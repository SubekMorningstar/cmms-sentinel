from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.database import alerts, machines, readings, thresholds
from app.security import check_csrf, flash, is_admin, require_admin, require_user
from app.services.analytics import machine_snapshot, thresholds_by_machine
from app.services.audit import audit
from app.utils import SENSOR_ORDER, sensor_meta, sensor_score, sensor_state, utcnow
from app.web import render

router = APIRouter()
GENERIC_THRESHOLDS = {
    "temperature": (75.0, 90.0),
    "vibration": (6.0, 10.0),
    "power": (15.0, 20.0),
    "sound": (82.0, 92.0),
}


def _threshold_context(
    request: Request,
    user: dict,
    selected: dict | None,
    machine_list: list[dict],
    *,
    draft: dict | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    rows: list[dict] = []
    latest = None
    recent_alerts: list[dict] = []
    snapshot = None
    configured = 0
    if selected:
        threshold_docs = {doc["sensor"]: doc for doc in thresholds().find({"machine_id": selected["_id"]})}
        configured = len(threshold_docs)
        latest = next(
            readings().find({"machine_id": selected["_id"]}, {"_id": 0}).sort("ts", -1).limit(1),
            None,
        )
        for sensor in SENSOR_ORDER:
            meta = sensor_meta(sensor)
            doc = threshold_docs.get(sensor) or {
                "sensor": sensor,
                "warning": GENERIC_THRESHOLDS[sensor][0],
                "critical": GENERIC_THRESHOLDS[sensor][1],
                "hysteresis": 0.6,
                "normal_reset_readings": 3,
                "enabled": True,
            }
            if draft and sensor in draft:
                doc = {**doc, **draft[sensor]}
            value = latest.get(sensor) if latest else None
            try:
                value_num = float(value) if value is not None else None
            except (TypeError, ValueError):
                value_num = None
            state = sensor_state(value_num, doc) if value_num is not None else "unknown"
            score = sensor_score(value_num, doc) if value_num is not None else None
            critical = float(doc.get("critical") or GENERIC_THRESHOLDS[sensor][1])
            warning = float(doc.get("warning") or GENERIC_THRESHOLDS[sensor][0])
            scale = max(critical * 1.2, 0.001)
            rows.append(
                {
                    "sensor": sensor,
                    "meta": meta,
                    "threshold": doc,
                    "value": value_num,
                    "state": state,
                    "score": score,
                    "meter": round(min(max(value_num / scale * 100, 0), 100), 1) if value_num is not None else 0,
                    "warning_pct": round(min(warning / scale * 100, 100), 1),
                    "critical_pct": round(min(critical / scale * 100, 100), 1),
                    "headroom": round(critical - value_num, 2) if value_num is not None else None,
                }
            )
        recent_alerts = list(
            alerts().find({"machine_id": selected["_id"]}).sort("last_seen", -1).limit(6)
        )
        for item in recent_alerts:
            item["id"] = str(item.pop("_id"))
        threshold_map = thresholds_by_machine([selected["_id"]]).get(selected["_id"], {})
        snapshot = machine_snapshot(selected, latest, threshold_map)

    return render(
        request,
        "thresholds/index.html",
        user=user,
        active_page="thresholds",
        machines=machine_list,
        machine=selected,
        rows=rows,
        latest=latest,
        snapshot=snapshot,
        recent_alerts=recent_alerts,
        configured=configured,
        can_edit=is_admin(user),
        error=error,
        status_code=status_code,
    )


def _select_machine(machine_code: str | None) -> tuple[dict | None, list[dict]]:
    machine_list = list(machines().find({"active": True}).sort("code", 1))
    selected = None
    if machine_code:
        selected = next((item for item in machine_list if item.get("code") == machine_code), None)
        if not selected:
            raise HTTPException(status_code=404, detail="Mesin tidak ditemukan atau sudah diarsipkan.")
    elif machine_list:
        selected = machine_list[0]
    return selected, machine_list


@router.get("/thresholds")
def thresholds_page(request: Request, machine: str | None = Query(None, max_length=40)):
    user = require_user(request)
    selected, machine_list = _select_machine(machine)
    return _threshold_context(request, user, selected, machine_list)


@router.post("/thresholds/{machine_id}")
async def thresholds_update(request: Request, machine_id: str, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    try:
        selected = machines().find_one({"_id": ObjectId(machine_id), "active": True})
    except Exception:
        selected = None
    if not selected:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan atau sudah diarsipkan.")
    raw = dict(await request.form())
    machine_list = list(machines().find({"active": True}).sort("code", 1))
    parse_errors: list[str] = []
    updates: dict[str, dict] = {}
    for sensor in SENSOR_ORDER:
        meta = sensor_meta(sensor)
        warning_raw = str(raw.get(f"{sensor}_warning", "")).strip().replace(",", ".")
        critical_raw = str(raw.get(f"{sensor}_critical", "")).strip().replace(",", ".")
        hysteresis_raw = str(raw.get(f"{sensor}_hysteresis", "")).strip().replace(",", ".") or "0"
        normal_raw = str(raw.get(f"{sensor}_normal", "")).strip() or "3"
        try:
            warning = float(warning_raw)
            critical = float(critical_raw)
            hysteresis = float(hysteresis_raw)
        except ValueError:
            parse_errors.append(f"Nilai {meta['label']} harus berupa angka.")
            continue
        try:
            normal = int(float(normal_raw))
        except ValueError:
            parse_errors.append(f"Jumlah pembacaan normal {meta['label']} tidak valid.")
            continue
        if warning <= 0 or critical <= warning:
            parse_errors.append(f"{meta['label']}: batas peringatan harus positif dan lebih kecil dari batas kritis.")
        if hysteresis < 0 or hysteresis > (critical - warning) / 2:
            parse_errors.append(f"{meta['label']}: histeresis maksimal setengah selisih batas.")
        if normal < 1 or normal > 10:
            parse_errors.append(f"{meta['label']}: pembacaan normal harus 1–10.")
        updates[sensor] = {
            "warning": round(warning, 2),
            "critical": round(critical, 2),
            "hysteresis": round(max(hysteresis, 0), 2),
            "normal_reset_readings": normal,
            "enabled": f"{sensor}_enabled" in raw,
        }
    if parse_errors:
        return _threshold_context(
            request,
            user,
            selected,
            machine_list,
            draft=updates,
            error=" ".join(parse_errors[:3]),
            status_code=400,
        )
    moment = utcnow()
    for sensor, values in updates.items():
        thresholds().update_one(
            {"machine_id": selected["_id"], "sensor": sensor},
            {
                "$set": {
                    **values,
                    "machine_code": selected.get("code"),
                    "unit": sensor_meta(sensor)["unit"],
                    "direction": "above",
                    "updated_at": moment,
                    "updated_by": user.get("nama_lengkap"),
                },
                "$setOnInsert": {"created_at": moment},
            },
            upsert=True,
        )
    audit(
        user,
        "Memperbarui threshold",
        "machine",
        selected["_id"],
        f"Ambang batas sensor {selected.get('code')} diperbarui.",
        request,
    )
    flash(request, "success", f"Threshold {selected.get('code')} berhasil diperbarui.")
    return RedirectResponse(f"/thresholds?machine={selected.get('code')}", status_code=303)
