# Sistem Pemeriksaan Lembar Jawaban Pilihan Ganda
Praktikum Pengolahan Citra Digital — Python, OpenCV, NumPy

## 1. Struktur Folder
```
proyek_pilgan/
├── main.py                     <- program utama (satu file, langsung jalan)
├── requirements.txt
├── README.md
└── dataset/
    ├── template_kosong.jpeg    <- gambar lembar KOSONG (acuan posisi huruf A-E)
    ├── kunci_contoh.csv        <- contoh format kunci jawaban
    └── lembar/                 <- taruh foto lembar terisi di sini
```

## 2. Instalasi (sekali saja)
Buka Anaconda Prompt / Terminal / CMD, masuk ke folder proyek:
```
cd path\ke\proyek_pilgan
pip install -r requirements.txt
```

## 3. Coba Dulu dengan Data Demo
```
python main.py --demo
```
Program membuat 5 foto lembar buatan (dengan perspektif, cahaya tidak rata, lingkaran/silang/arsir,
soal kosong, soal ganda), memeriksanya, dan menampilkan nilai serta akurasi pembacaan.
Hasil ada di `hasil/demo/`.

## 4. Menjalankan dengan Data Sendiri
1. Taruh foto lembar terisi di `dataset/lembar/` (misal `lembar_01.jpg` ... `lembar_25.jpg`).
2. Buat `dataset/kunci.csv` (salin dari `kunci_contoh.csv` lalu ubah isinya):
   ```
   soal,jawaban
   1,A
   2,C
   ...
   50,E
   ```
3. Jalankan:
   ```
   python main.py
   ```
   Kalau gambar berupa hasil scan / sudah dipotong rapi (tidak ada latar meja):
   ```
   python main.py --scan
   ```

### Cara mengisi lembar
Lingkari, silang, atau arsir HURUF jawaban (A-E) yang dipilih. Satu soal satu tanda.
Soal tanpa tanda = kosong, soal dengan dua tanda kuat = ganda (keduanya dihitung salah).

### Cara foto yang baik
- Seluruh 4 sudut kertas masuk frame, kertas diletakkan di atas latar yang kontras (meja gelap).
- Pencahayaan cukup, tidak ada bayangan tangan/HP yang menutupi lembar.
- Boleh agak miring, program meluruskan otomatis.

## 5. Mengukur Akurasi (opsional, untuk bab pengujian)
Buat `dataset/truth.csv` berisi jawaban asli yang ditandai tiap lembar (dicatat manual).
Satu baris per lembar, jawaban = 50 karakter (A-E, `-` = kosong, `*` = ganda):
```
lembar,jawaban
lembar_01,ABCDEABCDE...(50 karakter)
```
Jalankan:
```
python main.py --truth dataset/truth.csv
```
Akurasi pembacaan = jumlah soal yang terbaca sama dengan truth / total soal.

## 6. Output (folder `hasil/`)
- `ringkasan.csv` : benar, salah, kosong, ganda, nilai tiap lembar.
- `hasil/<nama_lembar>/` berisi satu figure `figure_tahapan.jpg` (semua tahap dalam satu grid
  berlabel: `1. Original`, `2. Grayscale`, `3. Gaussian Blur`, `4. Canny`, `5. Kontur Lembar`,
  `6. Perspective Warp`, `7. Threshold`, `8. Hasil` — kotak hijau = benar, merah = salah,
  biru = posisi kunci), serta `detail.csv` (kunci vs jawaban tiap soal).

Aturan nilai: jawaban sama dengan kunci -> `benar = benar + 1`, selain itu `salah = salah + 1`.
Nilai = benar / 50 x 100.

## 7. Parameter yang Bisa Diatur
| Opsi | Fungsi | Kapan diubah |
|---|---|---|
| `--min-extra 40` | minimal tinta tambahan agar huruf dianggap ditandai | Turunkan (30) jika tanda tipis/pensil tidak terbaca; naikkan (60) jika soal kosong terbaca terisi |
| `--dominance 3.0` | rasio tanda terkuat vs kedua; di bawahnya dianggap ganda | Naikkan jika jawaban ganda tidak terdeteksi; turunkan jika bekas hapusan dianggap ganda |
| `--scan` | lewati pencarian kertas | Gambar sudah scan / dipotong rapi |
| `--template`, `--key`, `--out` | ganti path file/folder | Kalau lokasi file berbeda |

## 8. Masalah Umum
| Gejala | Solusi |
|---|---|
| "Kertas tidak terdeteksi" | Foto di latar kontras, semua sudut terlihat, atau gunakan `--scan` |
| Banyak soal terbaca kosong | Turunkan `--min-extra`; periksa `7_threshold.jpg` apakah tanda terlihat |
| Kotak baca meleset dari huruf | Cek `6_perspective_warp.jpg`; pastikan kertas utuh dan template sama dengan lembar |
| Memakai template/lembar lain | Ubah koordinat di bagian KONFIGURASI pada `main.py` (`ROW_Y0`, `ROW_Y_STEP`, `BLOCK_COLS_X`) |

## 9. Deploy ke Render

Konfigurasi produksi sudah disiapkan: Docker, Gunicorn, persistent disk, health check, dan basic auth opsional.

Panduan lengkap ada di [`DEPLOY_RENDER.md`](DEPLOY_RENDER.md). Ringkasnya:

1. Push project ke GitHub/GitLab/Bitbucket.
2. Di Render, pilih **New → Blueprint** dan hubungkan repository.
3. Pilih blueprint:
   - `render-free.yaml` → gratis, tanpa kartu, data sementara (cocok demo).
   - `render.yaml` → berbayar, data permanen dengan persistent disk.
4. Isi `APP_PASSWORD` saat diminta, lalu Apply.
5. Buka URL service dan login dengan username `admin`.

Catatan penting: persistent disk hanya tersedia di paket berbayar. Pada paket gratis, database dan file upload akan hilang saat restart/redeploy/spin-down. SQLite sudah cukup untuk skala kecil; isi `DATABASE_URL` jika ingin memakai PostgreSQL.

## 10. Menjalankan Web App untuk Demo Lokal

Cara cepat:

- Double-click **`demo.bat`**, atau
- Jalankan di PowerShell:
  ```powershell
  .\demo.ps1
  ```

Script akan:

1. Mendeteksi virtualenv (`.venv` atau `venv`) atau memakai `python` global.
2. Mencari port kosong mulai dari `5000`.
3. Menjalankan Flask tanpa auto-reload.
4. Membuka browser otomatis setelah server siap.

Semua aset tampilan (Bootstrap, Bootstrap Icons, Chart.js, dan font Poppins) disimpan di `static/vendor/`, jadi UI tetap tampil normal tanpa koneksi internet.

Untuk menjalankan tanpa membuka browser:

```powershell
.\demo.ps1 -NoBrowser
```

Data demo tetap tersimpan di `instance/pilgan.db` dan `uploads/`. Backup keduanya sebelum presentasi:

```powershell
Compress-Archive -Path instance, uploads -DestinationPath backup-demo.zip
```


