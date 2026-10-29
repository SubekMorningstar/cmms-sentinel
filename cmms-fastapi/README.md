# CMMS Sentinel

CMMS (Computerized Maintenance Management System) berbasis web dengan **Condition-Based Monitoring** untuk aset manufaktur. Empat kanal sensor IoT — **suhu, getaran, daya, dan suara** — dipantau terhadap ambang batas, menghasilkan alert otomatis, dan membuat work order korektif saat kondisi kritis.

Aplikasi dibangun dengan **FastAPI + MongoDB time-series + Jinja2**, menggunakan shell visual siQtheme yang dikembangkan menjadi antarmuka operasional bertema glass putih-biru.

## Fitur utama

- **Pusat operasi** — ringkasan armada, mesin online, alert kritis, work order aktif, tren sensor, dan aktivitas terbaru.
- **Condition monitoring** — tren 1/6/24/168 jam per mesin dan per sensor, nilai terbaru, status ambang batas, serta tabel pembacaan terakhir.
- **Threshold sensor** — batas warning/kritis, histeresis, jumlah pembacaan normal untuk pemulihan otomatis, dan aktif/nonaktif per sensor.
- **Alert lifecycle** — aktif → diketahui → selesai, eskalasi warning ke critical, deduplikasi per mesin+sensor, dan pemulihan otomatis setelah N pembacaan normal.
- **Work order** — pembuatan manual maupun otomatis dari alert kritis, penugasan teknisi, alur status (menunggu → dikerjakan → menunggu tinjauan → selesai/dikembalikan), catatan aktivitas, dan pencatatan downtime.
- **Alur kerja lapangan** — checklist yang dapat ditandai, catatan, waktu mulai/kirim/selesai, pemakaian suku cadang, hasil pemeriksaan, serta persetujuan atau pengembalian pekerjaan oleh admin.
- **Penjadwalan tim** — antrean berdasarkan tenggat, beban aktif tiap teknisi, keterlambatan, dan penugasan manual; kapasitas demo menggunakan target antrean lima WO aktif per teknisi.
- **Pemeliharaan preventif** — rencana berbasis kalender dan interval hari yang otomatis membuat work order ber-checklist hanya untuk aset virtual tanpa telemetry gateway.
- **Persediaan** — stok minimum, penyesuaian stok oleh admin, dan pencatatan pemakaian dari work order yang sedang dikerjakan.
- **Notifikasi dalam aplikasi** — penugasan, work order mendekati tenggat, dan alert kritis; pengguna dapat menandai notifikasi telah dibaca.
- **Aset & mesin** — CRUD aset, arsip/pulihkan, threshold awal otomatis, dan riwayat alert/work order per mesin.
- **Laporan & analitik** — periode 7/14/30/90 hari, availability, MTTR, MTBF, SLA compliance, downtime, backlog, tren work order, skor kesehatan mesin, dan ekspor CSV empat dataset.
- **Pengguna & RBAC** — peran `admin` dan `teknisi`, aktivasi akun, audit trail seluruh aksi penting, dan profil pengguna.
- **Integrasi IoT** — API ingest ber-API key untuk gateway, endpoint baca mesin/alert/work order, halaman integrasi, serta unduhan dataset.
- **Telemetry demo** — simulator data 5 menit untuk pengembangan tanpa gateway fisik; otomatis berhenti bila telemetry gateway nyata sudah masuk.
- **Laboratorium simulasi** — kendali mesin virtual, skenario gangguan berlabel, evaluasi precision/recall/specificity, serta eksperimen ber-seed yang dapat diulang. Tidak mengendalikan mesin dengan telemetry gateway.
- **Perbandingan eksperimen** — pilih hingga empat run dengan seed, skenario, rentang data, keparahan, metrik deteksi, latensi, dan alarm keliru berdampingan.
- **Beranda berbasis peran** — admin melihat antrean tinjauan, beban teknisi, keterlambatan, dan status armada; teknisi melihat tugasnya, tenggat, dan hasil yang menunggu tinjauan.

## Halaman

| Halaman | Path | Akses |
|---|---|---|
| Login | `/login` | Publik |
| Pusat Operasi | `/dashboard` | Semua pengguna |
| Condition Monitoring | `/cbm-monitoring` | Semua pengguna |
| Pusat Peringatan | `/alerts` | Semua pengguna |
| Work Order | `/work-orders` | Semua pengguna |
| Penjadwalan Teknisi | `/schedule` | Admin |
| Pemeliharaan Preventif | `/maintenance` | Admin |
| Persediaan Suku Cadang | `/inventory` | Semua pengguna (ubah stok: admin) |
| Notifikasi | `/notifications` | Semua pengguna |
| Laporan & Analitik | `/reports` | Semua pengguna |
| Aset & Mesin | `/assets` | Semua pengguna (ubah: admin) |
| Threshold Sensor | `/thresholds` | Semua pengguna (ubah: admin) |
| Pengguna | `/users` | Admin |
| Audit Trail | `/admin/audit` | Admin |
| Integrasi & Dataset | `/integration` | Admin |
| Laboratorium Simulasi | `/simulation` | Admin |
| Profil Saya | `/profile` | Semua pengguna |

## Teknologi

- Python 3.12+ (diuji pada 3.14), FastAPI 0.162, Starlette, Uvicorn
- MongoDB 7+ (diuji pada 9.0.4) dengan koleksi time-series `readings`
- PyMongo 4.19, Pydantic 2, Jinja2 3, bcrypt cost 12
- Bootstrap 4/JQuery dari siQtheme + CSS/JS aplikasi kustom
- Tema glass putih-biru sebagai satu-satunya tampilan; grafik ApexCharts beranimasi halus dan seluruh motion menghormati `prefers-reduced-motion`

## Persiapan

Prasyarat: Python 3.12+, MongoDB yang berjalan lokal (atau URI MongoDB lain), dan `pip`.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Salin konfigurasi lalu isi rahasia:

```bash
copy .env.example .env        # Windows
cp .env.example .env          # Linux/macOS
```

Wajib diisi sebelum aplikasi dapat berjalan:

- `APP_SECRET_KEY` — kunci penandatanganan sesi.
- `INGEST_API_KEY` — kunci header `X-API-Key` untuk gateway.

Buat nilai acak, misalnya:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Menjalankan

```bash
# Opsional: perluas riwayat sintetis secara aman tanpa menghapus data yang ada.
python seed.py --extend-history

# Reset destruktif: muat ulang seluruh dataset 90 hari.
python seed.py --reset --yes

python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Buka `http://127.0.0.1:8001/login`.

Health check: `GET http://127.0.0.1:8001/health`.

### Akun demo

Nilai awal mengikuti `.env`. **Ganti sebelum dipakai di lingkungan nyata.**

| Peran | Email | Password |
|---|---|---|
| Administrator | `admin@cmms.test` | `Admin#2026!` |
| Teknisi | `teknisi@cmms.test` | `Teknisi#2026!` |

Set `SHOW_DEMO_CREDENTIALS=true` bila ingin menampilkan petunjuk akun demo pada halaman login. Jangan aktifkan di produksi.

## Konfigurasi lingkungan

| Variabel | Default | Keterangan |
|---|---|---|
| `APP_ENV` | `development` | `production` menonaktifkan simulator secara default |
| `APP_DEBUG` | `false` | Jangan aktifkan di produksi |
| `APP_SECRET_KEY` | — | Wajib; kunci sesi |
| `SESSION_HTTPS_ONLY` | `false` | Set `true` di belakang HTTPS |
| `MONGODB_URI` | `mongodb://127.0.0.1:27017` | URI MongoDB |
| `MONGODB_DB` | `cmms_ops` | Nama database |
| `INGEST_API_KEY` | — | Wajib; kunci gateway IoT |
| `AUTO_SEED` | `true` | Isi database kosong dengan dataset awal |
| `DEMO_TELEMETRY` | `true` di development | Simulator pembacaan 5 menit |
| `SHOW_DEMO_CREDENTIALS` | `false` | Tampilkan akun demo di login |
| `SEED_*` | akun demo | Akun awal saat seeding |
| `APP_TIMEZONE` | `Asia/Jakarta` | Zona tampilan |

## Dataset

`data/sensor_readings.csv` berisi **129.605 pembacaan** untuk 5 mesin (CNC-01, PMP-02, CMP-03, CNV-04, GRD-05) dengan interval 5 menit selama 90 hari. Data bersifat sintetis dan deterministik, dikalibrasi terhadap referensi publik:

- **ISO 10816-3** — klasifikasi keparahan getaran mesin industri.
- **IEC 60034-1** — batas kenaikan suhu mesin listrik.
- **OSHA 1910.95** — paparan kebisingan area kerja.
- Pola degradasi bearing, kavitasi pompa, dan overload motor dari literatur condition monitoring (termasuk karakteristik sinyal CWRU Bearing Data Center).

`data/fault_scenarios.csv` menyimpan ground-truth skenario gangguan untuk evaluasi, tetapi **tidak** dimuat ke koleksi sensor agar pipeline deteksi tetap realistis. Detail dan checksum ada di [data/DATASET.md](data/DATASET.md).

Perluas riwayat yang sudah ada tanpa reset (aman dijalankan berulang kali):

```bash
python seed.py --extend-history
```

Perintah ini hanya menambahkan data yang lebih lama, melewati mesin yang telah memiliki telemetry dari gateway langsung, dan tidak menghapus atau menimpa pembacaan tersimpan. Untuk membangun ulang database sepenuhnya:

```bash
python seed.py --reset --yes
```

## Logika CBM dan work order

1. Setiap pembacaan dievaluasi terhadap threshold aktif per mesin dan sensor.
2. Nilai di atas `warning` membuat alert warning; di atas `critical` membuat alert kritis.
3. Alert kritis tanpa work order terbuka otomatis membuat **work order korektif prioritas critical** (deduplikasi per mesin+sensor).
4. Nilai yang kembali normal mengurangi alert setelah `normal_reset_readings` pembacaan berturut-turut, dengan histeresis untuk mencegah flapping.
5. Alert dapat diketahui, diselesaikan manual dengan catatan, atau ditindaklanjuti menjadi work order dari halaman detail.

## Skor anomali berbasis riwayat

Dashboard dan detail aset menghitung skor anomali 0–100 per mesin dari hingga 90 hari telemetry terakhir (maksimal 25.921 sampel per mesin pada interval 5 menit). Untuk tiap sensor, baseline memakai median dan MAD (median absolute deviation) dari sampel yang masih berada di ambang normal mesin tersebut; bila tersedia minimal 48 sampel, pembanding dipilih dari jam operasi serupa (±90 menit) untuk mengurangi bias siklus harian. Model membandingkan baseline dengan median hingga tiga pembacaan dalam 30 menit terakhir, lalu menggabungkan sinyal sensor terkuat (60%) dengan rerata berbobot sensor (40%). Ambang warning/kritis tetap menjadi batas minimum risiko; skor ini melengkapi, bukan menggantikan, aturan alert dan skor kesehatan lama.

Skor adalah tingkat penyimpangan pola, **bukan probabilitas kerusakan atau diagnosis**. Riwayat sehat kurang dari 48 sampel per sensor tidak dilatih; layar menampilkan status belum cukup riwayat alih-alih membuat skor. Jumlah sampel dan sensor pemicu ditampilkan agar hasil dapat ditinjau teknisi.

## Laboratorium simulasi virtual

Administrator dapat membuka `/simulation` untuk menjeda atau menjalankan simulator per mesin virtual dan menerapkan kondisi normal, degradasi bearing, gangguan pendinginan, beban motor berlebih, suara mekanis abnormal, atau sensor terputus. Kontrol mencatat waktu mulai, durasi, sensor terdampak, tingkat keparahan, dan seed; skenario aktif berakhir otomatis sesuai durasi. Eksperimen memberi label ground-truth pada pembacaan sintetis dan menampilkannya sebagai **skor penyimpangan pada data simulasi**, bukan prediksi kerusakan nyata.

Eksperimen dapat memilih mesin, skenario, tingkat keparahan, seed, serta rentang waktu 30/60/120 menit pada interval lima menit. Nilai sensor gangguan meningkat bertahap pada paruh akhir; skenario normal memberi label seluruh rentang normal untuk menghitung precision/recall/specificity dan episode alarm palsu per jam. Hasil mencatat waktu deteksi dari skor penyimpangan ≥25; skenario sensor terputus menggunakan alarm kualitas data dan menampilkan metode deteksi secara terpisah.

Seed, rentang waktu, dan snapshot baseline disimpan bersama konfigurasi eksperimen. Tombol **Ulangi** memakai rentang, seed, skenario, tingkat keparahan, dan baseline yang sama agar pola sensor dapat direproduksi; pembacaan eksperimen berlabel dikecualikan dari baseline model. Alert simulasi dapat dilanjutkan ke work order, ditugaskan kepada teknisi, dimulai, lalu diselesaikan melalui alur yang sama dengan pekerjaan lainnya. Mesin yang memiliki telemetry `iot`, `gateway`, `edge`, atau `api` tidak dapat dikendalikan atau dipilih untuk eksperimen sintetis. Dashboard, kartu mesin, alert, grafik, laporan, dan ekspor menampilkan sumber serta rentang data; data sintetis ditandai **Data simulasi**. Hasil laboratorium bukan akurasi lapangan, probabilitas kerusakan, diagnosis, atau kendali mesin fisik.

## API IoT

Semua endpoint baca menerima header `X-API-Key` **atau** sesi web yang sudah login. Ingest hanya menerima API key.

| Metode | Endpoint | Keterangan |
|---|---|---|
| `POST` | `/api/ingest` | Kirim 1–500 pembacaan untuk satu mesin |
| `GET` | `/api/machines` | Snapshot seluruh armada |
| `GET` | `/api/machines/{code}/latest?hours=24` | Seri waktu, alert, dan work order mesin |
| `GET` | `/api/alerts?status=active&limit=50` | Daftar alert |
| `GET` | `/api/work-orders?status=active&limit=50` | Daftar work order |

Contoh ingest:

```bash
curl -X POST http://127.0.0.1:8001/api/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CMMS_API_KEY" \
  -d '{
    "machine_code": "CNC-01",
    "readings": [
      {"temperature": 68.4, "vibration": 2.1, "power": 14.8, "sound": 74.2}
    ]
  }'
```

Nilai tervalidasi Pydantic (rentang fisik, field tak dikenal ditolak, minimal satu sensor). Timestamp opsional, tidak boleh lebih dari 5 menit ke masa depan atau lebih lama dari 366 hari. Respons memuat alert yang dibuat/diperbarui/diselesaikan serta work order otomatis.

Kunci API di halaman Integrasi selalu ditampilkan dalam bentuk tersamarkan.

## Telemetry demo

Saat `DEMO_TELEMETRY=true`, simulator menulis pembacaan sintetis tiap 5 menit (backfill 24 jam, tick 60 detik) berdasarkan pembacaan terakhir mesin aktif, lalu mengevaluasi threshold. Simulator **tidak berjalan** bila sudah ada pembacaan dari sumber gateway nyata (`iot`, `gateway`, `edge`, `api`) pada database. Di produksi, set `APP_ENV=production` atau `DEMO_TELEMETRY=false`.

## Keamanan

- Password bcrypt cost 12; kebijakan minimal 10 karakter, huruf dan angka.
- Sesi HttpOnly, `SameSite=Lax`, masa berlaku 8 jam, dan opsi `Secure` di belakang HTTPS.
- Token CSRF per sesi untuk seluruh form POST.
- Pembatasan login: 6 kegagalan per 10 menit per host+email.
- RBAC server-side (`require_user`, `require_admin`) untuk setiap halaman dan aksi.
- CSP berbasis nonce, `X-Frame-Options: DENY`, `nosniff`, referrer policy, dan `no-store` untuk HTML.
- Audit trail untuk login, perubahan data, ekspor, dan aksi sistem.
- Ekspor CSV dilindungi dari formula injection; input dibatasi dan divalidasi; API key hanya dibandingkan secara constant-time.
- Dokumentasi OpenAPI/Redoc dinonaktifkan pada aplikasi ini.

## Pengujian

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Suite end-to-end memakai database terpisah `cmms_ops_test`, membuat fixture sendiri, dan menolak berjalan bila nama database tidak berakhiran `_test`. Database uji dibersihkan otomatis setelah selesai; database operasional tidak disentuh.

Cakupan: health, login/CSRF/throttling, RBAC, CRUD aset, arsip/pulihkan, threshold, siklus work order, siklus alert + work order otomatis, pengguna, profil, ekspor CSV (termasuk proteksi injeksi), dan validasi API ingest.

## Struktur proyek

```text
app/
  main.py            # aplikasi FastAPI, middleware keamanan, lifespan
  config.py          # konfigurasi .env
  database.py        # koneksi & indeks MongoDB
  security.py        # sesi, CSRF, RBAC, hashing, throttling
  web.py             # render Jinja2 & konteks shell
  utils.py           # label, format, helper waktu
  routers/           # auth, dashboard, monitoring, assets, thresholds,
                     # work_orders, alerts, reports, users, admin, api
  services/          # dataset, analytics, threshold engine, work order, audit, telemetry
  templates/         # halaman siQtheme yang dikembangkan
  static/            # CSS/JS aplikasi + vendor template
data/                # sensor_readings.csv, fault_scenarios.csv, DATASET.md
tests/               # conftest.py, test_smoke.py
seed.py              # pemuat dataset
```

## Catatan produksi

- Set `APP_ENV=production`, `APP_DEBUG=false`, `DEMO_TELEMETRY=false`, `SHOW_DEMO_CREDENTIALS=false`.
- Ganti `APP_SECRET_KEY`, `INGEST_API_KEY`, dan seluruh password akun demo.
- Jalankan di belakang reverse proxy TLS, set `SESSION_HTTPS_ONLY=true`, dan batasi akses MongoDB (autentikasi + bind lokal/firewall).
- Gunakan proses manager (systemd/container) dan backup MongoDB terjadwal.
- Simulator bukan pengganti gateway; untuk operasi nyata, hubungkan gateway ke `/api/ingest` dengan rotasi API key berkala.
