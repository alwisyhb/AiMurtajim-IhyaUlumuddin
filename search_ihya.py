#!/usr/bin/env python3
"""
CLI Tool to Search and Read Kitab Ihya' 'Ulum al-Din (Jilid 1 - 4) from Maktaba Shamela Database.
"""

import sys
import os
import argparse
import sqlite3

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ihya_ulumuddin.db')

def get_connection():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}. Please run build_database.py first.")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def list_toc():
    conn = get_connection()
    cur = conn.cursor()
    
    print("=" * 70)
    print("  فهرس كتاب إحياء علوم الدين - الإمام أبو حامد الغزالي")
    print("  DAFTAR ISI LENGKAP IHYA ULUMUDDIN (4 JILID / 40 KITAB)")
    print("=" * 70)
    
    cur.execute("SELECT volume_number, title_ar, title_id, total_pages FROM volumes ORDER BY volume_number;")
    vols = cur.fetchall()
    
    for v_num, v_ar, v_id, total_p in vols:
        print(f"\n📁 JILID {v_num}: {v_ar}")
        print(f"   ({v_id} - Total {total_p} Halaman)")
        print("   " + "-" * 60)
        
        cur.execute("""
            SELECT id, title_short, start_page, end_page, page_count, title_full
            FROM kitabs
            WHERE volume_number = ?
            ORDER BY id;
        """, (v_num,))
        
        kitabs = cur.fetchall()
        for k_id, k_short, start_p, end_p, p_count, full_title in kitabs:
            print(f"   [Kitab #{k_id:2d}] {k_short} (Hal {start_p}-{end_p}, {p_count} hal)")
            
    conn.close()

def view_page(volume, page_num):
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT global_page_id, volume, volume_page, rub_title, kitab_title, bab_title, fasal_title, content_clean
        FROM pages
        WHERE volume = ? AND volume_page = ?;
    """, (volume, page_num))
    
    row = cur.fetchone()
    if not row:
        print(f"Halaman {page_num} pada Jilid {volume} tidak ditemukan.")
        conn.close()
        return

    gid, vol, v_page, rub, kitab, bab, fasal, content = row
    print("=" * 70)
    print(f"📖 Jilid {vol} ({rub}) | Halaman {v_page} (ID Global: {gid})")
    print(f"📚 {kitab}")
    if bab:
        print(f"🔖 {bab}")
    if fasal:
        print(f"🔹 {fasal}")
    print("=" * 70)
    print(content)
    print("=" * 70)
    conn.close()

def search_text(query, volume=None, limit=10):
    conn = get_connection()
    cur = conn.cursor()
    
    sql = """
        SELECT volume, volume_page, kitab_title, bab_title,
               snippet(pages_fts, 5, '>>> ', ' <<<', '...', 20)
        FROM pages_fts
        WHERE pages_fts MATCH ?
    """
    params = [query]
    
    if volume:
        sql += " AND volume = ?"
        params.append(str(volume))
        
    sql += " LIMIT ?;"
    params.append(limit)
    
    try:
        cur.execute(sql, params)
        results = cur.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Pencarian FTS error: {e}")
        # Fallback to LIKE
        like_sql = """
            SELECT volume, volume_page, kitab_title, bab_title, substr(content_clean, 1, 200)
            FROM pages
            WHERE content_clean LIKE ?
        """
        like_params = [f"%{query}%"]
        if volume:
            like_sql += " AND volume = ?"
            like_params.append(volume)
        like_sql += " LIMIT ?;"
        like_params.append(limit)
        cur.execute(like_sql, like_params)
        results = cur.fetchall()

    print("=" * 70)
    print(f"🔍 Hasil Pencarian: '{query}' ({len(results)} temuan ditampilkan)")
    if volume:
        print(f"   Filter Jilid: {volume}")
    print("=" * 70)
    
    if not results:
        print("Tidak ada hasil yang cocok.")
    else:
        for idx, (vol, v_page, kitab, bab, snip) in enumerate(results, 1):
            print(f"\n[{idx}] Jilid {vol}, Halaman {v_page} | {kitab}")
            if bab:
                print(f"    Bab: {bab}")
            print(f"    Kutipan: {snip.strip()}")

    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Kitab Ihya' 'Ulum al-Din Shamela Database Query Tool")
    parser.add_argument("--toc", action="store_true", help="Tampilkan daftar isi (Table of Contents)")
    parser.add_argument("--read", nargs=2, type=int, metavar=("VOL", "PAGE"), help="Baca halaman tertentu, contoh: --read 1 5")
    parser.add_argument("--search", type=str, help="Cari kata/frasa dalam kitab (teks Arab)")
    parser.add_argument("--vol", type=int, help="Filter volume/jilid (1-4)")
    parser.add_argument("--limit", type=int, default=5, help="Batas jumlah hasil pencarian (default: 5)")
    
    args = parser.parse_args()
    
    if args.toc:
        list_toc()
    elif args.read:
        view_page(args.read[0], args.read[1])
    elif args.search:
        search_text(args.search, args.vol, args.limit)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
