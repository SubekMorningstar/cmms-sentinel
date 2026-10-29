from __future__ import annotations

import re
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.database import alerts, machines, readings, thresholds, work_orders
from app.security import check_csrf, flash, require_admin, require_user
from app.services.analytics import machine_snapshot, thresholds_by_machine
from app.services.audit import audit
from app.utils import (
    CRITICALITY,
    MACHINE_STATUS,
    SENSOR_ORDER,
    TZ,
    sensor_meta,
    to_local,
    utcnow,
)
from app.web import render

router = APIRouter()
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,19}$")
GENERIC_THRESHOLDS = {
    "temperature": (75.0, 90.0),
    "vibration": (6.0, 10.0),
    "sound": (82.0, 92.0),
}


def _form_values(machine: dict | None = None) -> dict:
    if not machine:
        return {
            "code": "",
            "name": "",
            "asset_type": "",
            "location": "",
            "manufacturer": "",
            "model": "",
            "serial_number": "",
            "criticality": "medium",
            "operational_status": "running",
            "rated_power_kw": "",
            "rated_speed_rpm": "",
            "installed_at": "",
            "notes": "",
        }
    return {
        "code": machine.get("code", ""),
        "name": machine.get("name", ""),
        "asset_type": machine.get("asset_type", ""),
        "location": machine.get("location", ""),
        "manufacturer": machine.get("manufacturer", ""),
        "model": machine.get("model", ""),
        "serial_number": machine.get("serial_number", ""),
        "criticality": machine.get("criticality", "medium"),
        "operational_status": machine.get("operational_status", "running"),
        "rated_power_kw": machine.get("rated_power_kw", ""),
        "rated_speed_rpm": machine.get("rated_speed_rpm", ""),
        "installed_at": to_local(machine.get("installed_at")).strftime("%Y-%m-%d")
        if machine.get("installed_at")
        else "",
        "notes": machine.get("notes", ""),
    }


def _parse_form(form: dict, *, creating: bool, current_id: ObjectId | None = None) -> tuple[dict, list[str]]:
    errors: list[str] = []
    code = form.get("code", "").strip().upper() if creating else ""
    name = form.get("name", "").strip()
    asset_type = form.get("asset_type", "").strip()
    location = form.get("location", "").strip()
    manufacturer = form.get("manufacturer", "").strip()
    model = form.get("model", "").strip()
    serial_number = form.get("serial_number", "").strip()
    criticality = form.get("criticality", "medium")
    operational_status = form.get("operational_status", "running")
    notes = form.get("notes", "").strip()
    if creating:
        if not CODE_RE.fullmatch(code):
            errors.append("Kode mesin wajib 3–20 karakter: huruf kapital, angka, atau tanda hubung.")
        elif machines().find_one({"code": code}):
            errors.append("Kode mesin sudah digunakan.")
    if not 2 <= len(name) <= 100:
        errors.append("Nama mesin wajib 2–100 karakter.")
    if not 2 <= len(asset_type) <= 80:
        errors.append("Tipe aset wajib 2–80 karakter.")
    if not 2 <= len(location) <= 100:
        errors.append("Lokasi wajib 2–100 karakter.")
    if criticality not in CRITICALITY:
        errors.append("Tingkat kekritisan tidak valid.")
    if operational_status not in MACHINE_STATUS or operational_status == "retired":
        errors.append("Status operasional tidak valid.")
    if len(notes) > 500:
        errors.append("Catatan maksimal 500 karakter.")
    power_raw = str(form.get("rated_power_kw", "")).strip().replace(",", ".")
    speed_raw = str(form.get("rated_speed_rpm", "")).strip().replace(",", ".")
    power = None
    speed = None
    if power_raw:
        try:
            power = float(power_raw)
            if not 0 < power <= 1000:
                raise ValueError
        except ValueError:
            errors.append("Daya terpasang harus berupa angka 0–1000 kW.")
    if speed_raw:
        try:
            speed = int(float(speed_raw))
            if not 0 < speed <= 100000:
                raise ValueError
        except ValueError:
            errors.append("Kecepatan nominal harus berupa angka 0–100.000 rpm.")
    installed_at = None
    date_raw = form.get("installed_at", "").strip()
    if date_raw:
        try:
            installed_at = datetime.strptime(date_raw, "%Y-%m-%d").replace(tzinfo=TZ).astimezone(timezone.utc)
        except ValueError:
            errors.append("Tanggal instalasi tidak valid.")
    data = {
        "name": name,
        "asset_type": asset_type,
        "location": location,
        "manufacturer": manufacturer[:100],
        "model": model[:100],
        "serial_number": serial_number[:100],
        "criticality": criticality,
        "operational_status": operational_status,
        "rated_power_kw": power,
        "rated_speed_rpm": speed,
        "installed_at": installed_at,
        "notes": notes,
    }
    if creating:
        data["code"] = code
    return data, errors


def _machines_with_snapshot(active: bool = True) -> list[dict]:
    docs = list(machines().find({"active": active}).sort("code", 1))
    if not docs:
        return []
    ids = [doc["_id"] for doc in docs]
    threshold_map = thresholds_by_machine(ids)
    alert_counts: dict = {}
    wo_counts: dict = {}
    for row in alerts().aggregate(
        [
            {"$match": {"machine_id": {"$in": ids}, "status": {"$in": ["open", "acknowledged"]}}},
            {"$group": {"_id": "$machine_id", "count": {"$sum": 1}}},
        ]
    ):
        alert_counts[row["_id"]] = row["count"]
    for row in work_orders().aggregate(
        [
            {"$match": {"machine_id": {"$in": ids}, "status": {"$in": ["pending", "in_progress"]}}},
            {"$group": {"_id": "$machine_id", "count": {"$sum": 1}}},
        ]
    ):
        wo_counts[row["_id"]] = row["count"]
    result = []
    for machine in docs:
        latest = next(
            readings().find({"machine_id": machine["_id"]}, {"_id": 0}).sort("ts", -1).limit(1),
            None,
        )
        result.append(
            machine_snapshot(
                machine,
                latest,
                threshold_map.get(machine["_id"], {}),
                alert_counts.get(machine["_id"], 0),
                wo_counts.get(machine["_id"], 0),
            )
        )
    return result


@router.get("/assets")
def assets_page(
    request: Request,
    q: str = "",
    status: str = "",
    criticality: str = "",
    archived: int = 0,
):
    user = require_user(request)
    snapshots = _machines_with_snapshot(active=not bool(archived))
    needle = q.strip().lower()
    if needle:
        snapshots = [
            item
            for item in snapshots
            if needle
            in " ".join(
                [
                    item["machine"].get("code", ""),
                    item["machine"].get("name", ""),
                    item["machine"].get("location", ""),
                    item["machine"].get("asset_type", ""),
                ]
            ).lower()
        ]
    if status:
        snapshots = [item for item in snapshots if item["machine"].get("operational_status") == status]
    if criticality:
        snapshots = [item for item in snapshots if item["machine"].get("criticality") == criticality]
    all_active = _machines_with_snapshot(active=True)
    summary = {
        "total": len(all_active),
        "running": sum(1 for item in all_active if item["machine"].get("operational_status") == "running"),
        "attention": sum(1 for item in all_active if item["health"]["key"] in {"warning", "critical"}),
        "offline": sum(1 for item in all_active if not item["online"]),
    }
    return render(
        request,
        "assets/index.html",
        user=user,
        active_page="assets",
        snapshots=snapshots,
        summary=summary,
        filters={"q": q, "status": status, "criticality": criticality, "archived": archived},
    )


@router.get("/assets/new")
def asset_new(request: Request):
    user = require_admin(request)
    return render(
        request,
        "assets/form.html",
        user=user,
        active_page="assets",
        active_page_title="Tambah aset",
        mode="new",
        machine=None,
        form=_form_values(),
        error=None,
    )


@router.post("/assets")
async def asset_create(request: Request, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    raw = dict(await request.form())
    return _save_asset(request, user, raw, creating=True)


@router.get("/assets/{machine_id}")
def asset_detail(request: Request, machine_id: str):
    user = require_user(request)
    try:
        oid = ObjectId(machine_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    machine = machines().find_one({"_id": oid})
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    latest = next(readings().find({"machine_id": oid}, {"_id": 0}).sort("ts", -1).limit(1), None)
    threshold_docs = list(thresholds().find({"machine_id": oid}).sort("sensor", 1))
    threshold_map = {doc["sensor"]: doc for doc in threshold_docs}
    open_alerts = alerts().count_documents({"machine_id": oid, "status": {"$in": ["open", "acknowledged"]}})
    open_wos = work_orders().count_documents({"machine_id": oid, "status": {"$in": ["pending", "in_progress"]}})
    snapshot = machine_snapshot(machine, latest, threshold_map, open_alerts, open_wos)
    alert_docs = list(alerts().find({"machine_id": oid}).sort("last_seen", -1).limit(5))
    for item in alert_docs:
        item["id"] = str(item.pop("_id"))
    wo_docs = list(work_orders().find({"machine_id": oid}).sort("created_at", -1).limit(5))
    for item in wo_docs:
        item["id"] = str(item.pop("_id"))
    return render(
        request,
        "assets/detail.html",
        user=user,
        active_page="assets",
        active_page_title=machine.get("name"),
        machine=machine,
        snapshot=snapshot,
        thresholds=threshold_docs,
        alert_docs=alert_docs,
        wo_docs=wo_docs,
    )


@router.get("/assets/{machine_id}/edit")
def asset_edit(request: Request, machine_id: str):
    user = require_admin(request)
    try:
        machine = machines().find_one({"_id": ObjectId(machine_id)})
    except Exception:
        machine = None
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    return render(
        request,
        "assets/form.html",
        user=user,
        active_page="assets",
        active_page_title=f"Edit {machine.get('name')}",
        mode="edit",
        machine=machine,
        form=_form_values(machine),
        error=None,
    )


@router.post("/assets/{machine_id}")
async def asset_update(request: Request, machine_id: str, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    try:
        machine = machines().find_one({"_id": ObjectId(machine_id)})
    except Exception:
        machine = None
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    raw = dict(await request.form())
    return _save_asset(request, user, raw, creating=False, machine=machine)


def _save_asset(
    request: Request,
    user: dict,
    raw: dict,
    *,
    creating: bool,
    machine: dict | None = None,
):
    data, errors = _parse_form(raw, creating=creating, current_id=machine["_id"] if machine else None)
    form = _form_values(machine)
    for key in form:
        if key == "code" and not creating:
            continue
        form[key] = raw.get(key, "")
    if errors:
        return render(
            request,
            "assets/form.html",
            user=user,
            active_page="assets",
            active_page_title="Tambah aset" if creating else f"Edit {machine.get('name')}",
            mode="new" if creating else "edit",
            machine=machine,
            form=form,
            error=errors[0],
            status_code=400,
        )
    now = utcnow()
    if creating:
        doc = {
            **data,
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
        inserted = machines().insert_one(doc)
        machine_id = inserted.inserted_id
        _insert_default_thresholds(machine_id, data)
        audit(
            user,
            "Menambah mesin",
            "machine",
            machine_id,
            f"{data['code']} · {data['name']} ditambahkan.",
            request,
        )
        flash(request, "success", f"Mesin {data['code']} berhasil ditambahkan beserta threshold awal.")
        return RedirectResponse(f"/assets/{machine_id}", status_code=303)
    updates = {**data, "updated_at": now}
    machines().update_one({"_id": machine["_id"]}, {"$set": updates})
    audit(
        user,
        "Memperbarui mesin",
        "machine",
        machine["_id"],
        f"Data {machine.get('code')} diperbarui.",
        request,
    )
    flash(request, "success", "Data mesin berhasil diperbarui.")
    return RedirectResponse(f"/assets/{machine['_id']}", status_code=303)


def _insert_default_thresholds(machine_id: ObjectId, data: dict) -> None:
    from app.services.dataset import THRESHOLD_SPECS

    known = THRESHOLD_SPECS.get(data.get("code", ""), {})
    docs = []
    for sensor in SENSOR_ORDER:
        if sensor in known:
            warning, critical = known[sensor]
        elif sensor == "power":
            rated = float(data.get("rated_power_kw") or 15.0)
            warning, critical = round(rated * 1.12, 1), round(rated * 1.35, 1)
        else:
            warning, critical = GENERIC_THRESHOLDS[sensor]
        docs.append(
            {
                "machine_id": machine_id,
                "sensor": sensor,
                "unit": sensor_meta(sensor)["unit"],
                "warning": warning,
                "critical": critical,
                "direction": "above",
                "hysteresis": round((critical - warning) * 0.06, 2),
                "normal_reset_readings": 3,
                "enabled": True,
                "updated_at": utcnow(),
            }
        )
    thresholds().insert_many(docs)


@router.post("/assets/{machine_id}/archive")
def asset_archive(request: Request, machine_id: str, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    try:
        machine = machines().find_one({"_id": ObjectId(machine_id)})
    except Exception:
        machine = None
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    open_wos = work_orders().count_documents(
        {"machine_id": machine["_id"], "status": {"$in": ["pending", "in_progress"]}}
    )
    if open_wos:
        flash(request, "error", "Mesin tidak dapat diarsipkan karena masih memiliki work order aktif.")
        return RedirectResponse(f"/assets/{machine['_id']}", status_code=303)
    machines().update_one(
        {"_id": machine["_id"]},
        {"$set": {"active": False, "operational_status": "retired", "updated_at": utcnow()}},
    )
    audit(user, "Mengarsipkan mesin", "machine", machine["_id"], f"{machine.get('code')} diarsipkan.", request)
    flash(request, "success", "Mesin berhasil diarsipkan. Riwayat sensor dan work order tetap tersimpan.")
    return RedirectResponse("/assets?archived=1", status_code=303)


@router.post("/assets/{machine_id}/restore")
def asset_restore(request: Request, machine_id: str, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    try:
        machine = machines().find_one({"_id": ObjectId(machine_id)})
    except Exception:
        machine = None
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan.")
    machines().update_one(
        {"_id": machine["_id"]},
        {"$set": {"active": True, "operational_status": "standby", "updated_at": utcnow()}},
    )
    audit(user, "Memulihkan mesin", "machine", machine["_id"], f"{machine.get('code')} diaktifkan kembali.", request)
    flash(request, "success", "Mesin berhasil diaktifkan kembali dengan status standby.")
    return RedirectResponse(f"/assets/{machine['_id']}", status_code=303)
