from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.database import machines, readings
from app.security import check_csrf, flash, require_admin
from app.services.audit import audit
from app.services.simulation import (
    SCENARIOS,
    SEVERITIES,
    control_map,
    experiment_history,
    repeat_experiment,
    run_experiment,
    update_machine_control,
)
from app.services.telemetry import REAL_SOURCES
from app.utils import TZ, to_local, utcnow
from app.web import render

router = APIRouter()


def _parse_local_datetime(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Format waktu eksperimen tidak valid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(timezone.utc)


@router.get("/simulation")
def simulation_page(request: Request):
    user = require_admin(request)
    controls = control_map()
    machine_rows = []
    for machine in machines().find({"active": True}).sort("code", 1):
        latest = readings().find_one(
            {"machine_id": machine["_id"]},
            {"_id": 0, "ts": 1, "source": 1},
            sort=[("ts", -1)],
        )
        control = controls.get(machine["_id"], {})
        has_live_source = bool(
            readings().find_one(
                {"machine_id": machine["_id"], "source": {"$in": sorted(REAL_SOURCES)}},
                {"_id": 1},
            )
        )
        machine_rows.append(
            {
                **machine,
                "status": control.get("status", "running"),
                "scenario_id": control.get("scenario_id") or "normal",
                "seed": control.get("seed", 20261028),
                "severity": control.get("severity", "high"),
                "severity_label": SEVERITIES.get(control.get("severity", "high"), SEVERITIES["high"])["label"],
                "duration_minutes": control.get("duration_minutes", 60),
                "scenario_started_at": control.get("scenario_started_at"),
                "scenario_ends_at": control.get("scenario_ends_at"),
                "latest": latest,
                "has_live_source": has_live_source,
                "scenario_active": bool(
                    control.get("status", "running") == "running"
                    and control.get("scenario_id")
                    and control.get("scenario_ends_at")
                    and control["scenario_ends_at"] > utcnow()
                    and not has_live_source
                ),
            }
        )
    range_end = utcnow().replace(second=0, microsecond=0)
    range_end -= timedelta(minutes=range_end.minute % 5)
    range_start = range_end - timedelta(minutes=60)
    return render(
        request,
        "simulation/index.html",
        user=user,
        active_page="simulation",
        machines=machine_rows,
        scenarios=SCENARIOS,
        experiments=experiment_history(),
        default_start=to_local(range_start).strftime("%Y-%m-%dT%H:%M"),
        default_end=to_local(range_end).strftime("%Y-%m-%dT%H:%M"),
    )


@router.post("/simulation/control")
def simulation_control(
    request: Request,
    machine_code: str = Form(""),
    status: str = Form(""),
    scenario_id: str = Form(""),
    severity: str = Form("high"),
    duration_minutes: int = Form(60),
    seed: int = Form(20261028),
    csrf_token: str = Form(""),
):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    machine = machines().find_one({"code": machine_code, "active": True})
    if not machine:
        flash(request, "error", "Mesin virtual tidak ditemukan atau tidak aktif.")
        return RedirectResponse("/simulation", status_code=303)
    try:
        control = update_machine_control(
            machine,
            status=status,
            scenario_id=scenario_id.strip(),
            severity=severity,
            duration_minutes=duration_minutes,
            seed=seed,
            actor=user,
        )
    except ValueError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse("/simulation", status_code=303)
    action = "Mengubah kendali simulator"
    detail = (
        f"{machine_code} · status {control['status']} · "
        f"skenario {control['scenario_id'] or 'normal'} · seed {seed}."
    )
    audit(user, action, "simulation", machine["_id"], detail, request)
    flash(request, "success", f"Kendali {machine_code} disimpan; berlaku pada siklus telemetry berikutnya.")
    return RedirectResponse("/simulation", status_code=303)


@router.post("/simulation/experiments")
def simulation_experiment(
    request: Request,
    machine_code: str = Form(""),
    scenario_id: str = Form(""),
    duration_minutes: int = Form(60),
    start_at: str = Form(""),
    end_at: str = Form(""),
    severity: str = Form("high"),
    seed: str = Form(""),
    csrf_token: str = Form(""),
):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    parsed_seed = None
    if seed.strip():
        try:
            parsed_seed = int(seed)
        except ValueError:
            flash(request, "error", "Seed harus berupa bilangan bulat.")
            return RedirectResponse("/simulation", status_code=303)
    try:
        parsed_start = _parse_local_datetime(start_at)
        parsed_end = _parse_local_datetime(end_at)
        if (parsed_start is None) != (parsed_end is None):
            raise ValueError("Waktu mulai dan akhir eksperimen harus diisi bersama.")
        if parsed_start and parsed_end:
            range_minutes = (parsed_end - parsed_start).total_seconds() / 60
            if not range_minutes.is_integer():
                raise ValueError("Rentang eksperimen harus menggunakan menit bulat.")
            duration_minutes = int(range_minutes)
        result = run_experiment(
            machine_code,
            scenario_id,
            duration_minutes,
            parsed_seed,
            user,
            severity=severity,
            start_at=parsed_start,
        )
    except ValueError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse("/simulation", status_code=303)
    metrics = result["metrics"]
    audit(
        user,
        "Menjalankan eksperimen simulasi",
        "simulation",
        result["run_id"],
        (
            f"{machine_code} · {result['scenario_label']} · seed {result['seed']} · "
            f"recall {metrics['recall_pct']}% · {metrics['work_orders_created']} work order."
        ),
        request,
    )
    flash(
        request,
        "success",
        (
            f"Eksperimen {result['run_id']} selesai: recall "
            f"{metrics['recall_pct'] if metrics['recall_pct'] is not None else '—'}% "
            f"dan {metrics['work_orders_created']} work order dibuat."
        ),
    )
    return RedirectResponse("/simulation", status_code=303)


@router.post("/simulation/experiments/{run_id}/repeat")
def simulation_experiment_repeat(request: Request, run_id: str, csrf_token: str = Form("")):
    user = require_admin(request)
    check_csrf(request, csrf_token)
    try:
        result = repeat_experiment(run_id, user)
    except ValueError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse("/simulation", status_code=303)
    metrics = result["metrics"]
    audit(
        user,
        "Mengulang eksperimen simulasi",
        "simulation",
        result["run_id"],
        (
            f"{result['machine_code']} · {result['scenario_label']} · seed {result['seed']} · "
            f"recall {metrics['recall_pct']}%."
        ),
        request,
    )
    flash(
        request,
        "success",
        f"Eksperimen diulang dengan seed {result['seed']} dan baseline tersimpan; ID baru {result['run_id']}.",
    )
    return RedirectResponse("/simulation", status_code=303)
