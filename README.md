---
title: AiMurtajim IhyaUlumuddin
emoji: 📖
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Database Kitab Ihya' 'Ulum al-Din (Jilid 1 - 4) - Maktabah Syamilah

Database lengkap teks dan struktur Kitab **Ihya' 'Ulum al-Din (إحياء علوم الدين)** karya **Hujjatul Islam Abu Hamid Al-Ghazali (wafat 505 H)** yang bersumber langsung dari korpus **Al-Maktabah Asy-Syamilah (Shamela.ws ID: 9472)**, cetakan Dar al-Ma'rifah Beirut dengan catatan takhrij hadis oleh Al-Hafizh Al-Iraqi (*Al-Mughni 'an Hamlil Asfar*).

---

## 📊 Ringkasan Data

- **Judul Kitab**: إحياء علوم الدين (Ihya' 'Ulum al-Din)
- **Penulis**: أبو حامد محمد بن محمد الغزالي الطوسي (Imam Al-Ghazali)
- **Sumber Shamela**: [shamela.ws/book/9472](https://shamela.ws/book/9472)
- **Jumlah Jilid**: 4 Jilid (4 Rub')
- **Jumlah Kitab**: 40 Kitab (10 Kitab per Rub')
- **Total Halaman**: 1.706 Halaman (Lengkap Cover-to-Cover)

### Pembagian Jilid:
1. **Jilid 1 (ربع العبادات - Rub' al-'Ibadat)**: Halaman 1 – 361 (Kitab 1 – 10)
2. **Jilid 2 (ربع العادات - Rub' al-'Adat)**: Halaman 362 – 747 / Halaman 1 – 386 Jilid 2 (Kitab 11 – 20)
3. **Jilid 3 (ربع المهلكات - Rub' al-Muhlikat)**: Halaman 748 – 1160 / Halaman 1 – 413 Jilid 3 (Kitab 21 – 30)
4. **Jilid 4 (ربع المنجيات - Rub' al-Munjiyat)**: Halaman 1161 – 1706 / Halaman 1 – 546 Jilid 4 (Kitab 31 – 40)

---

## 📁 Struktur File di Folder Ini

| File / Folder | Keterangan |
| :--- | :--- |
| `ihya_ulumuddin.db` | **Database SQLite (31 MB)** lengkap dengan tabel Metadata, Volume, Kitab, Halaman, dan Full-Text Search (FTS5). |
| `json_exports/` | Folder berisi file JSON per jilid (`ihya_volume_1.json` s/d `ihya_volume_4.json`) dan `ihya_toc.json`. |
| `search_ihya.py` | Script CLI Python untuk mencari kata kunci teks Arab dan membaca per halaman. |
| `build_database.py` | Script generator untuk mengekstrak dan membangun ulang database SQLite dari data mentah. |
| `ihya_shamela_raw.txt` | Dump teks asli Shamela (7.6 MB) dengan anotasi halaman OpenITI. |

---

## 🌐 Aplikasi Web Kustom & Elegan (`Al-Mutarjim`)

Tersedia aplikasi web modern siap pakai yang dirancang khusus untuk muthala'ah Kitab Ihya 'Ulum al-Din dengan fitur:
1. **Pemberian Syakal Otomatis (Tashkil)**: Memberi harakat lengkap dan tepat sesuai kaidah Nahwu dan Shorof.
2. **Terjemahan Tiga Gaya**:
   - 🇮🇩 **Bahasa Indonesia**: Terjemahan kontekstual yang rapi dan mudah dipahami.
   - 🍃 **Basa Sunda Lemes**: Ragam bahasa hormat/halus khas pengajian para Ajengan/Kiai Sunda.
   - 🕌 **Logat Pasantren Sunda**: Makna gandul tradisional pesantren Sunda Jawa Barat
3. **Analisis I'rab & Tarkib Nahwu**: Menampilkan rincian kedudukan kata penting.
4. **Penjelajah Database Ihya Terintegrasi**: Memilih langsung Jilid 1–4, 40 Kitab, atau mencari di antara 1.706 halaman tanpa perlu copy-paste dari luar.

### Cara Menjalankan Aplikasi Web:
Cukup jalankan script launcher di terminal:
```bash
python run_app.py
```
*Atau di Windows, cukup klik dua kali file **`run.bat`**.*
Browser akan terbuka otomatis di alamat: **`http://127.0.0.1:8000`**

---

## 🚀 Cara Menggunakan CLI Tool (`search_ihya.py`)

Pastikan Python telah terinstal. Buka terminal di folder ini:

### 1. Menampilkan Daftar Isi Lengkap (40 Kitab)
```bash
python search_ihya.py --toc
```

### 2. Membaca Halaman Tertentu
Format: `python search_ihya.py --read <JILID> <HALAMAN>`
Contoh membaca Jilid 1 Halaman 1:
```bash
python search_ihya.py --read 1 1
```

### 3. Mencari Kata Kunci (Arabic Search)
Menggunakan index SQLite FTS5:
```bash
python search_ihya.py --search "طلب العلم" --limit 5
```

### 4. Mencari dengan Filter Jilid
Contoh mencari pembahasan "الصبر" hanya di Jilid 4:
```bash
python search_ihya.py --search "الصبر" --vol 4 --limit 5
```

---

## 🗄️ Skema Database SQLite (`ihya_ulumuddin.db`)

### 1. Tabel `pages`
Menyimpan seluruh halaman dari 4 jilid:
- `global_page_id` (INTEGER, PK): Nomor urut halaman global (1 s/d 1706)
- `volume` (INTEGER): Nomor Jilid (1, 2, 3, atau 4)
- `volume_page` (INTEGER): Nomor halaman pada jilid bersangkutan
- `rub_title` (TEXT): Nama Rub' (contoh: `ربع العبادات`)
- `kitab_id` (INTEGER): ID Kitab (1 s/d 40)
- `kitab_title` (TEXT): Nama Kitab (contoh: `كتاب العلم`)
- `bab_title` (TEXT): Nama Bab jika ada
- `fasal_title` (TEXT): Nama Fasal / Sub-bab jika ada
- `content_clean` (TEXT): Teks Arab yang sudah dibersihkan dari simbol teknis
- `content_raw` (TEXT): Teks mentah asli Shamela

### 2. Tabel `pages_fts`
Virtual Table SQLite FTS5 untuk pencarian teks penuh kecepatan tinggi.

### 3. Tabel `kitabs` & `volumes`
Tabel relasi untuk navigasi struktur bab dan jilid.

---

## 💻 Contoh Integrasi Program (Python)

```python
import sqlite3

conn = sqlite3.connect('ihya_ulumuddin.db')
cur = conn.cursor()

# Contoh: Cari ayat/hadits/kata dalam Ihya Ulumuddin
keyword = "نية"
cur.execute("""
    SELECT volume, volume_page, kitab_title, content_clean
    FROM pages_fts
    WHERE pages_fts MATCH ?
    LIMIT 5;
""", (keyword,))

for row in cur.fetchall():
    print(f"Jilid {row[0]}, Halaman {row[1]} ({row[2]}):\n{row[3][:150]}...\n")

conn.close()
```
