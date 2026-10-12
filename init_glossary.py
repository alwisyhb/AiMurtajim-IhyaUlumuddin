import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "ihya_ulumuddin.db"

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    # Strip harakat
    t = re.sub(r'[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]', '', text)
    # Normalize alif
    t = re.sub(r'[إأآٱ]', 'ا', t)
    # Normalize ya / alif maqsura
    t = re.sub(r'ى', 'ي', t)
    # Normalize ta marbuta
    t = re.sub(r'ة', 'ه', t)
    # Strip tatweel
    t = re.sub(r'ـ', '', t)
    return t.strip()

SEED_DATA = [
    # 1. KAIDAH NAHWU & PENANDA LOGAT PESANTREN SUNDA (RUMUS UTAMA)
    {
        "arabic_word": "المبتدأ",
        "grammar_role": "mubtada",
        "pesantren_marker": "Ari",
        "sunda_meaning": "Ari (Kudu dipake KHUSUS pikeun isim marfu' nu jadi pokok kalimah di mimiti jumlah)",
        "indo_meaning": "Adapun (penanda subjek/mubtada')",
        "category": "nahwu_marker",
        "notes": "PENTING: 'Ari' HANYA pikeun Mubtada'. Entong dipake dina fi'il atawa kedudukan sejen!"
    },
    {
        "arabic_word": "الخبر",
        "grammar_role": "khabar",
        "pesantren_marker": "eta",
        "sunda_meaning": "eta (penyampurna makna mubtada')",
        "indo_meaning": "Adalah / itu (penanda predikat/khabar)",
        "category": "nahwu_marker",
        "notes": "Dipake nalika nyaritakeun kaayaan mubtada'"
    },
    {
        "arabic_word": "الفاعل",
        "grammar_role": "fail",
        "pesantren_marker": "saha / naon",
        "sunda_meaning": "saha (pikeun jalma/nu boga akal) / naon (pikeun barang/perkara)",
        "indo_meaning": "Siapa / apa (penanda subjek pelaku)",
        "category": "nahwu_marker",
        "notes": "Subjek saenggeus fi'il ma'ruf. Misal: قال النبي -> Geus ngadawuh saha Kangjeng Nabi"
    },
    {
        "arabic_word": "نائب الفاعل",
        "grammar_role": "naibul_fail",
        "pesantren_marker": "naon / saha",
        "sunda_meaning": "naon (perkara) / saha (jalma) saenggeus fi'il majhul",
        "indo_meaning": "Apa / siapa (pengganti pelaku fi'il pasif)",
        "category": "nahwu_marker",
        "notes": "Misal: قيل -> Diucapkeun naon hiji ucapan"
    },
    {
        "arabic_word": "المفعول به",
        "grammar_role": "maful_bih",
        "pesantren_marker": "kana",
        "sunda_meaning": "kana (pikeun objek penderita nu keuna ku pagawean)",
        "indo_meaning": "Kepada / akan / pada (penanda objek)",
        "category": "nahwu_marker",
        "notes": "Misal: طلب العلم -> Nyiar kana elmu"
    },
    {
        "arabic_word": "المفعول لأجله",
        "grammar_role": "maful_liajlih",
        "pesantren_marker": "karana / karana karana",
        "sunda_meaning": "karana / karana karana (alesan migawe pagawean)",
        "indo_meaning": "Karena / demi alasan",
        "category": "nahwu_marker",
        "notes": "Misal: ابتغاء مرضاة الله -> Karana nyiar karidhaan Allah"
    },
    {
        "arabic_word": "الحال",
        "grammar_role": "hal",
        "pesantren_marker": "halna / bari",
        "sunda_meaning": "halna / bari (nerangkeun kaayaan waktu migawe)",
        "indo_meaning": "Dalam keadaan / seraya",
        "category": "nahwu_marker",
        "notes": "ULAH make 'Ari'! Kudu make 'halna' atawa 'bari'."
    },
    {
        "arabic_word": "التمييز",
        "grammar_role": "tamyiz",
        "pesantren_marker": "apana",
        "sunda_meaning": "apana (ngajelaskeun samar tina zat atawa nisbat)",
        "indo_meaning": "Apanya / segi mananya",
        "category": "nahwu_marker",
        "notes": "Misal: طاب نفسا -> Geus ngeunah naon jiwana apana jiwana"
    },
    {
        "arabic_word": "جواب الشرط",
        "grammar_role": "jawab_syarth",
        "pesantren_marker": "mangka",
        "sunda_meaning": "mangka (akibat/natijah tina syarat)",
        "indo_meaning": "Maka (akibat syarat)",
        "category": "nahwu_marker",
        "notes": "Misal: فمن يعمل... -> Mangka sing saha jalma..."
    },
    {
        "arabic_word": "الشرط",
        "grammar_role": "syarth",
        "pesantren_marker": "lamun / saupama / upama",
        "sunda_meaning": "lamun / saupama (kalimah syarat)",
        "indo_meaning": "Jikalau / apabila",
        "category": "nahwu_marker",
        "notes": "Pikeun in, idza, lau"
    },
    {
        "arabic_word": "النعت",
        "grammar_role": "naat",
        "pesantren_marker": "anu / nu",
        "sunda_meaning": "anu / nu (sipat pikeun man'ut)",
        "indo_meaning": "Yang (sifat)",
        "category": "nahwu_marker",
        "notes": "Penjelas sipat isim samemehna"
    },
    {
        "arabic_word": "البدل",
        "grammar_role": "badal",
        "pesantren_marker": "nyatana",
        "sunda_meaning": "nyatana (gaganti/penjelas mubdal minhu)",
        "indo_meaning": "Yaitu / yakni",
        "category": "nahwu_marker",
        "notes": "Misal: اهدنا الصراط المستقيم صراط الذين -> Nyatana jalanna jalma-jalma"
    },
    {
        "arabic_word": "المفعول المطلق",
        "grammar_role": "maful_muthlaq",
        "pesantren_marker": "kalawan / bener-bener",
        "sunda_meaning": "kalawan bener-bener / kalawan hiji tingkah",
        "indo_meaning": "Dengan sebenar-benarnya (penguat perbuatan)",
        "category": "nahwu_marker",
        "notes": "Pikeun tawkid masdar"
    },

    # 2. KOSA KATA KHAS KITAB IHYA' 'ULUM AL-DIN (TASAWWUF & AKHLAK)
    {
        "arabic_word": "طلب العلم",
        "grammar_role": "mubtada",
        "pesantren_marker": "Ari",
        "sunda_meaning": "Ari nyiar elmu",
        "indo_meaning": "Menuntut ilmu",
        "category": "tasawwuf",
        "notes": "Istilah bab fadilah elmu"
    },
    {
        "arabic_word": "العلم",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "elmu / kanyaho anu sajati",
        "indo_meaning": "Ilmu pengetahuan agama",
        "category": "tasawwuf",
        "notes": "Ihya Jilid 1 Kitab al-Ilm"
    },
    {
        "arabic_word": "العمل",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "amal perbuatan / migawé amal",
        "indo_meaning": "Amal perbuatan",
        "category": "tasawwuf",
        "notes": "Amal soleh"
    },
    {
        "arabic_word": "القلب",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "hate / angen-angen / hakikat rasa batin",
        "indo_meaning": "Hati nurani / qolbu",
        "category": "tasawwuf",
        "notes": "Bab 'Aja'ibul Qalb"
    },
    {
        "arabic_word": "النفس",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "hawa nafsu / diri sorangan",
        "indo_meaning": "Jiwa / hawa nafsu",
        "category": "tasawwuf",
        "notes": "Nafsu ammarah, lawwamah, muthmainnah"
    },
    {
        "arabic_word": "الروح",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "ruh / nyawa rohani",
        "indo_meaning": "Roh",
        "category": "tasawwuf",
        "notes": "Lathifah Robbaniyyah"
    },
    {
        "arabic_word": "العقل",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "akal pikiran / kakuatan mikir",
        "indo_meaning": "Akal budi",
        "category": "tasawwuf",
        "notes": "Cahaya dina hate"
    },
    {
        "arabic_word": "الرياء",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "riya / sipat hayang kapuji ku sasama manusa",
        "indo_meaning": "Riya (pamer amal)",
        "category": "tasawwuf",
        "notes": "Panyakit batin nu ngabatalkeun ganjaran"
    },
    {
        "arabic_word": "العجب",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "'ujub / ngarasa leuwih hade jeung gumede kana amal sorangan",
        "indo_meaning": "Ujub (bangga diri)",
        "category": "tasawwuf",
        "notes": "Panyakit batin muhlikat"
    },
    {
        "arabic_word": "الكبر",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "kibir / sombong / adigung adiguna",
        "indo_meaning": "Sombong / takabur",
        "category": "tasawwuf",
        "notes": "Nampik kabeneran jeung ngahina batur"
    },
    {
        "arabic_word": "الحسد",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "hasud / sirik dengki kana kanikmatan batur",
        "indo_meaning": "Hasad / dengki",
        "category": "tasawwuf",
        "notes": "Ngaharepkeun leungitna nikmat batur"
    },
    {
        "arabic_word": "الغفلة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "poho / lalawora tina dzikir ka Allah SWT",
        "indo_meaning": "Lalai / kelalaian dari mengingat Allah",
        "category": "tasawwuf",
        "notes": "Kaayaan hate nu poho"
    },
    {
        "arabic_word": "الإخلاص",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "ikhlas / beresih niat murni karana Allah Ta'ala",
        "indo_meaning": "Ikhlas semata-mata karena Allah",
        "category": "tasawwuf",
        "notes": "Rukun amal ditampi"
    },
    {
        "arabic_word": "التوبة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "tobat / kaduhung jeung balik deui tina maksiat kana ta'at",
        "indo_meaning": "Tobat / penyesalan dosa",
        "category": "tasawwuf",
        "notes": "Munjiyat mimiti"
    },
    {
        "arabic_word": "الصبر",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "sabar / nahan diri dina kasedih, musibah, jeung ta'at",
        "indo_meaning": "Sabar",
        "category": "tasawwuf",
        "notes": "Separuh tina iman"
    },
    {
        "arabic_word": "الشكر",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "syukur / ngaku kana nikmat kalawan ngagunakeunana dina ta'at",
        "indo_meaning": "Syukur atas nikmat-Nya",
        "category": "tasawwuf",
        "notes": "Separuh deui tina iman"
    },
    {
        "arabic_word": "الخوف",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "sieun / khauf ku siksaan jeung bendu Allah SWT",
        "indo_meaning": "Takut kepada Allah",
        "category": "tasawwuf",
        "notes": "Pamecut hate nuju ta'at"
    },
    {
        "arabic_word": "الرجاء",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "roja' / harepan ageung kana rahmat jeung pangampura-Na",
        "indo_meaning": "Harapan atas rahmat-Nya",
        "category": "tasawwuf",
        "notes": "Panyalindung tina putus asa"
    },
    {
        "arabic_word": "الزهد",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "zuhud / nolak karep kana dunya karana mikacinta akherat",
        "indo_meaning": "Zuhud terhadap duniawi",
        "category": "tasawwuf",
        "notes": "Tingkatan ahli suluk"
    },
    {
        "arabic_word": "التوكل",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "tawakkal / masrahkeun sakabeh urusan ka Gusti Allah kalawan ihtiar",
        "indo_meaning": "Tawakal dan berserah diri kepada Allah",
        "category": "tasawwuf",
        "notes": "Hakekat kapercayaan batin"
    },
    {
        "arabic_word": "المحبة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "mahabbah / kacida cinta jeung mikacinta ka Gusti Allah",
        "indo_meaning": "Cinta murni kepada Allah",
        "category": "tasawwuf",
        "notes": "Puncak maqamat"
    },
    {
        "arabic_word": "المراقبة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "muroqobah / ngarasa batin salawasna diawasi ku Gusti Allah SWT",
        "indo_meaning": "Mawas diri dalam pengawasan Allah",
        "category": "tasawwuf",
        "notes": "Ihsan: ningali atawa katingali ku Allah"
    },
    {
        "arabic_word": "المحاسبة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "muhasabah / mariksa jeung nimbang-nimbang amal diri sorangan",
        "indo_meaning": "Introspeksi amal perbuatan",
        "category": "tasawwuf",
        "notes": "Nimbang diri samemeh ditimbang di akherat"
    },
    {
        "arabic_word": "السالك",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "salik / jalma anu keur leumpang ngambah jalan nuju ka ridha Allah",
        "indo_meaning": "Penempuh jalan spiritual",
        "category": "tasawwuf",
        "notes": "Santri thariqah / ahli suluk"
    },
    {
        "arabic_word": "المريد",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "murid / santri anu boga tekad buleud nuju ka akherat",
        "indo_meaning": "Murid / pencari kebenaran",
        "category": "tasawwuf",
        "notes": "Ahli thalabul ilmi"
    },
    {
        "arabic_word": "الشيخ",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "guru / Ajengan / Kiai panungtun rohani",
        "indo_meaning": "Guru / Syekh / Ulama pembimbing",
        "category": "tasawwuf",
        "notes": "Murabbi ruhi"
    },
    {
        "arabic_word": "الدنيا",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "dunya / kahirupan dunya anu fana jeung pinuh ujian",
        "indo_meaning": "Kehidupan dunia fana",
        "category": "tasawwuf",
        "notes": "Ladang pikeun akherat"
    },
    {
        "arabic_word": "الآخرة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "akherat / nagara akherat anu langgeng abadi",
        "indo_meaning": "Negeri akhirat yang kekal",
        "category": "tasawwuf",
        "notes": "Tujuan utama manusa"
    },
    {
        "arabic_word": "الهوى",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "hawa nafsu anu condong kana kagorengan",
        "indo_meaning": "Hawa nafsu yang menyesatkan",
        "category": "tasawwuf",
        "notes": "Musuh jero diri"
    },
    {
        "arabic_word": "المعصية",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "maksiat / migawé dosa jeung ngarempak larangan Gusti Allah",
        "indo_meaning": "Perbuatan maksiat dan dosa",
        "category": "tasawwuf",
        "notes": "Racun pikeun rohani"
    },
    {
        "arabic_word": "الطاعة",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "ta'at / ngalaksanakeun sagala timbalan Gusti Allah",
        "indo_meaning": "Ketaatan kepada Allah",
        "category": "tasawwuf",
        "notes": "Cahaya rohani"
    },
    {
        "arabic_word": "الذكر",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "dzikir / salawasna eling ka Gusti Allah SWT",
        "indo_meaning": "Mengingat Allah SWT (dzikir)",
        "category": "tasawwuf",
        "notes": "Ubar panyakit hate"
    },
    {
        "arabic_word": "الفكر",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "tafakkur / mikir-mikir kana kakawasaan jeung ciptaan Allah",
        "indo_meaning": "Tafakur / perenungan mendalam",
        "category": "tasawwuf",
        "notes": "Ibadah akal"
    },
    {
        "arabic_word": "النية",
        "grammar_role": "umum",
        "pesantren_marker": "",
        "sunda_meaning": "niat / pamaksudan jero hate dina migawe hiji amal",
        "indo_meaning": "Niat yang tulus",
        "category": "tasawwuf",
        "notes": "Ruhna amal"
    }
]

def init_glossary():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pesantren_glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arabic_word TEXT NOT NULL,
            arabic_norm TEXT NOT NULL,
            grammar_role TEXT DEFAULT 'umum',
            pesantren_marker TEXT,
            sunda_meaning TEXT NOT NULL,
            indo_meaning TEXT,
            category TEXT DEFAULT 'umum',
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(arabic_word, grammar_role)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_glossary_norm ON pesantren_glossary(arabic_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_glossary_category ON pesantren_glossary(category);")
    
    # Insert or ignore seeds
    inserted = 0
    for item in SEED_DATA:
        norm = normalize_arabic(item["arabic_word"])
        try:
            cur.execute("""
                INSERT OR IGNORE INTO pesantren_glossary 
                (arabic_word, arabic_norm, grammar_role, pesantren_marker, sunda_meaning, indo_meaning, category, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item["arabic_word"],
                norm,
                item["grammar_role"],
                item.get("pesantren_marker", ""),
                item["sunda_meaning"],
                item.get("indo_meaning", ""),
                item.get("category", "umum"),
                item.get("notes", "")
            ))
            if cur.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"Error inserting {item['arabic_word']}: {e}")
            
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM pesantren_glossary;")
    total = cur.fetchone()[0]
    conn.close()
    print(f"Pesantren glossary initialized successfully! Seeded {inserted} items, Total: {total} entries.")

if __name__ == "__main__":
    init_glossary()
