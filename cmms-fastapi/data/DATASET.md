# Dataset Sensor CMMS Sentinel

Dataset ini disertakan agar aplikasi CMMS/CBM dapat langsung dioperasikan tanpa menunggu gateway fisik.
Data bersifat sintetis dan direkayasa untuk meniru pola operasi mesin industri, bukan rekaman rahasia pabrik.

## Ringkasan

- **Periode:** 28 Jul 2026 15:05 s.d. 26 Oct 2026 15:05 WIB
- **Interval:** 5 menit
- **Mesin:** 5 aset industri
- **Kanal sensor:** suhu (°C), getaran RMS (mm/s), daya (kW), suara (dB(A))
- **Jumlah baris:** 129,605
- **Format waktu:** ISO 8601 UTC (`Z`)
- **SHA-256:** `cd3f8a4f9fd5298ae7302f08724e3ffc7d9ecfbaa725f63ff7bc0d0099ccb27b`
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

Eksperimen tambahan dapat dibuat melalui halaman administrator **Laboratorium Simulasi** (`/simulation`).
Pembacaan eksperimen memiliki label `source=simulator`, `simulation_run_id`, `scenario_id`, `fault_label`,
dan `fault_sensor`; data tersebut tidak mengubah CSV dataset dasar. Evaluasi model menggunakan label skenario
sebagai ground-truth dan harus ditafsirkan sebagai pengujian sintetis, bukan hasil validasi lapangan.
