import os
import re
import sys
import json
import sqlite3

def clean_arabic_text(raw_text):
    # Remove milestone tags e.g. ms1234
    text = re.sub(r'ms\d+\s*', '', raw_text)
    # Unfold wrapped lines starting with ~~
    text = re.sub(r'\n~~', ' ', text)
    # Remove heading markers
    text = re.sub(r'^###\s*\|+\s*', '', text, flags=re.MULTILINE)
    # Remove paragraph marks like # and ~
    text = re.sub(r'^[#~]+\s*', '', text, flags=re.MULTILINE)
    # Clean whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    raw_path = os.path.join(base_dir, '..', 'ihya_shamela_raw.txt')
    if not os.path.exists(raw_path):
        raw_path = os.path.join(base_dir, 'ihya_shamela_raw.txt')

    print(f"Reading source file: {raw_path}")
    with open(raw_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    header, body = content.split('#META#Header#End#', 1)

    db_path = os.path.join(base_dir, 'ihya_ulumuddin.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create tables
    cur.execute("""
    CREATE TABLE metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE volumes (
        volume_number INTEGER PRIMARY KEY,
        title_ar TEXT,
        title_id TEXT,
        start_page INTEGER,
        end_page INTEGER,
        total_pages INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE kitabs (
        id INTEGER PRIMARY KEY,
        volume_number INTEGER,
        kitab_number INTEGER,
        title_short TEXT,
        title_full TEXT,
        start_page INTEGER,
        end_page INTEGER,
        page_count INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE pages (
        global_page_id INTEGER PRIMARY KEY,
        volume INTEGER,
        volume_page INTEGER,
        rub_title TEXT,
        kitab_id INTEGER,
        kitab_title TEXT,
        bab_title TEXT,
        fasal_title TEXT,
        content_clean TEXT,
        content_raw TEXT
    );
    """)

    # Populate metadata
    metadata_entries = [
        ("title_ar", "إحياء علوم الدين"),
        ("title_id", "Ihya Ulumuddin (Kebangkitan Ilmu-Ilmu Agama)"),
        ("author_ar", "أبو حامد محمد بن محمد الغزالي الطوسي (المتوفى: 505هـ)"),
        ("author_id", "Imam Abu Hamid Al-Ghazali (Wafat 505 H)"),
        ("publisher", "دار المعرفة - بيروت"),
        ("source", "المكتبة الشاملة (Maktaba Shamela / shamela.ws)"),
        ("shamela_book_id", "9472"),
        ("volumes_count", "4"),
        ("total_pages", "1706"),
        ("description", "Karya agung Imam Al-Ghazali yang memadukan fiqih, akhlak, dan tasawuf dalam 4 rub' (jilid) dan 40 kitab.")
    ]
    cur.executemany("INSERT INTO metadata (key, value) VALUES (?, ?);", metadata_entries)

    volume_info = {
        1: {
            "title_ar": "ربع العبادات",
            "title_id": "Rub' al-'Ibadat (Bagian Pertama: Ibadah)",
            "start_page": 1,
            "end_page": 361,
            "total_pages": 361
        },
        2: {
            "title_ar": "ربع العادات",
            "title_id": "Rub' al-'Adat (Bagian Kedua: Tradisi dan Adab Kehidupan)",
            "start_page": 362,
            "end_page": 747,
            "total_pages": 386
        },
        3: {
            "title_ar": "ربع المهلكات",
            "title_id": "Rub' al-Muhlikat (Bagian Ketiga: Hal-Hal yang Membinasakan)",
            "start_page": 748,
            "end_page": 1160,
            "total_pages": 413
        },
        4: {
            "title_ar": "ربع المنجيات",
            "title_id": "Rub' al-Munjiyat (Bagian Keempat: Hal-Hal yang Menyelamatkan)",
            "start_page": 1161,
            "end_page": 1706,
            "total_pages": 546
        }
    }

    for vol_num, info in volume_info.items():
        cur.execute("""
        INSERT INTO volumes (volume_number, title_ar, title_id, start_page, end_page, total_pages)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (vol_num, info["title_ar"], info["title_id"], info["start_page"], info["end_page"], info["total_pages"]))

    # Parse pages
    matches = list(re.finditer(r'PageV(\d+)P(\d+)', body))
    print(f"Found {len(matches)} pages across all volumes.")

    current_kitab_id = 0
    current_kitab_short = "مقدمة"
    current_kitab_full = "مقدمة الإمام الغزالي"
    current_bab = ""
    current_fasal = ""

    kitabs_dict = {}
    pages_records = []
    
    # Pre-define 40 kitab titles for clean lookup
    # Let's track kitab segments
    prev_end = 0
    for idx, m in enumerate(matches):
        global_id = idx + 1
        vol = int(m.group(1))
        vol_page = int(m.group(2))
        raw_page = body[prev_end:m.start()]
        prev_end = m.end()

        # Check for Rub' (Volume Header)
        rub_title = volume_info[vol]["title_ar"]

        # Check for Kitab transition
        k_matches = re.findall(r'###\s*\|\|\s*(كتاب[^\n]+)', raw_page)
        if k_matches:
            current_kitab_id += 1
            current_kitab_full = k_matches[-1].strip()
            # Clean short title
            short_match = re.search(r'كتاب\s+[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,3}', current_kitab_full)
            current_kitab_short = short_match.group(0).strip() if short_match else current_kitab_full
            current_bab = ""
            current_fasal = ""

            kitabs_dict[current_kitab_id] = {
                "id": current_kitab_id,
                "volume_number": vol,
                "kitab_number": current_kitab_id,
                "title_short": current_kitab_short,
                "title_full": current_kitab_full,
                "start_page": global_id,
                "end_page": global_id,
                "page_count": 0
            }

        # Check for Bab transition
        bab_matches = re.findall(r'###\s*\|\|\|\s*([^\n]+)', raw_page)
        if bab_matches:
            current_bab = bab_matches[-1].strip()
            current_fasal = ""

        # Check for Fasal transition
        fasal_matches = re.findall(r'###\s*\|\|\|\|\s*([^\n]+)', raw_page)
        if fasal_matches:
            current_fasal = fasal_matches[-1].strip()

        if current_kitab_id in kitabs_dict:
            kitabs_dict[current_kitab_id]["end_page"] = global_id
            kitabs_dict[current_kitab_id]["page_count"] += 1

        clean_text = clean_arabic_text(raw_page)
        pages_records.append((
            global_id,
            vol,
            vol_page,
            rub_title,
            current_kitab_id,
            current_kitab_short,
            current_bab,
            current_fasal,
            clean_text,
            raw_page.strip()
        ))

    # Insert kitabs
    for k_id, k_info in kitabs_dict.items():
        cur.execute("""
        INSERT INTO kitabs (id, volume_number, kitab_number, title_short, title_full, start_page, end_page, page_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            k_info["id"],
            k_info["volume_number"],
            k_info["kitab_number"],
            k_info["title_short"],
            k_info["title_full"],
            k_info["start_page"],
            k_info["end_page"],
            k_info["page_count"]
        ))

    # Insert pages
    print("Inserting 1706 pages into database...")
    cur.executemany("""
    INSERT INTO pages (
        global_page_id, volume, volume_page, rub_title,
        kitab_id, kitab_title, bab_title, fasal_title,
        content_clean, content_raw
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, pages_records)

    # Create FTS5 virtual table for lightning search
    print("Building FTS5 full-text search index...")
    cur.execute("""
    CREATE VIRTUAL TABLE pages_fts USING fts5(
        global_page_id UNINDEXED,
        volume UNINDEXED,
        volume_page UNINDEXED,
        kitab_title,
        bab_title,
        content_clean
    );
    """)

    cur.execute("""
    INSERT INTO pages_fts (global_page_id, volume, volume_page, kitab_title, bab_title, content_clean)
    SELECT global_page_id, volume, volume_page, kitab_title, bab_title, content_clean FROM pages;
    """)

    # Create normal indexes
    cur.execute("CREATE INDEX idx_pages_vol ON pages(volume);")
    cur.execute("CREATE INDEX idx_pages_kitab ON pages(kitab_id);")

    conn.commit()
    conn.close()
    print(f"SQLite database created successfully at: {db_path}")

    # Export JSON per volume
    json_dir = os.path.join(base_dir, 'json_exports')
    print(f"Exporting JSON files into: {json_dir}")

    for vol_num in range(1, 5):
        vol_pages = [
            {
                "global_page_id": r[0],
                "volume": r[1],
                "volume_page": r[2],
                "rub_title": r[3],
                "kitab_id": r[4],
                "kitab_title": r[5],
                "bab_title": r[6],
                "fasal_title": r[7],
                "content": r[8]
            }
            for r in pages_records if r[1] == vol_num
        ]
        vol_file = os.path.join(json_dir, f"ihya_volume_{vol_num}.json")
        with open(vol_file, 'w', encoding='utf-8') as jf:
            json.dump({
                "volume": vol_num,
                "rub_ar": volume_info[vol_num]["title_ar"],
                "rub_id": volume_info[vol_num]["title_id"],
                "page_count": len(vol_pages),
                "pages": vol_pages
            }, jf, ensure_ascii=False, indent=2)
        print(f"Exported Volume {vol_num}: {len(vol_pages)} pages -> {vol_file}")

    # Table of contents JSON
    toc_file = os.path.join(json_dir, "ihya_toc.json")
    with open(toc_file, 'w', encoding='utf-8') as jf:
        json.dump({
            "metadata": dict(metadata_entries),
            "volumes": volume_info,
            "kitabs": list(kitabs_dict.values())
        }, jf, ensure_ascii=False, indent=2)
    print(f"Exported Table of Contents -> {toc_file}")

if __name__ == '__main__':
    main()
