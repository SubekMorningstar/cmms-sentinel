from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.config import settings

TZ = ZoneInfo(settings.timezone)

SENSORS: dict[str, dict[str, str]] = {
    "temperature": {
        "label": "Suhu",
        "short": "Suhu",
        "unit": "°C",
        "icon": "fa-thermometer-half",
        "key": "temperature",
        "hint": "Suhu bearing / proses",
    },
    "vibration": {
        "label": "Getaran",
        "short": "Getaran",
        "unit": "mm/s",
        "icon": "fa-signal",
        "key": "vibration",
        "hint": "RMS velocity ISO 10816",
    },
    "power": {
        "label": "Daya",
        "short": "Daya",
        "unit": "kW",
        "icon": "fa-bolt",
        "key": "power",
        "hint": "Beban motor aktual",
    },
    "sound": {
        "label": "Suara",
        "short": "Suara",
        "unit": "dB(A)",
        "icon": "fa-volume-up",
        "key": "sound",
        "hint": "Kebisingan area mesin",
    },
}

SENSOR_ORDER = ["temperature", "vibration", "power", "sound"]

ROLE_LABELS = {"admin": "Administrator", "teknisi": "Teknisi"}
WO_STATUS = {
    "pending": "Menunggu",
    "in_progress": "Dikerjakan",
    "awaiting_review": "Menunggu tinjauan",
    "resolved": "Selesai",
    "cancelled": "Dibatalkan",
}
PRIORITY = {
    "critical": "Kritis",
    "high": "Tinggi",
    "medium": "Sedang",
    "low": "Rendah",
}
ALERT_STATUS = {
    "open": "Aktif",
    "acknowledged": "Diketahui",
    "resolved": "Selesai",
}
ALERT_LEVEL = {"warning": "Peringatan", "critical": "Kritis"}
MACHINE_STATUS = {
    "running": "Berjalan",
    "standby": "Standby",
    "maintenance": "Perawatan",
    "offline": "Offline",
    "retired": "Arsip",
}
CRITICALITY = {
    "critical": "Kritis",
    "high": "Tinggi",
    "medium": "Sedang",
    "low": "Rendah",
}
WO_TYPE = {"corrective": "Korektif", "preventive": "Preventif", "inspection": "Inspeksi"}
SOURCE_LABEL = {
    "automatic": "Otomatis",
    "manual": "Manual",
    "preventive": "Preventif terjadwal",
    "seed": "Riwayat",
    "simulator": "Simulasi",
    "dataset-seed": "Dataset sintetis",
    "iot": "Gateway IoT",
    "gateway": "Gateway",
    "edge": "Edge",
    "api": "API",
}

MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ)


def format_dt(value: datetime | None) -> str:
    local = to_local(value)
    if local is None:
        return "—"
    return f"{local.day:02d} {MONTHS_ID[local.month - 1]} {local.year} · {local.strftime('%H:%M')}"


def format_date(value: datetime | None) -> str:
    local = to_local(value)
    if local is None:
        return "—"
    return f"{local.day:02d} {MONTHS_ID[local.month - 1]} {local.year}"


def format_time(value: datetime | None) -> str:
    local = to_local(value)
    if local is None:
        return "—"
    return local.strftime("%H:%M")


def relative_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = int((utcnow() - value).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        return "baru saja"
    if seconds < 3600:
        amount, unit = seconds // 60, "menit"
    elif seconds < 86400:
        amount, unit = seconds // 3600, "jam"
    else:
        amount, unit = seconds // 86400, "hari"
    return f"dalam {amount} {unit}" if future else f"{amount} {unit} lalu"


def local_day_label(value: datetime | None) -> str:
    local = to_local(value)
    if local is None:
        return "—"
    return f"{DAYS_ID[local.weekday()]}, {local.day} {MONTHS_ID[local.month - 1]} {local.year}"


def format_number(value: Any, decimals: int = 1) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_int(value: Any) -> str:
    return format_number(value, 0)


def initials(name: str | None) -> str:
    if not name:
        return "?"
    parts = [part for part in name.strip().split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def sensor_meta(sensor: str) -> dict[str, str]:
    return SENSORS.get(sensor, SENSORS["temperature"])


def sensor_state(value: float, threshold: dict) -> str:
    warning = float(threshold.get("warning", 0))
    critical = float(threshold.get("critical", 0))
    direction = threshold.get("direction", "above")
    if direction == "below":
        if value <= critical:
            return "critical"
        if value <= warning:
            return "warning"
        return "normal"
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "normal"


def sensor_score(value: float, threshold: dict) -> float:
    warning = float(threshold.get("warning", 0))
    critical = float(threshold.get("critical", 0))
    direction = threshold.get("direction", "above")
    if direction == "below":
        span = max(warning - critical, 0.001)
        if value >= warning:
            return 100.0
        if value > critical:
            return 85.0 - ((warning - value) / span) * 40.0
        return max(5.0, 45.0 - ((critical - value) / max(critical, 1.0)) * 40.0)
    if value <= warning:
        reference = max(warning, 0.001)
        return 100.0 - min(value / reference, 1.0) * 12.0
    if value < critical:
        span = max(critical - warning, 0.001)
        return 88.0 - ((value - warning) / span) * 43.0
    return max(5.0, 45.0 - ((value - critical) / max(critical, 1.0)) * 40.0)


def health_state(score: float | None) -> dict[str, str]:
    if score is None:
        return {"key": "unknown", "label": "Belum ada data", "tone": "neutral"}
    if score >= 85:
        return {"key": "good", "label": "Baik", "tone": "success"}
    if score >= 65:
        return {"key": "warning", "label": "Perhatian", "tone": "warning"}
    return {"key": "critical", "label": "Kritis", "tone": "danger"}


def oid(value: str | ObjectId | None) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not value:
        raise ValueError("ID tidak valid")
    return ObjectId(str(value))


def safe_next(value: str | None, fallback: str = "/dashboard") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return fallback
    return value


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return to_local(value).isoformat() if value.tzinfo else value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    raise TypeError(f"Tidak dapat serialisasi {type(value)!r}")


def dumps(value: Any) -> str:
    return (
        json.dumps(value, default=json_default, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def status_label(group: str, key: str | None) -> str:
    mapping = {
        "wo_status": WO_STATUS,
        "priority": PRIORITY,
        "alert_status": ALERT_STATUS,
        "alert_level": ALERT_LEVEL,
        "machine_status": MACHINE_STATUS,
        "criticality": CRITICALITY,
        "wo_type": WO_TYPE,
        "role": ROLE_LABELS,
        "source": SOURCE_LABEL,
    }.get(group, {})
    return mapping.get(key or "", key or "—")


def badge_tone(value: str | None) -> str:
    return {
        "critical": "danger",
        "high": "danger",
        "warning": "warning",
        "medium": "warning",
        "low": "info",
        "pending": "warning",
        "in_progress": "info",
        "resolved": "success",
        "cancelled": "neutral",
        "open": "danger",
        "acknowledged": "warning",
        "running": "success",
        "standby": "info",
        "maintenance": "warning",
        "offline": "neutral",
        "retired": "neutral",
    }.get(value or "", "neutral")
