# Deploy ke Render

Panduan ini menjelaskan cara menjalankan aplikasi di [Render](https://render.com) memakai **Docker**, **Gunicorn**, **persistent disk**, dan **SQLite** (default). PostgreSQL opsional.

---

## 1. File yang dipakai

| File | Fungsi |
|---|---|
| `Dockerfile` | Image produksi: Python 3.12, OpenCV headless, Gunicorn |
| `gunicorn.conf.py` | Jumlah worker/thread, port, timeout |
| `requirements-prod.txt` | Dependency produksi (tanpa paket GUI OpenCV) |
| `render.yaml` | Blueprint Render: service, disk, env var, health check |
| `Procfile` | Alternatif start command jika tidak memakai Docker |
| `.dockerignore` | Agar data lokal tidak ikut ke dalam image |
| `.gitignore` | Agar database, upload, dan `.env` tidak ikut ke Git |
| `.env.example` | Contoh environment variable |

---

## 2. Sebelum deploy

1. Pastikan project sudah di-push ke **GitHub / GitLab / Bitbucket**.
2. Jangan commit `instance/`, `uploads/`, `hasil/`, atau `.env`. File-file itu sudah dikecualikan oleh `.gitignore`.
3. Siapkan akun Render dan metode pembayaran. **Persistent disk hanya tersedia di instance berbayar** (blueprint memakai `plan: starter`).

```bash
git add .
git commit -m "Siapkan deploy Render"
git push
```

> Cek dulu dengan `git status` bahwa `instance/` dan `uploads/` tidak ikut ter-stage.

---

## 3. Deploy lewat Blueprint (disarankan)

1. Buka **Render Dashboard → New → Blueprint**.
2. Hubungkan repository aplikasi.
3. Render akan membaca `render.yaml`. Periksa nama service `pilgan-checker`, region `singapore`, dan disk `pilgan-data`.
4. Saat diminta, isi **`APP_PASSWORD`** dengan password kuat. Nilai ini tidak disimpan di repo (`sync: false`).
5. Klik **Apply / Create**.
6. Tunggu build Docker selesai dan health check `/healthz` lulus.
7. Buka URL `https://<nama-service>.onrender.com`, lalu login dengan:
   - Username: `admin`
   - Password: yang kamu isi pada langkah 4

Setiap push ke branch utama akan otomatis deploy ulang (`autoDeploy: true`).

---

## 4. Environment variable

| Variable | Wajib | Default | Keterangan |
|---|---|---|---|
| `SECRET_KEY` | Ya (produksi) | dibuat otomatis oleh Render | Kunci session Flask. Ganti = semua session lama tidak berlaku |
| `PILGAN_DATA_DIR` | Ya di Render | folder project | Di blueprint: `/var/data` (lokasi persistent disk) |
| `APP_USERNAME` | Tidak | `admin` (dari blueprint) | Basic auth aktif jika username **dan** password diisi |
| `APP_PASSWORD` | Tidak | kosong | Isi saat membuat Blueprint. Jangan taruh di repo |
| `DATABASE_URL` | Tidak | SQLite di `PILGAN_DATA_DIR` | Isi jika memakai PostgreSQL |
| `WEB_CONCURRENCY` | Tidak | `1` | Jumlah worker Gunicorn |
| `WEB_THREADS` | Tidak | `4` | Thread per worker |
| `GUNICORN_TIMEOUT` | Tidak | `300` | Detik; scan batch besar butuh waktu |
| `PORT` | Otomatis | diisi Render | Jangan diubah manual |

**Catatan keamanan:** jika `APP_PASSWORD` kosong, aplikasi berjalan **tanpa login**. Jangan biarkan kondisi ini di URL publik.

---

## 5. Persistent disk & paket gratis

Blueprint memasang disk 1 GB di `/var/data`:

```text
/var/data/instance/pilgan.db   -> database SQLite
/var/data/uploads/             -> foto templat, scan, gambar debug
```

Hal penting:

- **Paket gratis Render tidak mendukung persistent disk.** File akan hilang saat service restart, redeploy, atau spin-down. Jangan pakai paket gratis untuk data sungguhan.
- Satu disk hanya bisa dipasang ke **satu service**. Jangan menaikkan jumlah instance; disk tidak bisa dipakai bersama.
- Isi disk **tidak di-backup otomatis** oleh Render. Lakukan backup berkala (lihat bagian 9).
- Jika kapasitas 1 GB terasa sempit, perbesar `sizeGB` di `render.yaml` atau hapus scan lama lewat aplikasi.
- Upgrade paket RAM jika sering kehabisan memori saat scan banyak lembar. Paket Starter (512 MB) cukup untuk pemakaian kecil, tetapi OpenCV bisa berat.

---

## 6. Database

### Opsi A — SQLite (default, paling sederhana)

Tidak perlu setup apa pun. Aplikasi otomatis membuat `pilgan.db` di persistent disk saat pertama start.

Cocok untuk:

- satu sekolah / beberapa guru,
- ratusan sampai beberapa ribu lembar,
- satu instance aplikasi.

Keterbatasan: penulisan bersamaan terbatas. Karena itu Gunicorn diset `WEB_CONCURRENCY=1` dan memakai thread, bukan banyak proses.

### Opsi B — PostgreSQL

Gunakan jika pemakaian bersamaan tinggi atau butuh skalabilitas.

1. Di Render: **New → PostgreSQL** (pilih paket berbayar untuk data jangka panjang; paket gratis punya masa berlaku terbatas).
2. Setelah database siap, salin **Internal Database URL**.
3. Buka service web → **Environment** → tambahkan:
   ```env
   DATABASE_URL=postgresql://user:password@host:5432/database
   ```
4. Simpan, lalu redeploy/restart service.
5. Tabel dibuat otomatis saat aplikasi start (`db.create_all()`).

Catatan:

- URL `postgres://...` otomatis dinormalisasi menjadi `postgresql://...`.
- `psycopg2-binary` sudah ada di `requirements-prod.txt`.
- **Data SQLite tidak ikut pindah otomatis.** Buat ulang templat/kunci lewat UI, atau minta skrip migrasi khusus.
- Persistent disk tetap diperlukan untuk folder `uploads/`.

---

## 7. Basic auth

Aktif otomatis jika `APP_USERNAME` dan `APP_PASSWORD` sama-sama tidak kosong.

- Semua halaman dan file statis dilindungi.
- `/healthz` **dikecualikan** agar health check Render tetap jalan.
- Render menyediakan HTTPS, jadi password tidak dikirim dalam koneksi terbuka.
- Untuk menonaktifkan: kosongkan salah satu variable, lalu redeploy.
- Untuk mengganti password: ubah `APP_PASSWORD` di dashboard, lalu restart/redeploy.

---

## 8. Migrasi data dari lokal (opsional)

Data lokal **tidak** ikut ke Render karena dikecualikan dari Git dan Docker. Pilihan:

### Cara aman — buat ulang lewat UI

Buat templat, isi paket kunci, lalu scan ulang di aplikasi Render. Paling sederhana dan menghindari konflik file.

### Cara cepat — salin database + upload

Hanya lakukan saat tidak ada yang memakai aplikasi.

1. Di lokal, buat arsip:
   ```powershell
   Compress-Archive -Path instance, uploads -DestinationPath pilgan-data.zip
   ```
2. Unggah arsip ke penyimpanan sementara yang bisa diakses Render (misalnya object storage atau tautan unduhan sementara).
3. Buka **Render Shell** pada service, lalu:
   ```bash
   cd /var/data
   curl -L -o data.zip "<URL_ARSIP>"
   unzip -o data.zip
   ```
4. Pastikan hasilnya:
   ```text
   /var/data/instance/pilgan.db
   /var/data/uploads/...
   ```
5. Restart service.

> Salin `pilgan.db` dan `uploads/` dalam kondisi konsisten. Jika database berubah saat disalin, data scan bisa tidak cocok dengan gambarnya.

---

## 9. Operasional & backup

- **Backup**: unduh `instance/pilgan.db` dan folder `uploads/` secara berkala. Jangan hanya mengandalkan disk Render.
- **Log**: pantau **Logs** di dashboard Render saat deploy atau saat scan gagal.
- **Ukuran data**: foto scan dan gambar debug paling cepat menghabiskan disk. Bersihkan hasil lama jika perlu.
- **Batas upload**: request maksimal **32 MB** dan maksimal **50 file** per batch. Untuk foto ponsel, 10–20 lembar per batch lebih realistis.
- **Timeout**: scan batch besar bisa lama. `GUNICORN_TIMEOUT=300` memberi ruang, tetapi tetap pecah batch agar tidak kehabisan RAM/timeout.
- **Jangan scale horizontal** selama memakai disk lokal. Untuk multi-instance: pindah ke PostgreSQL + object storage (S3/R2).

---

## 10. Troubleshooting

| Gejala | Penyebab umum | Solusi |
|---|---|---|
| Build gagal | Dependency sistem OpenCV kurang | Pastikan memakai `Dockerfile` dan `opencv-python-headless` |
| Health check gagal | App crash saat start, DB tidak bisa ditulis, atau `DATABASE_URL` salah | Buka Logs; cek `/var/data` dan koneksi database |
| 502 / request timeout | Scan terlalu banyak/berat, RAM habis | Kecilkan batch, naikkan paket, cek timeout |
| 401 terus | Password salah atau `APP_PASSWORD` tidak diset | Perbaiki env var, restart, hapus cache login browser |
| Data hilang setelah redeploy | Memakai paket gratis / disk tidak terpasang | Gunakan paket berbayar + disk `/var/data` |
| `database is locked` | Banyak worker/instance menulis SQLite | Pertahankan `WEB_CONCURRENCY=1`, jangan multi-instance |
| Gambar scan hilang tetapi nilai ada | `uploads/` tidak berada di disk persistent | Set `PILGAN_DATA_DIR=/var/data` |
| Halaman publik tanpa login | `APP_PASSWORD` kosong | Isi username + password, redeploy |

---

## 11. Uji lokal dengan Docker (opsional)

```bash
docker build -t pilgan-checker .
docker run --rm -p 8000:8000 \
  -e SECRET_KEY=tes-lokal \
  -e APP_USERNAME=admin \
  -e APP_PASSWORD=rahasia \
  -v pilgan-data:/var/data \
  pilgan-checker
```

Buka `http://localhost:8000` dan login dengan kredensial di atas.

---

## 12. Alternatif: runtime Python tanpa Docker

Jika ingin build lebih cepat dan tidak memakai Docker:

1. Di Render, buat **Web Service** dengan runtime **Python**.
2. Build command:
   ```bash
   pip install -r requirements-prod.txt
   ```
3. Start command:
   ```bash
   gunicorn -c gunicorn.conf.py app:app
   ```
4. Tetap tambahkan persistent disk di `/var/data` dan set `PILGAN_DATA_DIR=/var/data`.

`Procfile` sudah berisi start command yang sama. Namun `render.yaml` saat ini memakai Docker agar versi OpenCV dan library sistem konsisten.
