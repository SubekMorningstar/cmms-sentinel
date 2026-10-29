from __future__ import annotations

import csv
import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from app.config import settings
from app.database import (
    alerts,
    audit_logs,
    counters,
    create_indexes,
    ensure_timeseries_collection,
    machines,
    readings,
    simulation_controls,
    simulation_runs,
    thresholds,
    users,
    work_orders,
)
from app.security import hash_password
from app.services.thresholds import evaluate_reading
from app.services.telemetry import DATASET_SOURCE, REAL_SOURCES
from app.services.work_orders import create_work_order
from app.utils import SENSOR_ORDER, format_number, sensor_meta, to_local, utcnow

INTERVAL_MINUTES = 5
DATASET_DAYS = 90

MACHINE_SPECS = [
    {
        "code": "CNC-01",
        "name": "CNC Milling VCN-530",
        "asset_type": "CNC Milling Machine",
        "location": "Line A · Machining",
        "manufacturer": "Mazak",
        "model": "VCN-530C",
        "serial_number": "MZK-530-2201",
        "criticality": "high",
        "installed_at": datetime(2021, 3, 18, tzinfo=None),
        "rated_power_kw": 22.5,
        "rated_speed_rpm": 8000,
        "operational_status": "running",
        "notes": "Pusat pemesinan utama untuk komponen presisi line A.",
    },
    {
        "code": "PMP-02",
        "name": "Coolant Pump NK 65-200",
        "asset_type": "Centrifugal Pump",
        "location": "Utility · Cooling",
        "manufacturer": "Grundfos",
        "model": "NK 65-200",
        "serial_number": "GRF-NK-1187",
        "criticality": "high",
        "installed_at": datetime(2020, 9, 7, tzinfo=None),
        "rated_power_kw": 15.0,
        "rated_speed_rpm": 2900,
        "operational_status": "running",
        "notes": "Pompa sirkulasi coolant utama; standby unit tersedia.",
    },
    {
        "code": "CMP-03",
        "name": "Air Compressor GA 37",
        "asset_type": "Screw Air Compressor",
        "location": "Utility · Compressed Air",
        "manufacturer": "Atlas Copco",
        "model": "GA 37",
        "serial_number": "AC-GA37-0912",
        "criticality": "critical",
        "installed_at": datetime(2019, 11, 25, tzinfo=None),
        "rated_power_kw": 37.0,
        "rated_speed_rpm": 3000,
        "operational_status": "running",
        "notes": "Satu-satunya sumber udara tekan untuk seluruh plant.",
    },
    {
        "code": "CNV-04",
        "name": "Assembly Conveyor BM-1200",
        "asset_type": "Belt Conveyor",
        "location": "Line B · Assembly",
        "manufacturer": "Interroll",
        "model": "BM-1200",
        "serial_number": "INT-BM-4410",
        "criticality": "medium",
        "installed_at": datetime(2022, 6, 13, tzinfo=None),
        "rated_power_kw": 5.5,
        "rated_speed_rpm": 1450,
        "operational_status": "running",
        "notes": "Konveyor transfer komponen dari stasiun 1 ke stasiun 6.",
    },
    {
        "code": "GRD-05",
        "name": "Surface Grinder ACC-820",
        "asset_type": "Surface Grinder",
        "location": "Line A · Finishing",
        "manufacturer": "Okamoto",
        "model": "ACC-820",
        "serial_number": "OKM-820-3320",
        "criticality": "medium",
        "installed_at": datetime(2023, 2, 2, tzinfo=None),
        "rated_power_kw": 7.5,
        "rated_speed_rpm": 1750,
        "operational_status": "standby",
        "notes": "Grinding finishing untuk dies dan tooling presisi.",
    },
]

THRESHOLD_SPECS: dict[str, dict[str, tuple[float, float]]] = {
    "CNC-01": {
        "temperature": (72.0, 85.0),
        "vibration": (6.5, 10.5),
        "power": (22.0, 28.0),
        "sound": (82.0, 90.0),
    },
    "PMP-02": {
        "temperature": (70.0, 82.0),
        "vibration": (5.5, 9.0),
        "power": (14.0, 17.0),
        "sound": (80.0, 88.0),
    },
    "CMP-03": {
        "temperature": (88.0, 100.0),
        "vibration": (7.0, 11.0),
        "power": (34.0, 42.0),
        "sound": (85.0, 94.0),
    },
    "CNV-04": {
        "temperature": (65.0, 78.0),
        "vibration": (4.5, 7.5),
        "power": (6.5, 8.5),
        "sound": (78.0, 86.0),
    },
    "GRD-05": {
        "temperature": (68.0, 80.0),
        "vibration": (5.0, 8.0),
        "power": (8.0, 10.5),
        "sound": (80.0, 89.0),
    },
}

PROFILES = {
    "CNC-01": {"temp": (54, 12), "vib": (2.2, 3.1), "power": 18.0, "sound": (70, 7), "phase": 0.3},
    "PMP-02": {"temp": (47, 14), "vib": (1.8, 2.3), "power": 11.0, "sound": (66, 6), "phase": 1.1},
    "CMP-03": {"temp": (68, 14), "vib": (3.3, 1.6), "power": 30.0, "sound": (74, 6), "phase": 2.0},
    "CNV-04": {"temp": (40, 12), "vib": (1.6, 1.4), "power": 4.6, "sound": (63, 5), "phase": 0.7},
    "GRD-05": {"temp": (43, 14), "vib": (1.9, 1.6), "power": 6.0, "sound": (67, 6), "phase": 1.7},
}

SCENARIO_META = [
    {
        "code": "CNC-01",
        "fault_mode": "Degradasi bearing spindle",
        "severity": "critical",
        "start_offset_hours": -72,
        "duration_hours": 72,
        "sensors": "vibration,temperature,sound",
        "description": "Kenaikan progresif getaran, suhu, dan kebisingan akibat keausan bearing spindle.",
    },
    {
        "code": "PMP-02",
        "fault_mode": "Kavitasi & misalignment pompa",
        "severity": "critical",
        "start_offset_hours": -30,
        "duration_hours": 30,
        "sensors": "vibration,temperature,sound",
        "description": "Kavitasi dan ketidaksejajaran kopling meningkatkan getaran serta suhu pompa.",
    },
    {
        "code": "CMP-03",
        "fault_mode": "Degradasi sistem pendinginan",
        "severity": "warning",
        "start_offset_hours": -120,
        "duration_hours": 4,
        "sensors": "temperature",
        "description": "Suhu buang kompresor meningkat akibat fouling pada cooler.",
    },
    {
        "code": "CNV-04",
        "fault_mode": "Kontaminasi bearing conveyor",
        "severity": "warning",
        "start_offset_hours": -192,
        "duration_hours": 5,
        "sensors": "vibration,sound",
        "description": "Getaran pulley meningkat akibat kontaminasi dan pelumasan berlebih.",
    },
    {
        "code": "GRD-05",
        "fault_mode": "Overload motor grinding",
        "severity": "warning",
        "start_offset_hours": -240,
        "duration_hours": 4,
        "sensors": "power,temperature",
        "description": "Beban motor meningkat saat siklus dressing dan pemakanan material keras.",
    },
    {
        "code": "PMP-02",
        "fault_mode": "Misalignment transient",
        "severity": "warning",
        "start_offset_hours": -288,
        "duration_hours": 6,
        "sensors": "vibration",
        "description": "Misalignment sementara setelah pekerjaan penyambungan pipa.",
    },
]


def _load_factor(ts: datetime) -> float:
    local = to_local(ts)
    hour = local.hour + local.minute / 60
    if 6 <= hour < 22:
        factor = 0.82 + 0.16 * math.sin(math.pi * (hour - 6) / 16)
    else:
        factor = 0.55 + 0.02 * math.sin(math.pi * hour / 12)
    if local.weekday() >= 5:
        factor *= 0.72
    return factor


def _anomaly(code: str, ts: datetime, now: datetime) -> dict[str, float]:
    deltas = {sensor: 0.0 for sensor in SENSOR_ORDER}
    if code == "CNC-01":
        start = now - timedelta(hours=72)
        if start <= ts <= now:
            p = (ts - start).total_seconds() / (72 * 3600)
            deltas["temperature"] += 12.0 * p
            deltas["vibration"] += 7.3 * (p ** 1.25)
            deltas["sound"] += 8.0 * p
            deltas["power"] += 1.7 * p
    elif code == "PMP-02":
        start = now - timedelta(hours=30)
        if start <= ts <= now:
            p = (ts - start).total_seconds() / (30 * 3600)
            deltas["temperature"] += 10.0 * p
            deltas["vibration"] += 5.8 * (p ** 1.1)
            deltas["sound"] += 10.0 * p
            deltas["power"] += 0.8 * p
        start = now - timedelta(hours=288)
        end = start + timedelta(hours=6)
        if start <= ts <= end:
            ramp = min((ts - start).total_seconds() / 3600, (end - ts).total_seconds() / 3600, 1.0)
            deltas["vibration"] += 2.6 * ramp
            deltas["temperature"] += 4.0 * ramp
            deltas["sound"] += 4.0 * ramp
    elif code == "CMP-03":
        start = now - timedelta(hours=120)
        end = start + timedelta(hours=4)
        if start <= ts <= end:
            ramp = min((ts - start).total_seconds() / 3600, (end - ts).total_seconds() / 3600, 1.0)
            deltas["temperature"] += 9.0 * ramp
            deltas["vibration"] += 1.2 * ramp
            deltas["sound"] += 3.0 * ramp
    elif code == "CNV-04":
        start = now - timedelta(hours=192)
        end = start + timedelta(hours=5)
        if start <= ts <= end:
            ramp = min((ts - start).total_seconds() / 3600, (end - ts).total_seconds() / 3600, 1.0)
            deltas["vibration"] += 2.6 * ramp
            deltas["temperature"] += 4.0 * ramp
            deltas["sound"] += 4.0 * ramp
    elif code == "GRD-05":
        start = now - timedelta(hours=240)
        end = start + timedelta(hours=4)
        if start <= ts <= end:
            ramp = min((ts - start).total_seconds() / 3600, (end - ts).total_seconds() / 3600, 1.0)
            deltas["power"] += 2.6 * ramp
            deltas["temperature"] += 4.0 * ramp
            deltas["sound"] += 3.0 * ramp
    return deltas


def _generate_rows(
    start: datetime,
    end: datetime,
    seed_base: int,
    anomaly_now: datetime | None = None,
) -> list[dict]:
    points = int((end - start).total_seconds() // (INTERVAL_MINUTES * 60)) + 1
    rows: list[dict] = []
    for index, spec in enumerate(MACHINE_SPECS):
        profile = PROFILES[spec["code"]]
        rng = random.Random(seed_base + index)
        for point in range(points):
            ts = start + timedelta(minutes=point * INTERVAL_MINUTES)
            load = _load_factor(ts)
            noise_temp = rng.gauss(0, 0.65)
            noise_vib = abs(rng.gauss(0, 0.13))
            noise_power = rng.gauss(0, 0.35)
            noise_sound = rng.gauss(0, 0.8)
            temp = (
                profile["temp"][0]
                + profile["temp"][1] * load
                + 1.1 * math.sin(2 * math.pi * point / 288 + profile["phase"])
                + noise_temp
            )
            vibration = (
                profile["vib"][0]
                + profile["vib"][1] * load
                + 0.25 * math.sin(2 * math.pi * point / 96 + profile["phase"])
                + noise_vib
            )
            power = max(profile["power"] * load + noise_power, 0.4)
            sound = (
                profile["sound"][0]
                + profile["sound"][1] * load
                + 0.7 * math.sin(2 * math.pi * point / 144 + profile["phase"])
                + noise_sound
            )
            extra = _anomaly(spec["code"], ts, anomaly_now) if anomaly_now else {}
            row = {
                "ts": ts,
                "machine_code": spec["code"],
                "temperature": round(temp + extra.get("temperature", 0.0), 2),
                "vibration": round(max(vibration + extra.get("vibration", 0.0), 0.0), 2),
                "power": round(max(power + extra.get("power", 0.0), 0.0), 2),
                "sound": round(max(sound + extra.get("sound", 0.0), 35.0), 2),
            }
            rows.append(row)
    rows.sort(key=lambda item: (item["ts"], item["machine_code"]))
    return rows


def generate_series(now: datetime | None = None) -> tuple[list[dict], dict[str, dict], list[dict]]:
    now = now or utcnow()
    now = now.replace(second=0, microsecond=0)
    now = now - timedelta(minutes=now.minute % INTERVAL_MINUTES)
    start = now - timedelta(days=DATASET_DAYS)
    rows = _generate_rows(start, now, seed_base=1200, anomaly_now=now)
    latest_by_code = {row["machine_code"]: row for row in rows[-len(MACHINE_SPECS) :]}
    scenarios = []
    for item in SCENARIO_META:
        start_dt = now + timedelta(hours=item["start_offset_hours"])
        end_dt = start_dt + timedelta(hours=item["duration_hours"])
        scenarios.append({**item, "start": start_dt, "end": end_dt})
    return rows, latest_by_code, scenarios


def _read_dataset_scenarios() -> list[dict]:
    with settings.dataset_scenarios_csv.open(newline="", encoding="utf-8") as handle:
        return [
            {
                **row,
                "code": row["machine_code"],
                "sensors": row["affected_sensors"],
                "start": datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00")),
                "end": datetime.fromisoformat(row["end_utc"].replace("Z", "+00:00")),
            }
            for row in csv.DictReader(handle)
        ]


def extend_dataset_history() -> dict[str, Any]:
    if not settings.dataset_readings_csv.is_file():
        raise FileNotFoundError(f"Dataset sensor tidak ditemukan: {settings.dataset_readings_csv}")
    if not settings.dataset_scenarios_csv.is_file():
        raise FileNotFoundError(f"Dataset skenario tidak ditemukan: {settings.dataset_scenarios_csv}")

    with settings.dataset_readings_csv.open(newline="", encoding="utf-8") as handle:
        csv_rows = [
            {
                "ts": datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")),
                "machine_code": row["machine_code"],
                "temperature": float(row["temperature_c"]),
                "vibration": float(row["vibration_mm_s"]),
                "power": float(row["power_kw"]),
                "sound": float(row["sound_db_a"]),
            }
            for row in csv.DictReader(handle)
        ]
    if not csv_rows:
        raise ValueError("Dataset sensor kosong; perlu data sebelum menambah riwayat.")

    dataset_start = min(row["ts"] for row in csv_rows)
    dataset_end = max(row["ts"] for row in csv_rows)
    target_start = dataset_end - timedelta(days=DATASET_DAYS)
    history_end = dataset_start - timedelta(minutes=INTERVAL_MINUTES)
    history_rows = (
        _generate_rows(target_start, history_end, seed_base=5200)
        if target_start <= history_end
        else []
    )
    rows = sorted([*history_rows, *csv_rows], key=lambda item: (item["ts"], item["machine_code"]))
    scenarios = _read_dataset_scenarios()
    _write_dataset(rows, scenarios)

    codes = sorted({row["machine_code"] for row in rows})
    machine_map = {item["code"]: item for item in machines().find({"code": {"$in": codes}})}
    by_machine: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_machine[row["machine_code"]].append(row)

    inserted = 0
    skipped_real_machines = []
    skipped_missing_machines = []
    for code in codes:
        machine = machine_map.get(code)
        if not machine:
            skipped_missing_machines.append(code)
            continue
        machine_id = machine["_id"]
        if readings().find_one(
            {"machine_id": machine_id, "source": {"$in": sorted(REAL_SOURCES)}},
            {"_id": 1},
        ):
            skipped_real_machines.append(code)
            continue

        earliest = readings().find_one(
            {"machine_id": machine_id},
            {"ts": 1},
            sort=[("ts", 1)],
        )
        candidates = [
            row
            for row in by_machine[code]
            if earliest is None or row["ts"] < earliest["ts"]
        ]
        batch = []
        for row in candidates:
            batch.append(
                {
                    "ts": row["ts"],
                    "machine_id": machine_id,
                    "machine_code": code,
                    "temperature": row["temperature"],
                    "vibration": row["vibration"],
                    "power": row["power"],
                    "sound": row["sound"],
                    "quality": "good",
                    "source": DATASET_SOURCE,
                }
            )
            if len(batch) >= 4000:
                result = readings().insert_many(batch, ordered=False)
                inserted += len(result.inserted_ids)
                batch = []
        if batch:
            result = readings().insert_many(batch, ordered=False)
            inserted += len(result.inserted_ids)

    return {
        "readings_added": inserted,
        "csv_readings": len(rows),
        "synthetic_history_readings": len(history_rows),
        "dataset_start": rows[0]["ts"],
        "dataset_end": rows[-1]["ts"],
        "skipped_real_machines": skipped_real_machines,
        "skipped_missing_machines": skipped_missing_machines,
        "dataset": str(settings.dataset_readings_csv),
    }


def _write_dataset(rows: list[dict], scenarios: list[dict]) -> None:
    settings.dataset_readings_csv.parent.mkdir(parents=True, exist_ok=True)
    with settings.dataset_readings_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_utc",
                "machine_code",
                "temperature_c",
                "vibration_mm_s",
                "power_kw",
                "sound_db_a",
                "source",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["ts"].isoformat().replace("+00:00", "Z"),
                    row["machine_code"],
                    f"{row['temperature']:.2f}",
                    f"{row['vibration']:.2f}",
                    f"{row['power']:.2f}",
                    f"{row['sound']:.2f}",
                    "cmms-sentinel-synthetic",
                ]
            )
    with settings.dataset_scenarios_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["machine_code", "fault_mode", "severity", "start_utc", "end_utc", "affected_sensors", "description"]
        )
        for item in scenarios:
            writer.writerow(
                [
                    item["code"],
                    item["fault_mode"],
                    item["severity"],
                    item["start"].isoformat().replace("+00:00", "Z"),
                    item["end"].isoformat().replace("+00:00", "Z"),
                    item["sensors"],
                    item["description"],
                ]
            )
    digest = hashlib.sha256(settings.dataset_readings_csv.read_bytes()).hexdigest()
    first, last = rows[0]["ts"], rows[-1]["ts"]
    metadata = f"""# Dataset Sensor CMMS Sentinel

Dataset ini disertakan agar aplikasi CMMS/CBM dapat langsung dioperasikan tanpa menunggu gateway fisik.
Data bersifat sintetis dan direkayasa untuk meniru pola operasi mesin industri, bukan rekaman rahasia pabrik.

## Ringkasan

- **Periode:** {to_local(first).strftime('%d %b %Y %H:%M')} s.d. {to_local(last).strftime('%d %b %Y %H:%M')} WIB
- **Interval:** {INTERVAL_MINUTES} menit
- **Mesin:** {len(MACHINE_SPECS)} aset industri
- **Kanal sensor:** suhu (°C), getaran RMS (mm/s), daya (kW), suara (dB(A))
- **Jumlah baris:** {len(rows):,}
- **Format waktu:** ISO 8601 UTC (`Z`)
- **SHA-256:** `{digest}`
- **Lisensi:** CC BY 4.0 — bebas digunakan dengan atribusi "CMMS Sentinel Dataset".

## Sumber & kalibrasi

Data dibangun secara sintetis dengan parameter yang mengacu pada referensi publik:

1. **ISO 10816-3** untuk klasifikasi tingkat keparahan getaran mesin industri.
2. **IEC 60034-1** untuk batas kenaikan suhu mesin listrik.
3. **OSHA 1910.95** untuk paparan kebisingan area kerja.
4. Pola degradasi bearing, kavitasi pompa, dan overload motor yang umum dibahas pada literatur
   condition monitoring industri (mis. CWRU Bearing Data Center untuk karakteristik sinyal getaran).

Tidak ada data pelanggan atau rahasia perusahaan yang digunakan. Nilai baseline, siklus shift,
gangguan, dan noise dibuat deterministik dengan seed agar dapat direproduksi.

## Skenario gangguan

- CNC-01: degradasi bearing spindle progresif selama 72 jam terakhir.
- PMP-02: kavitasi dan misalignment 30 jam terakhir, plus misalignment transient 12 hari lalu.
- CMP-03: degradasi pendinginan 5 hari lalu.
- CNV-04: kontaminasi bearing conveyor 8 hari lalu.
- GRD-05: overload motor grinding 10 hari lalu.

Label ground-truth tersedia di `fault_scenarios.csv`. Kolom tersebut **tidak** dimasukkan ke data sensor
utama agar pipeline deteksi tetap realistis.

## Struktur

`sensor_readings.csv`:

| Kolom | Satuan | Keterangan |
|---|---|---|
| timestamp_utc | ISO 8601 | Waktu pembacaan (UTC) |
| machine_code | — | Kode aset |
| temperature_c | °C | Suhu bearing/proses |
| vibration_mm_s | mm/s RMS | Kecepatan getaran |
| power_kw | kW | Daya motor |
| sound_db_a | dB(A) | Kebisingan area |
| source | — | Asal data |

## Cara memuat ulang

```bash
# Tambahkan riwayat sintetis lama tanpa menghapus pembacaan yang sudah ada
python seed.py --extend-history

# Reset destruktif: buat ulang seluruh database dan dataset 90 hari
python seed.py --reset --yes
```

Perintah `--extend-history` aman dijalankan berulang kali. Ia hanya menambahkan pembacaan yang lebih lama,
melewati mesin yang memiliki sumber telemetry langsung, dan tidak menghapus atau menimpa data yang ada.
Dataset CSV berisi 90 hari data sintetis dengan interval 5 menit.
"""
    settings.dataset_metadata.write_text(metadata, encoding="utf-8")


def _insert_users() -> tuple[dict, dict]:
    seed_specs = [
        {
            "email": settings.seed_admin_email,
            "nama_lengkap": "Administrator",
            "role": "admin",
            "password": settings.seed_admin_password,
        },
        {
            "email": settings.seed_teknisi_email,
            "nama_lengkap": "Rizky Hidayat",
            "role": "teknisi",
            "password": settings.seed_teknisi_password,
        },
    ]
    now = utcnow()
    for spec in seed_specs:
        users().update_one(
            {"email": spec["email"]},
            {
                "$setOnInsert": {
                    "email": spec["email"],
                    "nama_lengkap": spec["nama_lengkap"],
                    "role": spec["role"],
                    "password_hash": hash_password(spec["password"]),
                    "active": True,
                    "created_at": now,
                    "last_login_at": None,
                }
            },
            upsert=True,
        )
    admin = users().find_one({"email": settings.seed_admin_email})
    teknisi = users().find_one({"email": settings.seed_teknisi_email})
    if not admin or not teknisi:
        raise RuntimeError("Gagal membuat akun seed")
    return admin, teknisi


def _insert_machines() -> dict[str, dict]:
    now = utcnow()
    result: dict[str, dict] = {}
    for spec in MACHINE_SPECS:
        doc = {
            "_id": ObjectId(),
            **spec,
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
        machines().insert_one(doc)
        result[spec["code"]] = doc
    return result


def _insert_thresholds(machine_map: dict[str, dict]) -> None:
    docs = []
    for code, sensor_specs in THRESHOLD_SPECS.items():
        for sensor, (warning, critical) in sensor_specs.items():
            meta = sensor_meta(sensor)
            docs.append(
                {
                    "machine_id": machine_map[code]["_id"],
                    "sensor": sensor,
                    "unit": meta["unit"],
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


def _insert_readings(
    rows: list[dict], machine_map: dict[str, dict]
) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    batch: list[dict] = []
    for row in rows:
        machine = machine_map[row["machine_code"]]
        doc = {
            "ts": row["ts"],
            "machine_id": machine["_id"],
            "machine_code": row["machine_code"],
            "temperature": row["temperature"],
            "vibration": row["vibration"],
            "power": row["power"],
            "sound": row["sound"],
            "quality": "good",
            "source": DATASET_SOURCE,
        }
        batch.append(doc)
        latest[row["machine_code"]] = doc
        if len(batch) >= 4000:
            readings().insert_many(batch, ordered=False)
            batch = []
    if batch:
        readings().insert_many(batch, ordered=False)
    return latest


def _peak_reading(machine_id: ObjectId, start: datetime, end: datetime, sensor: str) -> dict | None:
    docs = readings().find(
        {"machine_id": machine_id, "ts": {"$gte": start, "$lte": end}},
        {"_id": 0, sensor: 1, "ts": 1},
    )
    return max(docs, key=lambda item: item.get(sensor, float("-inf")), default=None)


def _alert_message(machine_code: str, sensor: str, level: str, value: float, threshold_value: float) -> str:
    meta = sensor_meta(sensor)
    label = "kritis" if level == "critical" else "peringatan"
    return (
        f"{meta['label']} {format_number(value)} {meta['unit']} pada {machine_code} "
        f"melampaui batas {label} ({format_number(threshold_value)} {meta['unit']})."
    )


def _create_alert(
    machine: dict,
    sensor: str,
    level: str,
    value: float,
    threshold_value: float,
    first_seen: datetime,
    last_seen: datetime,
    *,
    status: str = "open",
    acknowledged: dict | None = None,
    acknowledged_at: datetime | None = None,
    resolved_at: datetime | None = None,
    resolved_by: dict | None = None,
    resolution_note: str = "",
) -> dict:
    doc = {
        "machine_id": machine["_id"],
        "machine_code": machine["code"],
        "machine_name": machine["name"],
        "sensor": sensor,
        "level": level,
        "status": status,
        "value": value,
        "threshold_value": threshold_value,
        "unit": sensor_meta(sensor)["unit"],
        "message": _alert_message(machine["code"], sensor, level, value, threshold_value),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "consecutive_normal": 0,
        "acknowledged_by": acknowledged["_id"] if acknowledged else None,
        "acknowledged_by_name": acknowledged.get("nama_lengkap") if acknowledged else None,
        "acknowledged_at": acknowledged_at,
        "resolved_at": resolved_at,
        "resolved_by": resolved_by["_id"] if resolved_by else None,
        "resolved_by_name": resolved_by.get("nama_lengkap") if resolved_by else None,
        "resolution_note": resolution_note,
        "wo_id": None,
    }
    doc["_id"] = alerts().insert_one(doc).inserted_id
    return doc


def _finalize_wo(
    wo: dict,
    *,
    status: str,
    started_at: datetime | None = None,
    resolved_at: datetime | None = None,
    cancelled_at: datetime | None = None,
    downtime: int | None = None,
    resolution_notes: str = "",
    assigned: dict | None = None,
    activities: list[dict] | None = None,
) -> dict:
    updates: dict[str, Any] = {
        "status": status,
        "started_at": started_at,
        "resolved_at": resolved_at,
        "cancelled_at": cancelled_at,
        "downtime_minutes": downtime,
        "resolution_notes": resolution_notes,
        "assigned_to": assigned["_id"] if assigned else None,
        "assigned_name": assigned.get("nama_lengkap") if assigned else None,
        "activities": activities or [],
        "updated_at": resolved_at or cancelled_at or started_at or utcnow(),
    }
    work_orders().update_one({"_id": wo["_id"]}, {"$set": updates})
    return work_orders().find_one({"_id": wo["_id"]})


def _activity(ts: datetime, actor: str, action: str, status: str, note: str = "") -> dict:
    return {"ts": ts, "actor": actor, "action": action, "status": status, "note": note}


def _seed_work_orders(machine_map: dict[str, dict], admin: dict, teknisi: dict) -> dict[str, dict]:
    now = utcnow()
    result: dict[str, dict] = {}

    def make(
        key: str,
        code: str,
        title: str,
        description: str,
        *,
        created_at: datetime,
        due_at: datetime,
        priority: str,
        wo_type: str = "corrective",
        sensor: str | None = None,
        source: str = "manual",
        assigned: dict | None = None,
    ) -> dict:
        order = create_work_order(
            machine_map[code],
            title=title,
            description=description,
            priority=priority,
            wo_type=wo_type,
            assigned_user=assigned,
            due_at=due_at,
            sensor=sensor,
            source=source,
            created_at=created_at,
        )
        result[key] = order
        return order

    cnc_active = make(
        "cnc_active",
        "CNC-01",
        "Analisis getaran & penggantian bearing spindle",
        "Getaran spindle melewati batas kritis. Lakukan analisis spektrum, cek runout, dan siapkan bearing pengganti.",
        created_at=now - timedelta(hours=18),
        due_at=now + timedelta(hours=2),
        priority="critical",
        sensor="vibration",
        source="automatic",
        assigned=teknisi,
    )
    _finalize_wo(
        cnc_active,
        status="in_progress",
        started_at=now - timedelta(hours=6),
        assigned=teknisi,
        activities=[
            _activity(now - timedelta(hours=18), "Sistem", "created", "pending", "Dibuat otomatis oleh sistem CBM."),
            _activity(now - timedelta(hours=6), teknisi["nama_lengkap"], "started", "in_progress", "Diagnostik getaran dimulai."),
        ],
    )

    pmp_active = make(
        "pmp_active",
        "PMP-02",
        "Perbaikan kavitasi & alignment pompa coolant",
        "Getaran pompa di atas ambang kritis disertai kenaikan suhu. Periksa NPSH, seal, dan alignment kopling.",
        created_at=now - timedelta(hours=6),
        due_at=now + timedelta(hours=4),
        priority="critical",
        sensor="vibration",
        source="automatic",
    )
    _finalize_wo(
        pmp_active,
        status="pending",
        activities=[
            _activity(now - timedelta(hours=6), "Sistem", "created", "pending", "Dibuat otomatis oleh sistem CBM.")
        ],
    )

    cnv_pending = make(
        "cnv_preventive",
        "CNV-04",
        "Inspeksi belt, pulley, dan pelumasan conveyor",
        "Inspeksi preventif sesuai jadwal 500 jam operasi. Cek tension belt, kondisi pulley, dan pompa pelumasan otomatis.",
        created_at=now - timedelta(hours=20),
        due_at=now + timedelta(days=2),
        priority="medium",
        wo_type="preventive",
        source="manual",
        assigned=teknisi,
    )
    _finalize_wo(
        cnv_pending,
        status="pending",
        assigned=teknisi,
        activities=[
            _activity(now - timedelta(hours=20), "Administrator", "created", "pending", "Work order preventif dibuat."),
        ],
    )

    grd_cancel = make(
        "grd_cancelled",
        "GRD-05",
        "Kalibrasi ulang dressing unit",
        "Kalibrasi dressing unit dijadwalkan ulang setelah penggantian wheel.",
        created_at=now - timedelta(days=4),
        due_at=now - timedelta(days=2),
        priority="low",
        wo_type="inspection",
        source="manual",
    )
    _finalize_wo(
        grd_cancel,
        status="cancelled",
        cancelled_at=now - timedelta(days=3, hours=20),
        resolution_notes="Digabung dengan pekerjaan penggantian wheel pada WO terjadwal.",
        activities=[
            _activity(now - timedelta(days=4), "Administrator", "created", "pending", "Work order dibuat."),
            _activity(now - timedelta(days=3, hours=20), "Administrator", "cancelled", "cancelled", "Digabung dengan pekerjaan penggantian wheel."),
        ],
    )

    resolved_specs = [
        (
            "cmp_resolved",
            "CMP-03",
            "Pembersihan cooler & penggantian filter kompresor",
            "Suhu buang kompresor meningkat. Bersihkan heat exchanger, ganti filter udara, dan verifikasi thermostatic valve.",
            -timedelta(days=5, hours=3),
            80,
            "Cooler dibersihkan, filter diganti, suhu turun ke 82 °C. Monitoring 2 jam stabil.",
            "temperature",
            "high",
        ),
        (
            "cnv_resolved",
            "CNV-04",
            "Perbaikan bearing pulley conveyor",
            "Getaran pulley melebihi batas. Ganti bearing 6205, bersihkan rumah bearing, dan set ulang tension belt.",
            -timedelta(days=8, hours=4),
            90,
            "Bearing pulley diganti dan alignment belt diperbaiki. Getaran kembali 2,9 mm/s.",
            "vibration",
            "high",
        ),
        (
            "grd_resolved",
            "GRD-05",
            "Inspeksi overload motor grinding",
            "Daya motor meningkat saat siklus dressing. Periksa arus fase, kondisi wheel, dan parameter pemakanan.",
            -timedelta(days=10, hours=2),
            45,
            "Parameter depth of cut dikoreksi dan arus motor kembali normal.",
            "power",
            "medium",
        ),
        (
            "pmp_resolved",
            "PMP-02",
            "Re-alignment pompa setelah pekerjaan pipa",
            "Getaran pompa naik setelah penyambungan pipa. Lakukan re-alignment kopling dan cek soft foot.",
            -timedelta(days=12, hours=1),
            70,
            "Alignment kopling dikoreksi; offset <0,05 mm. Getaran turun ke 3,4 mm/s.",
            "vibration",
            "medium",
        ),
    ]
    for key, code, title, description, offset, downtime, notes, sensor, priority in resolved_specs:
        created = now + offset
        late = key == "cnv_resolved"
        order = make(
            key,
            code,
            title,
            description,
            created_at=created,
            due_at=created + timedelta(hours=8),
            priority=priority,
            sensor=sensor,
            source="automatic",
            assigned=teknisi,
        )
        started = created + timedelta(hours=2)
        resolved = created + timedelta(hours=(9 if late else 7))
        _finalize_wo(
            order,
            status="resolved",
            started_at=started,
            resolved_at=resolved,
            downtime=downtime,
            resolution_notes=notes,
            assigned=teknisi,
            activities=[
                _activity(created, "Sistem", "created", "pending", "Dibuat otomatis oleh sistem CBM."),
                _activity(started, teknisi["nama_lengkap"], "started", "in_progress", "Pekerjaan dimulai."),
                _activity(resolved, teknisi["nama_lengkap"], "resolved", "resolved", notes),
            ],
        )

    cnc_prev = make(
        "cnc_preventive",
        "CNC-01",
        "Pelumasan rel dan pengecekan way cover",
        "Pelumasan preventif rel X/Y/Z dan inspeksi way cover.",
        created_at=now - timedelta(days=3, hours=4),
        due_at=now - timedelta(days=2, hours=20),
        priority="low",
        wo_type="preventive",
        source="manual",
        assigned=teknisi,
    )
    _finalize_wo(
        cnc_prev,
        status="resolved",
        started_at=now - timedelta(days=3, hours=3),
        resolved_at=now - timedelta(days=3, hours=2, minutes=30),
        downtime=0,
        resolution_notes="Pelumasan selesai; tidak ada kebocoran way cover.",
        assigned=teknisi,
        activities=[
            _activity(now - timedelta(days=3, hours=4), "Administrator", "created", "pending", "Work order preventif dibuat."),
            _activity(now - timedelta(days=3, hours=3), teknisi["nama_lengkap"], "started", "in_progress", "Pekerjaan dimulai."),
            _activity(now - timedelta(days=3, hours=2, minutes=30), teknisi["nama_lengkap"], "resolved", "resolved", "Pelumasan selesai."),
        ],
    )

    cmp_prev = make(
        "cmp_preventive",
        "CMP-03",
        "Penggantian filter separator dan oli kompresor",
        "Perawatan preventif 4.000 jam: ganti filter separator, oli, dan inspeksi drain valve.",
        created_at=now - timedelta(days=6, hours=6),
        due_at=now - timedelta(days=5, hours=20),
        priority="medium",
        wo_type="preventive",
        source="manual",
        assigned=teknisi,
    )
    _finalize_wo(
        cmp_prev,
        status="resolved",
        started_at=now - timedelta(days=6, hours=5),
        resolved_at=now - timedelta(days=6, hours=3, minutes=40),
        downtime=0,
        resolution_notes="Filter dan oli diganti; drain valve dibersihkan.",
        assigned=teknisi,
        activities=[
            _activity(now - timedelta(days=6, hours=6), "Administrator", "created", "pending", "Work order preventif dibuat."),
            _activity(now - timedelta(days=6, hours=5), teknisi["nama_lengkap"], "started", "in_progress", "Pekerjaan dimulai."),
            _activity(now - timedelta(days=6, hours=3, minutes=40), teknisi["nama_lengkap"], "resolved", "resolved", "Perawatan preventif selesai."),
        ],
    )
    return result


def _seed_alerts_and_links(
    machine_map: dict[str, dict],
    latest: dict[str, dict],
    work_order_map: dict[str, dict],
    teknisi: dict,
) -> None:
    now = utcnow()
    active_specs = [
        ("CNC-01", "vibration", "critical", now - timedelta(hours=18), True, "cnc_active"),
        ("CNC-01", "temperature", "warning", now - timedelta(hours=12), False, None),
        ("CNC-01", "sound", "warning", now - timedelta(hours=10), False, None),
        ("PMP-02", "vibration", "critical", now - timedelta(hours=6), False, "pmp_active"),
        ("PMP-02", "temperature", "warning", now - timedelta(hours=5), True, None),
        ("PMP-02", "sound", "warning", now - timedelta(hours=4), False, None),
    ]
    latest_ts = next(iter(latest.values()))["ts"]
    for code, sensor, level, first_seen, ack, wo_key in active_specs:
        machine = machine_map[code]
        value = latest[code].get(sensor)
        if value is None:
            continue
        threshold = THRESHOLD_SPECS[code][sensor][1 if level == "critical" else 0]
        acknowledged = teknisi if ack else None
        ack_at = now - timedelta(hours=4) if ack else None
        alert = _create_alert(
            machine,
            sensor,
            level,
            float(value),
            threshold,
            first_seen,
            now,
            status="acknowledged" if ack else "open",
            acknowledged=acknowledged,
            acknowledged_at=ack_at,
        )
        if wo_key and wo_key in work_order_map:
            alerts().update_one({"_id": alert["_id"]}, {"$set": {"wo_id": work_order_map[wo_key]["_id"]}})

    resolved_specs = [
        ("CMP-03", "temperature", -timedelta(days=5, hours=3), 9, "cmp_resolved"),
        ("CNV-04", "vibration", -timedelta(days=8, hours=4), 5, "cnv_resolved"),
        ("GRD-05", "power", -timedelta(days=10, hours=2), 4, "grd_resolved"),
        ("PMP-02", "vibration", -timedelta(days=12, hours=1), 6, "pmp_resolved"),
    ]
    for code, sensor, offset, duration_hours, wo_key in resolved_specs:
        machine = machine_map[code]
        start = now + offset
        end = start + timedelta(hours=duration_hours)
        doc = _peak_reading(machine["_id"], start, end, sensor) or latest[code]
        value = float(doc.get(sensor))
        threshold = THRESHOLD_SPECS[code][sensor][0]
        alert = _create_alert(
            machine,
            sensor,
            "warning",
            value,
            threshold,
            start,
            end,
            status="resolved",
            acknowledged=teknisi,
            acknowledged_at=start + timedelta(minutes=20),
            resolved_at=end + timedelta(minutes=30),
            resolved_by=teknisi,
            resolution_note="Kondisi kembali normal setelah tindakan perawatan.",
        )
        order = work_order_map.get(wo_key)
        if order:
            alerts().update_one({"_id": alert["_id"]}, {"$set": {"wo_id": order["_id"]}})
            work_orders().update_one({"_id": order["_id"]}, {"$set": {"alert_id": alert["_id"]}})


def _seed_audit(admin: dict, teknisi: dict) -> None:
    now = utcnow()
    rows = [
        (now - timedelta(minutes=45), admin, f"Memuat dataset sintetis {DATASET_DAYS} hari", "system", None, f"{len(rows):,} pembacaan sensor dimuat."),
        (now - timedelta(hours=6), None, "Work order otomatis", "work_order", None, "PMP-02 · getaran kritis membuat work order korektif."),
        (now - timedelta(hours=6), teknisi, "Memulai work order", "work_order", None, "Diagnostik getaran CNC-01 dimulai."),
        (now - timedelta(hours=18), None, "Work order otomatis", "work_order", None, "CNC-01 · getaran kritis membuat work order korektif."),
        (now - timedelta(days=3, hours=20), admin, "Membatalkan work order", "work_order", None, "Kalibrasi dressing GRD-05 digabung dengan pekerjaan wheel."),
    ]
    for ts, actor, action, entity, entity_id, detail in rows:
        audit_logs().insert_one(
            {
                "ts": ts,
                "actor_id": actor["_id"] if actor else None,
                "actor_name": actor["nama_lengkap"] if actor else "Sistem",
                "actor_role": actor["role"] if actor else "system",
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "detail": detail,
                "ip": "127.0.0.1",
            }
        )


def _reset_collections() -> None:
    get_db_collections = [
        users(),
        machines(),
        thresholds(),
        readings(),
        alerts(),
        work_orders(),
        audit_logs(),
        counters(),
        simulation_controls(),
        simulation_runs(),
    ]
    for collection in get_db_collections:
        collection.drop()
    from app.database import login_attempts

    login_attempts().delete_many({})


def seed_all(reset: bool = False) -> dict[str, Any]:
    if reset:
        _reset_collections()
    create_indexes()
    ensure_timeseries_collection()
    admin, teknisi = _insert_users()
    if machines().count_documents({}) > 0:
        return {
            "seeded": False,
            "reason": "Data mesin sudah tersedia",
            "machines": machines().count_documents({}),
            "readings": readings().count_documents({}),
        }
    now = utcnow()
    rows, latest_rows, scenarios = generate_series(now)
    _write_dataset(rows, scenarios)
    machine_map = _insert_machines()
    _insert_thresholds(machine_map)
    latest = _insert_readings(rows, machine_map)
    work_order_map = _seed_work_orders(machine_map, admin, teknisi)
    _seed_alerts_and_links(machine_map, latest, work_order_map, teknisi)
    for code, machine in machine_map.items():
        threshold_docs = list(thresholds().find({"machine_id": machine["_id"]}))
        evaluate_reading(latest[code], machine, threshold_docs, ts=latest[code]["ts"])
    _seed_audit(admin, teknisi)
    summary = {
        "seeded": True,
        "machines": machines().count_documents({}),
        "readings": readings().count_documents({}),
        "alerts": alerts().count_documents({}),
        "work_orders": work_orders().count_documents({}),
        "rows_csv": len(rows),
        "first": rows[0]["ts"],
        "last": rows[-1]["ts"],
        "dataset": str(settings.dataset_readings_csv),
    }
    return summary
