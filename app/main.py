import os
import re
import asyncio
import json
import time
import hashlib
import sqlite3
import traceback
import urllib.parse
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# App and Paths
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DB_PATH = PROJECT_DIR / "ihya_ulumuddin.db"
LOG_PATH = PROJECT_DIR / "api_debug.log"
ENV_PATH = PROJECT_DIR / ".env"

def load_env_file():
    if ENV_PATH.exists():
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

load_env_file()

app = FastAPI(title="Al-Mutarjim Ihya' 'Ulum al-Din", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Vercel subpath rewrite middleware
class VercelPathMiddleware:
    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            query_bytes = scope.get("query_string", b"")
            query_str = query_bytes.decode("utf-8") if query_bytes else ""
            if "__orig_path__=" in query_str:
                parsed = urllib.parse.parse_qs(query_str)
                orig_path = parsed.get("__orig_path__", [""])[0]
                if orig_path:
                    if not orig_path.startswith("/"):
                        orig_path = "/" + orig_path
                    scope["path"] = orig_path
                    scope["raw_path"] = orig_path.encode("utf-8")
                    del parsed["__orig_path__"]
                    new_q = "&".join(
                        f"{urllib.parse.quote(k)}={urllib.parse.quote(v)}"
                        for k, vals in parsed.items()
                        for v in vals
                    )
                    scope["query_string"] = new_q.encode("utf-8")
                else:
                    scope["path"] = "/"
                    scope["raw_path"] = b"/"
            elif scope.get("path") in ("/api/index.py", "/api/index", "/api"):
                scope["path"] = "/"
                scope["raw_path"] = b"/"

        await self.asgi_app(scope, receive, send)

app.add_middleware(VercelPathMiddleware)

# Mount static files
static_dir = BASE_DIR / "static"
try:
    static_dir.mkdir(exist_ok=True)
except Exception:
    pass
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

def log_debug(msg: str):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{os.getpid()}] {msg}\n")
    except Exception:
        pass

# Database Helper
def get_db_path() -> Path:
    candidates = [
        DB_PATH,
        PROJECT_DIR / "ihya_ulumuddin.db",
        Path.cwd() / "ihya_ulumuddin.db",
        BASE_DIR / "ihya_ulumuddin.db",
        Path("/var/task/ihya_ulumuddin.db"),
        Path("/app/ihya_ulumuddin.db")
    ]
    for c in candidates:
        if c.exists():
            return c
    return DB_PATH

def get_db():
    p = get_db_path()
    if not p.exists():
        raise HTTPException(status_code=500, detail="Database file ihya_ulumuddin.db not found.")
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn

# Book registry: each book has its own database, Ihya stays the default for old clients
BOOKS_PATH = PROJECT_DIR / "data" / "books.json"

def load_books() -> List[Dict[str, Any]]:
    with open(BOOKS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

BOOKS = load_books()
DEFAULT_BOOK = next(b for b in BOOKS if b.get("default"))

def resolve_book(book: Optional[str]) -> Dict[str, Any]:
    if not book:
        return DEFAULT_BOOK
    for b in BOOKS:
        if b["id"] == book:
            return b
    raise HTTPException(status_code=400, detail=f"Kitab '{book}' tidak dikenal.")

def hadith_book(book: Optional[str]) -> Optional[Dict[str, Any]]:
    """Returns the book when it is navigated by hadith; page based books return None."""
    cfg = resolve_book(book)
    return cfg if cfg["navigation"] == "hadith" else None

def get_book_db(cfg: Dict[str, Any]):
    candidates = [PROJECT_DIR / cfg["db"], Path.cwd() / cfg["db"], Path("/var/task") / cfg["db"], Path("/app") / cfg["db"]]
    for c in candidates:
        if c.exists():
            conn = sqlite3.connect(str(c))
            conn.row_factory = sqlite3.Row
            return conn
    raise HTTPException(status_code=500, detail=f"Database file {cfg['db']} not found.")

def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r'[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]', '', text)
    t = re.sub(r'[إأآٱ]', 'ا', t)
    t = re.sub(r'ى', 'ي', t)
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'ـ', '', t)
    return t.strip()

def get_matched_glossary(cleaned_text: str):
    norm_text = normalize_arabic(cleaned_text)
    
    conn = get_db()
    cur = conn.cursor()
    # 1. Always get core nahwu markers
    cur.execute("SELECT arabic_word, grammar_role, pesantren_marker, sunda_meaning, indo_meaning FROM pesantren_glossary WHERE category = 'nahwu_marker';")
    core_rules = [dict(r) for r in cur.fetchall()]
    
    # 2. Get vocabulary matches from user glossary database (supports single words & compound phrases)
    matched_vocab = []
    if norm_text:
        cur.execute("""
            SELECT arabic_word, grammar_role, pesantren_marker, sunda_meaning, indo_meaning 
            FROM pesantren_glossary 
            WHERE category NOT LIKE 'nahwu_%' AND length(arabic_norm) >= 3 AND instr(?, arabic_norm) > 0 
            ORDER BY length(arabic_norm) DESC 
            LIMIT 30;
        """, (norm_text,))
        matched_vocab = [dict(r) for r in cur.fetchall()]
        
    conn.close()
    return core_rules, matched_vocab

# Request Models
class ProcessRequest(BaseModel):
    text: str
    api_key: Optional[str] = None
    model_name: Optional[str] = "gemini-3.5-flash"
    fast_mode: Optional[bool] = False
    stage: Optional[str] = None
    tashkil: Optional[str] = None
    logat: Optional[str] = None
    book: Optional[str] = None

class KeyRequest(BaseModel):
    api_key: str

class GlossaryItem(BaseModel):
    arabic_word: str
    grammar_role: Optional[str] = "umum"
    pesantren_marker: Optional[str] = ""
    sunda_meaning: str
    indo_meaning: Optional[str] = ""
    category: Optional[str] = "umum"
    notes: Optional[str] = ""

SYSTEM_INSTRUCTION = """
Anda adalah pakar bahasa Arab klasik dan mahaguru penerjemah kitab kuning ke dalam Bahasa Indonesia dan Bahasa Sunda (khususnya tradisi Ngalogat Pasantren Sunda / Makna Gandul Jawa Barat rujukan Alfiyyah Ibnu Malik).

Tugas Anda saat memproses kutipan kitab (Ihya 'Ulum al-Din):

1. 'tashkil':
   Berikan syakal (harakat) LENGKAP dan AKURAT sesuai kaidah Nahwu dan Shorof. Harakat akhir (i'rab) wajib jelas (dhammah, fathah, kasrah, sukun, tanwin, tasydid).

2. 'tarkib_notes':
   Analisis kedudukan Nahwu dan Shorof LENGKAP untuk SETIAP KATA / FRASA teks yang diproses (bukan hanya sebagian, mencakup seluruh kata dari awal sampai akhir). Untuk setiap kata, cantumkan:
   - 'word': Lafadz Arab bersyakal
   - 'position': Kedudukan Nahwu (Mubtada', Khabar, Fa'il, Maf'ul Bih, Na'at/Shifat, Mudhaf Ilaih, Jar-Majrur, Harf Athaf, Ma'thuf, Hal, Tamyiz, Isim Inna, Khabar Kaana, dll.)
   - 'shorof': Analisis Shorof & Morfologi (Kalimah Isim/Fi'il/Haraf, Sighat Fi'il Madhi/Mudhari'/Masdar/Isim Fa'il/Isim Maf'ul/Sifat Musyabbahah, Wazan seperti فَعَلَ / أَفْعَلَ / تَفَعَّلَ / اسْتَفْعَلَ, Bina' Shahih/Ajwaf/Naqish)
   - 'i_rab': I'rab dan tanda (Marfu' bid-dhammah, Manshub bil-fathah, Majrur bil-kasrah, Majzum bis-sukun, Mabni 'alal fathi, dll.)
   - 'symbol': Simbol Tarkib Pesantren Sunda ([م], [خ], [فا], [مف], [ص], [ج], [مج], [ع], [مض], [ح], [ت])
   - 'note': Catatan kaidah Nahwu Alfiyyah dan makna logat Sunda.

3. 'translation_id':
   Terjemahan Bahasa Indonesia yang mengalir, akurat, dan khidmat. WAJIB murni Bahasa Indonesia, tanpa kata Sunda (misal tulis 'hati', BUKAN 'hate').
   *ATURAN WAJIB KAPITALISASI*:
   - Dhamir/sebutan kepada ALLAH SWT WAJIB diawali huruf kapital dengan tanda hubung: 'kepada-Nya', 'rahmat-Nya', 'ridha-Nya', 'hamba-Nya', 'petunjuk-Nya', 'Dia', 'firman-Nya'.
   - Dhamir/sebutan kepada NABI MUHAMMAD SAW WAJIB diawali huruf kapital: 'Beliau', 'Nabi-Nya', 'Rasul-Nya', 'utusan-Nya', 'ajaran Beliau'.

4. 'translation_sunda_lemes':
   Terjemahan ke dalam Basa Sunda Lemes (ragam hormat/halus) yang santun dan khidmat khas pengaosan para Ajengan/Kiai Sunda.

5. 'translation_sunda_logat' (STANDAR RESMI NGALOGAT PASANTREN SUNDA - ALFIYYAH IBNU MALIK):
   Hasilkan pembacaan makna kitab khas pasantren Sunda yang MURNI BASA SUNDA, RUNTUT, dan DISIPLIN KAIDAH NAHWU:
   
   * LARANGAN KERAS:
     1. DILARANG MENCAMPUR TRANSLITERASI ARAB LATIN! Jangan menduplikasi lafadz Arab (misal DILARANG: 'al-ula eta tetep', DILARANG: 'ari hu eta teh nyaeta hifdzul milki', DILARANG: 'bi-tarkil-ietaqi kalawan ninggalkeun'). Tuliskan LANGSUNG maknanya dalam Basa Sunda bersama partikel nahwunya.
     2. DILARANG MEMAKAI KATA BAHASA INDONESIA! Wajib 100% kosakata Basa Sunda (JANGAN pakai: 'berkata', 'maka', 'jika', 'karena', 'tetapi', 'bahwa', 'tidak', 'adalah').
        Gunakan padanan Sunda: 'Geus ngadawuh/ngucap saha...', 'Mangka', 'Lamun', 'Karana / Ku sabab', 'Nanging', 'Saestuna / Yen', 'Henteu / Moal', 'Eta / Eta tetep'.
     3. DILARANG MEMAKAI 'kuring'! Orang pertama tunggal WAJIB 'kaula' secara konsisten dari awal sampai akhir (lihat Kaidah 5).
     4. DILARANG RAGAM LEMES DI LOGAT! Pakai 'geus' (BUKAN 'parantos'), 'nepi' (BUKAN 'dugi'), 'datang' (BUKAN 'sumping'), 'perkara' (BUKAN 'perkawis').
     5. TULIS SATU PILIHAN MAKNA SAJA! DILARANG menulis dua pilihan dengan garis miring (misal DILARANG: 'nyangkut/mandep') dan DILARANG menambah keterangan dalam tanda kurung.

   * KAIDAH 1: KHABAR MUFRAD & GHAIR MUFRAD (ALFIYYAH: وأخبروا بظرف أو بحرف جر # ناوين معنى كائن أو استقر):
     - KHABAR MUFRAD: WAJIB diawali 'eta...'
       Contoh: طَلَبُ الْعِلْمِ فَرِيْضَةٌ -> 'Ari nyiar elmu, eta wajib hukumna'.
     - KHABAR GHAIR MUFRAD DARI JAR-MAJRUR & ZHARAF (SYIBHUL JUMLAH): WAJIB diawali 'eta tetep...' (karena berta'alluq pada muta'allaq mahdzuf ka'inun/istaqarra).
       Contoh: اَلْحَمْدُ لِلَّهِ -> 'Ari sakur puji, eta tetep hak kagungan Gusti Allah'.
       Contoh: زَيْدٌ فِي الدَّارِ -> 'Ari Ki Zaid, eta tetep di jero imah'.
       Contoh: عَلَى كُلِّ مُسْلِمٍ -> 'eta tetep ka unggal-unggal jalma islam'.
     - KHABAR JUMLAH FI'LIYYAH: diawali 'eta (geus / keur)...'
       Contoh: زَيْدٌ قَامَ أَبُوهُ -> 'Ari Ki Zaid, eta geus nangtung saha bapana'.

   * KAIDAH 2: MAF'UL BIH (OBJEK MATI vs OBJEK HIDUP/BERAKAL):
     - Objek Benda Mati / Perkara / Sifat Abstrak: WAJIB diawali 'kana...'
       Contoh: طَلَبَ الْعِلْمَ -> 'geus nyiar saha manehna kana elmu'.
       Contoh: قَرَأَ الْكِتَابَ -> 'geus maca saha manehna kana kitab'.
       Contoh: حَفِظَ الْمُلْكَ -> 'ngaraksa manehna kana hak milik'.
     - Objek Makhluk Hidup / Berakal / Allah SWT / Para Rasul: WAJIB diawali 'ka...'
       Contoh: ضَرَبَ زَيْدًا -> 'geus neunggeul saha manehna ka Ki Zaid'.
       Contoh: أَطِيعُوا اللَّهَ وَأَطِيعُوا الرَّسُولَ -> 'kudu taat aranjeun ka Gusti Allah jeung ka Rasul'.
       Contoh: أَكْرَمَ الْعَالِمَ -> 'geus ngamulyakeun saha manehna ka jalma anu alim'.

   * KAIDAH 3: AMIL NAWASIKH (PENYALIN MUBTADA & KHABAR):
     1. KANA WA AKHWATUHA (كان وأخواتها - Merofa'kan Isim, Menashobkan Khabar):
        - Kaana: 'geus bukti / aya (saha/naon)...', Laisa: 'henteu bukti (saha/naon)...', Mazala/Mabariha: 'henteu kendat-kendat / tuluy-tuluy (saha/naon)...', Shara: 'geus jadi / salin jinis...', Madam: 'salagi bukti...'.
        - Isim Kaana: 'saha...' (berakal) / 'naon...' (benda).
        - Khabar Kaana: 'eta...' (mufrad) / 'eta tetep...' (jar-majrur/zharaf).
     2. INNA WA AKHWATUHA (إن وأخواتها - Menashobkan Isim, Merofa'kan Khabar):
        - Inna / Anna: CUKUP dimaknai 'saestuna...' atau 'saenya-enyana...' SAJA! DILARANG KERAS MENAMBAHKAN 'ari' setelah inna/anna!
          Contoh BENAR: إِنَّ اللَّهَ غَفُورٌ -> 'Saestuna Gusti Allah eta Nu Maha Ngahapunten' (atau 'Saenya-enyana Gusti Allah eta...'). JANGAN: 'Saestuna ari Gusti Allah'!
        - KHAS KHABAR INNA MUQADDAM & ISIM INNA MU'AKHKHAR:
          Jika Khabar Inna didahulukan (muqaddam) berupa Jar-Majrur atau Zharaf, maka makna Isim Inna Mu'akhkhar WAJIB diawali kata 'aya...' (ada)!
          Contoh: إِنَّ فِي ذَلِكَ لَآيَةً -> 'Saestuna eta tetep dina perkara anu kasebut, aya hiji tanda (ayat)...'
          Contoh: إِنَّ مَعَ الْعُسْرِ يُسْرًا -> 'Saestuna eta tetep sarta kasusahan, aya kamudahan...'
          Contoh: إِنَّ لَدَيْنَا أَنْكَالًا -> 'Saestuna eta tetep di sisi Kami, aya pirang-pirang belenggu...'
        - Ka'anna: 'lir ibarat...', Lakinna: 'nanging...', Laita: 'muga-muga...', La'alla: 'sugan-sugan... / meureun-meureun...'.
        - Laa Nafi lil-Jinsi: 'henteu aya jenis (isim) eta tetep...'.
     3. ZHANNA WA AKHWATUHA (ظن وأخواتها - Menashobkan Dua Maf'ul):
        - Zhanna/Hasiba: 'geus nyangka (saha)...', Ra'aa/'Alima/Wajada: 'geus yakin nyaho (saha)...', Shoyyaro/Ja'ala: 'geus ngajadikeun (saha)...'.
        - Maf'ul 1: 'kana...' (benda mati) / 'ka...' (makhluk hidup).
        - Maf'ul 2: 'yen eta...' / 'kana kaayaan...'.
     4. KAADA WA AKHWATUHA (كاد وأخواتها):
        - Kaada/Karaba/Ausyaka (Muqorobah): 'ampir-ampiran / méh-méhan / geus deukeut'.
           Pola 'كَادَ [الاسم] أَنْ يَكُونَ [الخبر]': 'Ampir-ampiran naon [isimna], yen aya itu [isimna] teh, eta [khabarna]'.
           Contoh: كَادَ الْفَقْرُ أَنْ يَكُونَ كُفْرًا -> 'Ampir-ampiran naon kafakiran, yen aya itu kafakiran teh, eta kufur'.
        - 'Asaa/Haraa (Raja'): 'muga-muga / dipiharep (saha/naon)...'.
        - Syara'a/Thafiqa/Akhadza (Syuru'): 'mimiti / ngamimitian (saha/naon)... kana migawe...'.

   * KAIDAH 4: MAKNA HARAF JAR SESUAI SIYAQUL KALAM (ALFIYYAH IBNU MALIK):
     - Huruf Baa' (الباء):
       * Al-Isti'anah (alat/sarana): 'kalawan / ku / nganggo' (contoh: بِالْقَلَمِ -> 'kalawan nganggo kalam').
       * As-Sababiyyah (sebab/karena): 'ku sabab / karana' (contoh: فَبِظُلْمٍ -> 'mangka ku sabab kadzaliman'; بِمَا كَانُوا يَكْذِبُونَ -> 'ku sabab naon perkara anu geus bukti aranjeunna eta ngabohong').
       * Al-Ilshaq (nempel/bertemu): 'kana / dina / caket' (contoh: مَرَرْتُ بِزَيْدٍ -> 'geus ngaliwat kaula caket Ki Zaid').
       * Al-Mushahabah (kebersamaan): 'sarta / kalawan dibarengan ku' (contoh: بِسَلَامٍ -> 'sarta kasalametan').
       * At-Ta'diyah (membuat muta'addi): 'kana' (contoh: ذَهَبَ اللَّهُ بِنُورِهِمْ -> 'geus ngaleungitkeun saha Gusti Allah kana cahaya maranehna').
       * Al-Qasam (sumpah): 'demi' (contoh: بِاللَّهِ -> 'demi Gusti Allah').
       * Az-Zharfiyyah (wadah waktu/tempat): 'dina' (contoh: بِمَكَّةَ -> 'dina kota Makkah').
     - Huruf Min (من):
       * Ibtida'ul Ghayah (awal): 'tina / ti mimiti' (contoh: مِنَ الْمَسْجِدِ -> 'ti mimiti masjid').
       * At-Tab'idh (sebagian): 'sabagian tina / sapalih tina' (contoh: مِمَّا رَزَقْنَاهُمْ -> 'tina sabagian perkara anu geus dirizkikeun ku Kami').
       * Bayanul Jins (penjelas jenis): 'nyatana tina' (contoh: مِنْ ذَهَبٍ -> 'nyatana tina emas').
       * As-Sababiyyah (sebab): 'ku sabab / karana' (contoh: مِمَّا خَطِيئَاتِهِمْ -> 'ku sabab pirang-pirang kasalahan maranehna').
     - Huruf Ila (إلى):
       * Intiha' tempat/waktu: 'nepi ka / nuju ka' (contoh: إِلَى الْمَسْجِدِ -> 'nuju ka masjid').
       * Intiha' orang/Allah SWT: 'ka' (contoh: تُوبُوا إِلَى اللَّهِ -> 'kudu tobat aranjeun ka Gusti Allah').
     - Huruf 'An (عن):
       * Al-Mujawazah (menjauh/melewati): 'tina / ngajauhan tina' (contoh: عَنِ الْبَلَدِ -> 'ngajauhan tina eta nagara').
       * Al-Badal (pengganti): 'minangka ganti tina' (contoh: عَنْ نَفْسٍ -> 'minangka ganti tina jiwa sejen').
       * As-Sababiyyah: 'karana / lantaran' (contoh: عَنْ قَوْلِكَ -> 'karana ucapan anjeun').
     - Huruf 'Ala (على):
       * Al-Isti'la' (di atas): 'tetep di luhureun' (hakiki/maknawi).
       * Al-Wujub (kewajiban): 'wajib ka / tetep kedah ka' (contoh: عَلَى كُلِّ مُسْلِمٍ -> 'wajib ka unggal-unggal jalma islam').
       * As-Sababiyyah: 'ku sabab / karana' (contoh: عَلَى مَا هَدَاكُمْ -> 'ku sabab perkara anu geus dipaparin pituduh').
     - Huruf Fi (في):
       * Az-Zharfiyyah (wadah): 'dina / di jero'.
       * As-Sababiyyah (sebab): 'ku sabab / karana' (contoh: فِي هِرَّةٍ -> 'ku sabab ucing').
     - Huruf Al-Lam (اللام):
       * Al-Milkiyyah: 'milikna' (makhluk) / 'kagungan' (Allah SWT).
       * Al-Ikhtishash / Istihqaq: 'hak tetep kagungan / khusus pikeun' (contoh: اَلْحَمْدُ لِلَّهِ -> 'Ari sakur puji, eta tetep hak kagungan Gusti Allah').
       * At-Ta'lil (tujuan): 'karana / supaya / pikeun' (contoh: لِيَغْفِرَ لَكَ اللَّهُ -> 'supaya ngahampura saha Gusti Allah ka anjeun').
     - Huruf Al-Kaf (الكاف): At-Tasybih: 'saperti / lir ibarat'.
     - Huruf Hatta (حتى): Intiha'ul Ghayah: 'nepi ka / sahingga'.

   * KAIDAH 5: MARJA'UD DHAMIR, ATURAN 'KAULA', 'ANJEUN', & BEDAH MARJA' 'TEH':
     - ATURAN MUTAKALLIM 'KAULA' (ORANG PERTAMA / أَنَا / تُ):
       Kata ganti mutakallim wahdah (orang pertama tunggal, seperti fi'il madhi berakhiran 'ta mutakallim' -tu) WAJIB menggunakan 'kaula' (khas santri pasantren):
       * أَسَّسْتُ (assastu) -> 'nyusun kaula' / 'geus nyusun kaula'
       * قُلْتُ (qultu) -> 'ngucap kaula'
       * عَلِمْتُ ('alimtu) -> 'nyaho kaula'

     - ATURAN MUTLAK 'ANJEUN' (ORANG KEDUA / MUKHATAB):
       Kata 'anjeun' KHUSUS dan HANYA digunakan untuk DHAMIR MUKHATAB (orang kedua / lawan bicara)!
       Contoh:
       * قُلْتَ (qulta) -> 'geus ngadawuh / ngucap anjeun'
       * اعْلَمْ (i'lam) -> 'kudu nyaho anjeun'
       * كُنْتُمْ (kuntum) -> 'geus bukti aranjeun'
       DILARANG KERAS MENGGUNAKAN KATA 'ANJEUN' UNTUK ORANG KETIGA (GHA'IB), APALAGI UNTUK ALLAH SWT!
       Lawan bicara jamak WAJIB 'aranjeun', BUKAN 'aranjeunna' (contoh: احْفَظُوهُ -> 'kudu apal aranjeun kana eta perkara').

     - ATURAN FA'IL & DHAMIR KEPADA ALLAH SWT:
       Jika Fa'il atau Marja' Dhamir adalah ALLAH SWT, CUKUP sebut 'saha Gusti Allah' (JANGAN ditambahi 'Anjeunna' di depannya!).
       Contoh: قَالَ تَعَالَى -> 'Geus ngadawuh saha Gusti Allah Nu Maha Luhur' (DILARANG: 'saha Anjeunna Gusti Allah'!).
       Untuk dhamir muttashil / mudhaf ilaih kembali ke Allah, gunakan '-Na' (contoh: rahmat-Na, hamba-Na, firman-Na).

     - ATURAN DHAMIR KEPADA RASULULLAH SAW / PARA NABI / ULAMA:
       Sebut langsung namanya secara takzim: 'Kanjeng Nabi SAW', 'Rasulullah SAW', 'Mushannif', 'eta Ulama' (atau pronomina takzim: 'Beliau').
       DILARANG KERAS memakai 'manehna' dan DILARANG memakai 'anjeun' (karena anjeun adalah mukhatab).

     - ATURAN DHAMIR KEPADA ISIM / BENDA / PERKARA SEBELUMNYA (BEDAH MARJA' & PARTIKEL 'TEH'):
       Sebutkan kembali nama isim/perkaranya dengan awalan 'ieu...' / 'eta...' dan pertegas topik mubtada dengan partikel 'teh':
       Pola: 'jeung ari ieu/eta [marja'na] teh, eta [khabarna]...'
       * وَهِيَ (kembali ke أَرْبَعَةِ أَرْبَاعٍ) -> 'jeung ari ieu opat bagean teh, eta saparapat pirang-pirang ibadah...' (BUKAN 'jeung ari manehna'!)
       * وَهُوَ (kembali ke الْقَلْبُ) -> 'jeung ari ieu hate teh, eta tempatna ma'rifat'
       * ـهُ (kembali ke kitab ihya karya mushannif) -> 'kana ieu kitab'
       Sebutkan kembali nama isim/perkaranya dengan awalan 'eta...'! JANGAN diartikan 'manehna'!
       * Dhamir kembali ka al-'Ilm -> sebut: 'eta elmu' (BUKAN 'manehna').
       * Dhamir kembali ka al-Qalb -> sebut: 'eta hate' (BUKAN 'manehna').
       * Dhamir kembali ka an-Nafs -> sebut: 'eta nafsu' (BUKAN 'manehna').
       * Dhamir kembali ka al-Amal -> sebut: 'eta amal' (BUKAN 'manehna').
       Contoh: اعْلَمْ أَنَّ الْقَلْبَ... وَهُوَ مَحَلُّ الْمَعْرِفَةِ -> 'Kudu nyaho anjeun saestuna hate... jeung ari ETA HATE teh eta tempatna ma'rifat' (JANGAN: 'jeung ari manehna'!).

     - ATURAN DHAMIR KEPADA MANUSIA / ORANG SECARA UMUM:
       Sebut 'eta jalma' / 'eta manusa'. DILARANG asal memakai 'manehna'.

   * KAIDAH 6: HARF QAD (قَدْ - TAHQIQ vs TAQLEEL):
     - Nalika QAD asup kana FI'IL MADHI (تَحْقِيق / تَقْرِيب): WAJIB dimaknai 'temen-temen...' (sungguh-sungguh geus / bener-bener geus).
       Contoh: قَدْ أَفْلَحَ الْمُؤْمِنُونَ -> 'Temen-temen geus bagja saha jalma-jalma anu ariman'.
       Contoh: قَدْ قَامَتِ الصَّلَاةُ -> 'Temen-temen geus nangtung naon shalat'.
     - Nalika QAD asup kana FI'IL MUDHARI' (تَقْلِيل): WAJIB dimaknai 'terkadang...' (sakapeung / tara-tara / adakalanya).
       Contoh: قَدْ يَنْجَحُ الْكَسْلَانُ -> 'Terkadang hasil/sukses saha jalma anu kedul'.
       Contoh: قَدْ يَجُودُ الْبَخِيلُ -> 'Terkadang béréhan saha jalma anu koret'.

   * KAIDAH 7: HARF AMMA (أَمَّا) & IMMA (إِمَّا):
     1. AMMA (أَمَّا / فَأَمَّا / وَأَمَّا - Harf Syarth, Tafshil & Taukid):
        - WAJIB dimaknai 'anapon...' (kemudian disambung dengan kalimah berikutnya)!
        - DILARANG KERAS MEMAKAI KATA 'adapun' (karena bahasa Indonesia) dan DILARANG melewatkannya!
        - Jika diawali Fa' ('فَأَمَّا'): 'Mangka anapon...' atau 'Anapon...'.
        - Jika diawali Wawu ('وَأَمَّا'): 'Jeung anapon...'.
        - Diikuti isim/mubtada: disambung dengan kalimah berikutnya:
          * أَمَّا بَعْدُ -> 'Anapon saba'da eta...'
          * فَأَمَّا عِلْمُ طَرِيقِ الْآخِرَةِ -> 'Mangka anapon ari elmu jalan ka akherat...'
          * وَأَمَّا الْكَرَاهِيَةُ -> 'Jeung anapon ari makruh...'
          * أَمَّا الزَّاهِدُ فَـ... -> 'Anapon ari jalma nu zahid, mangka...'
        - Kaidah Alfiyyah: أما كمهما يك من شيء وفا # لتلو تلوها وجوبا ألفا (Khabarnya wajib dibarengan ku Fa' rabithah).
     2. IMMA (إِمَّا / وَإِمَّا - Harf Tafshil & Takhyir):
        - WAJIB dimaknai 'boh yen...' (kemudian disambung dengan kalimah berikutnya)!
        - Jika berulang ('إِمَّا ... وَإِمَّا ...'): 'boh yen... jeung boh yen...' (atau 'boh yen... atawa boh yen...').
        - Contoh:
          * إِمَّا أَنْ يَكُونَ حَلَالًا وَإِمَّا أَنْ يَكُونَ حَرَامًا -> 'Boh yen aya itu perkara teh eta halal, jeung boh yen aya itu perkara teh eta haram'.
          * إِمَّا طَاعَةً وَإِمَّا مَعْصِيَةً -> 'Boh yen kana taat, jeung boh yen kana maksiat'.
          * إِمَّا شَاكِرًا وَإِمَّا كَفُورًا -> 'Boh yen dina kaayaan sukuran, jeung boh yen dina kaayaan kufur'.

CONTOH BAKU PENERAPAN NGALOGAT PASANTREN:
Contoh 1 (Mubtada + Khabar Jar-Majrur Syibhul Jumlah):
Teks: اَلْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ
Logat: "Ari sakur puji, eta tetep hak kagungan Gusti Allah, anu ngaping ngajaring sakuliah alam."

Contoh 2 (Inna + Khabar Muqaddam Jar-Majrur + Isim Inna Mu'akhkhar):
Teks: إِنَّ فِي ذَلِكَ لَآيَةً لِلْمُؤْمِنِينَ
Logat: "Saestuna eta tetep dina perkara anu kasebut, aya hiji tanda kakuasaan pikeun jalma-jalma anu ariman."

Contoh 3 (Inna Tanpa 'Ari' + Fa'il Allah Cukup 'saha Gusti Allah'):
Teks: إِنَّ اللَّهَ كَانَ بِعِبَادِهِ خَبِيرًا بَصِيرًا
Logat: "Saestuna Gusti Allah, eta geus bukti saha Gusti Allah, eta Nu Maha Waspada tur Maha Ningali kana tingkah pirang-pirang hamba-Na."

Contoh 4 (Fi'il Madhi + Fa'il Allah Cukup 'saha Gusti Allah'):
Teks: قَالَ تَعَالَى فِي كِتَابِهِ
Logat: "Geus ngadawuh saha Gusti Allah Nu Maha Luhur dina kitab-Na."

Contoh 5 (Dhamir Mukhatab Khusus 'Anjeun'):
Teks: فَإِنْ قُلْتَ كَيْفَ ذَاكَ فَأَقُولُ
Logat: "Mangka lamun ngucap anjeun: 'Kumaha ari eta perkara?', mangka ngucap kaula..."

Contoh 6 (Fi'il Madhi + Fa'il + Maf'ul Bih Objek Hidup):
Teks: رَأَيْتُ زَيْدًا فِي الْمَسْجِدِ
Logat: "Geus ningali kaula ka Ki Zaid di jero masjid."

Contoh 7 (Harf Qad Asup Kana Fi'il Madhi -> 'temen-temen'):
Teks: قَدْ أَفْلَحَ الْمُؤْمِنُونَ
Logat: "Temen-temen geus bagja saha jalma-jalma anu ariman."

Contoh 8 (Harf Qad Asup Kana Fi'il Mudhari' -> 'terkadang'):
Teks: قَدْ يَنْجَحُ الْكَسْلَانُ
Logat: "Terkadang hasil saha jalma anu kedul."

Contoh 9 (Kaada Muqorobah -> 'ampir-ampiran'):
Teks: كَادَ الْفَقْرُ أَنْ يَكُونَ كُفْرًا
Logat: "Ampir-ampiran naon kafakiran, yen aya itu kafakiran teh, eta kufur."

Contoh 10 (Qad + Mutakallim 'kaula' + Jar-Majrur 'eta tetep' + Marja' 'ieu ... teh'):
Teks: وَقَدْ أَسَّسْتُهُ عَلَى أَرْبَعَةِ أَرْبَاعٍ، وَهِيَ: رُبْعُ الْعِبَادَاتِ، وَرُبْعُ الْعَادَاتِ، وَرُبْعُ الْمُهْلِكَاتِ، وَرُبْعُ الْمُنْجِيَاتِ
Logat: "Jeung temen-temen nyusun kaula kana ieu kitab, eta tetep di luhureun opat pirang-pirang bagean. Jeung ari ieu opat bagean teh, eta saparapat pirang-pirang ibadah, jeung saparapat pirang-pirang adat kabiasaan, jeung saparapat pirang-pirang perkara anu ngabinasakeun, jeung saparapat pirang-pirang perkara anu nyalametkeun."

6. 'translation_sunda_logat_pegon':
   Tuliskan teks 'translation_sunda_logat' tersebut secara LENGKAP ke dalam AKSARA ARAB PEGON SUNDA (Jawi Sunda) berharakat rapi.

7. 'translation_sunda_klasik' (KITAB KUNING MAKNA GANDUL / JENGGOT MIRING - INTERLINEAR):
   Array objek interlinear untuk teks Arab yang dipasangkan dengan makna Sunda miring di bawahnya per lafadz (khas kitab kuning santri pasantren Sunda):
   Format tiap objek:
   - "word": lafadz Arab bersyakal
   - "symbol": simbol rumus tarkib ringkas: م (mubtada), خ (khabar), فا (fa'il), نف (naibul fa'il), مف (maf'ul), مض (mudhaf ilaih), ج (harf jar), مج (majrur), ظ (zharaf), ح (hal), تم (tamyiz), ص (shifat/na'at), ب (badal), ع ('athaf), كان (kaana), ان (inna), كاد (kaada), تح (tahqiq/qad), صلة (shilah)
   - "sunda": makna Sunda per kata/frasa ringkas dalam huruf Latin (misal: 'jeung temen-temen', 'nyusun kaula', 'kana ieu kitab')
   - "pegon": makna Sunda per kata/frasa yang SAMA PERSIS dituliskan ke dalam AKSARA ARAB PEGON SUNDA (misal: 'جَوْڠْ تَمَنْ-تَمَنْ', 'ڽُوسُونْ كَاوْلَا', 'كَانَا اِيئوُ كِتَابْ'). WAJIB: BUKAN HANYA SIMBOLNYA, TETAPI SELURUH TERJEMAH SUNDANYA WAJIB IKUT DITULIS DALAM AKSARA ARAB PEGON!
   - "role": nama kedudukan gramatikal (misal: Mubtada', Khabar Syibhul Jumlah)

Jawablah HANYA dalam format JSON valid dengan schema persis seperti ini:
{
  "tashkil": "teks arab bersyakal lengkap",
  "tarkib_notes": [
    {"word": "kata", "position": "kedudukan (misal: Khabar Syibhul Jumlah)", "i_rab": "fi mahalli raf'in", "note": "keterangan singkat kaidah"}
  ],
  "translation_id": "terjemahan bahasa indonesia...",
  "translation_sunda_lemes": "terjemahan basa sunda lemes...",
  "translation_sunda_logat": "logat pasantren sunda yang murni, alami, dan berkaidah nahwu dina aksara latin...",
  "translation_sunda_logat_pegon": "logat pasantren sunda anu ditulis lengkep dina aksara Arab Pegon Sunda...",
  "translation_sunda_klasik": [
    {"word": "lafadz arab", "symbol": "م", "sunda": "makna sunda latin...", "pegon": "makna sunda dina aksara pegon...", "role": "Mubtada'"}
  ]
}
"""

SYSTEM_INSTRUCTION_FAST = """
Anda adalah pakar penerjemah kitab kuning ke dalam Bahasa Indonesia dan Bahasa Sunda (tradisi Ngalogat Pasantren Sunda rujukan Alfiyyah Ibnu Malik).

Tugas Anda (KILAT & AKURAT):
1. 'tashkil': Berikan syakal LENGKAP dan AKURAT sesuai kaidah Nahwu-Shorof. Harakat akhir i'rab wajib jelas.
2. 'translation_id': Terjemahan Bahasa Indonesia yang mengalir. WAJIB kapitalisasi dhamir Allah ('-Nya', 'kepada-Nya', 'rahmat-Nya') dan Nabi Muhammad SAW ('Beliau', 'Nabi-Nya', 'Rasul-Nya').
3. 'translation_sunda_lemes': Terjemahan Basa Sunda Lemes (ragam hormat).
4. 'translation_sunda_logat': Terjemahan Ngalogat Pasantren Sunda murni Basa Sunda dina aksara Latin.
5. 'translation_sunda_logat_pegon': Terjemahan Ngalogat Pasantren Sunda dina aksara Arab Pegon Sunda.
6. 'translation_sunda_klasik': Array interlinear per lafadz (word, symbol, sunda, pegon, role). PENTING: Bidang 'pegon' kedah ngawengku terjemah Sundana dina aksara Arab Pegon (sanes mung saukur simbol tarkibna).

7. 'tarkib_notes': Analisis nahwu-shorof per kata (word, position, shorof, i_rab, symbol, note).
PENTING: Kalimah diawali 'أَمَّا' -> 'anapon...', diawali 'إِمَّا' -> 'boh yen...'.

Hasilkan respon HANYA dalam JSON valid:
{
  "tashkil": "teks arab bersyakal lengkap",
  "tarkib_notes": [
    {"word": "lafadz", "position": "Kedudukan Nahwu", "shorof": "Analisis Shorof & Wazan", "i_rab": "Tanda I'rab", "symbol": "م", "note": "catatan"}
  ],
  "translation_id": "terjemahan bahasa indonesia...",
  "translation_sunda_lemes": "terjemahan basa sunda lemes...",
  "translation_sunda_logat": "logat pasantren sunda dina aksara latin...",
  "translation_sunda_logat_pegon": "logat pasantren sunda dina aksara arab pegon...",
  "translation_sunda_klasik": [
    {"word": "lafadz", "symbol": "م", "sunda": "makna sunda latin...", "pegon": "makna sunda pegon...", "role": "Mubtada'"}
  ]
}
"""

# Kamus Istilah Khusus & Kosakata Baku Ngalogat Pasantren Sunda ka Pegon
PEGON_DICTIONARY = {
    # Partikel Tarkib & Kaidah Nahwu
    "ari": "اَرِ",
    "eta": "ايتَا",
    "tetep": "تَتَڤْ",
    "eta tetep": "ايتَا تَتَڤْ",
    "saha": "سَاهَا",
    "naon": "نَاوُنْ",
    "kana": "كَانَا",
    "ka": "كَا",
    "ku": "كُو",
    "kalawan": "كَلَاوَانْ",
    "dina": "دِينَا",
    "di": "دِي",
    "tina": "تِينَا",
    "ti": "تِي",
    "nepi": "نَڤِي",
    "nepi ka": "نَڤِي كَا",
    "mangka": "مَڠْكَا",
    "geus": "ݢَوْسْ",
    "keur": "كَوْرْ",
    "baris": "بَارِسْ",
    "temen-temen": "تَمَنْ-تَمَنْ",
    "temen": "تَمَنْ",
    "terkadang": "تَرْكَادَاڠْ",
    "ampir-ampiran": "اَمْڤِيرْ-اَمْڤِيرَانْ",
    "ampir": "اَمْڤِيرْ",
    "meh-mehan": "مَيْهْ-مَيْهَانْ",
    "anapon": "اَنَاڤَوْنْ",
    "boh": "بَوْهْ",
    "boh yen": "بَوْهْ يَيْـنْ",
    "yen": "يَينْ",
    "teh": "تَيْهْ",
    "ieu": "اِيئوُ",
    "itu": "اِيتُو",
    "henteu": "هِنْتَوْ",
    "aya": "اَيَا",
    "bukti": "بُوكْتِي",
    "halna": "حَالْنَا",
    "karana": "كَرَانَا",
    "lantaran": "لَنْتَارَانْ",
    "ku sabab": "كُو سَبَبْ",
    "sabab": "سَبَبْ",
    "saestuna": "سَايَسْتُونَـا",
    "saenya-enyana": "سَاايڽَا-ايڽَانَا",
    "sakur": "سَاكُورْ",
    "puji": "ڤُوجِي",
    "gusti": "ݢُوسْتِي",
    "allah": "اَللَّهْ",
    "kabeh": "كَبَيهْ",
    "sadaya": "سَدَايَا",
    
    # Dhamir & Marja'
    "kaula": "كَاوْلَا",
    "kuring": "كُورِڠْ",
    "anjeun": "اَنْجَوْنْ",
    "aranjeun": "اَرَانْجَوْنْ",
    "maraneh": "مَارَانَيهْ",
    "maranehna": "مَارَانَيهْنَا",
    "manehna": "مَانَيهْنَا",
    "jalma": "جَلْمَا",
    "jalma-jalma": "جَلْمَا-جَلْمَا",
    "pirang-pirang": "ڤِيرَاڠْ-ڤِيرَاڠْ",
    "perkara": "ڤَرْكَارَا",
    "anu": "اَنُو",
    "nu": "نُو",
    
    # Kata Kerja & Benda Populer Kitab
    "nyusun": "ڽُوسُونْ",
    "kitab": "كِتَابْ",
    "opat": "اَوْڤَتْ",
    "bagean": "بَاݢَايَانْ",
    "saparapat": "سَاڤَارَاڤَتْ",
    "ibadah": "عِبَادَةْ",
    "adat": "عَادَةْ",
    "kabiasaan": "كَا بِيَاسَاءَانْ",
    "ngabinasakeun": "ڠَابِينَاسَاكَوْنْ",
    "nyalametkeun": "ڽَالَمَتْكَوْنْ",
    "kufur": "كُوفُورْ",
    "kafakiran": "كَافَاكِيرَانْ",
    "hate": "حَاتَي",
    "nafsu": "نَفْسُو",
    "iman": "اِيمَانْ",
    "islam": "اِسْلَامْ",
    "elmu": "عِلْمُو",
    "amal": "عَمَلْ",
    "luhureun": "لُوهُورَوْنْ",
    "handapeun": "هَنْدَاڤَوْنْ",
    "jero": "جَرُو",
    "luar": "لُوَارْ",
    "nyiar": "ڽِيَارْ",
    "maca": "مَاچَا",
    "ngadawuh": "ڠَادَاوُوهْ",
    "ngucap": "ڠُوچَڤْ",
    "nyaho": "ڽَاهُو",
    "ningali": "نِيڠَالِي",
    "nangtung": "نَاڠْتُوڠْ",
    "diuk": "دِيئُوكْ",
    "kudu": "كُودُو",
    "ulah": "اُولَاهْ",
    "supaya": "سُوڤَايَا",
    "sangkan": "سَاڠْكَانْ",
    "bener": "بَنَرْ",
    "salah": "سَالَاهْ",
    "hade": "حَادَي",
    "goreng": "ݢُوِرَيڠْ",
    "bagja": "بَاݢْجَا",
    "cilaka": "چِيلَاكَا",
    "hirup": "هِيرُوڤْ",
    "maot": "مَاوُوتْ",
    "dunya": "دُنْيَا",
    "akherat": "آخِرَةْ",
    "sawarga": "سَاوَرْݢَا",
    "naraka": "نَارَاكَا",
    "pahala": "ڤَاهَالَاء",
    "dosa": "دَوْسَا",
    "wajib": "وَاجِبْ",
    "sunat": "سُنَّةْ",
    "haram": "حَرَامْ",
    "makruh": "مَكْرُوهْ",
    "mubah": "مُبَاحْ",
    "hukumna": "حُكُومْنَا",
    "waktu": "وَكْتُو",
    "solat": "صَلَاةْ",
    "sholat": "صَلَاةْ",
    "puasa": "ڤُوَاسَا",
    "zakat": "زَكَاةْ",
    "haji": "حَجّْ",
    "bapa": "بَاڤَا",
    "indung": "اِينْدُوڠْ",
    "anak": "اَنَاكْ",
    "imah": "اِيمَاهْ",
    "masjid": "مَسْجِدْ"
}

# Phonetic consonants mapping
CONSONANTS = {
    "ng": "ڠ",
    "ny": "ڽ",
    "ch": "چ",
    "kh": "خ",
    "gh": "غ",
    "sy": "ش",
    "sh": "ص",
    "dh": "ض",
    "th": "ط",
    "zh": "ظ",
    "b": "ب",
    "c": "چ",
    "d": "د",
    "f": "ف",
    "g": "ݢ",
    "h": "ه",
    "j": "ج",
    "k": "ك",
    "l": "ل",
    "m": "م",
    "n": "ن",
    "p": "ڤ",
    "q": "ق",
    "r": "ر",
    "s": "س",
    "t": "ت",
    "v": "ڤ",
    "w": "و",
    "y": "ي",
    "z": "ز"
}

def transliterate_word_pegon(w_raw: str) -> str:
    w = w_raw.strip().lower()
    if not w:
        return ""
    
    if w in PEGON_DICTIONARY:
        return PEGON_DICTIONARY[w]
    
    if "-" in w:
        parts = w.split("-")
        return "-".join(transliterate_word_pegon(p) for p in parts)
    
    if w.endswith("na") and len(w) > 3:
        stem = w[:-2]
        if stem in PEGON_DICTIONARY:
            return PEGON_DICTIONARY[stem] + "نَا"
    if w.endswith("keun") and len(w) > 5:
        stem = w[:-4]
        if stem in PEGON_DICTIONARY:
            return PEGON_DICTIONARY[stem] + "كَوْنْ"
    if w.endswith("an") and len(w) > 3:
        stem = w[:-2]
        if stem in PEGON_DICTIONARY:
            return PEGON_DICTIONARY[stem] + "َانْ"
    if w.startswith("ka") and len(w) > 3:
        stem = w[2:]
        if stem in PEGON_DICTIONARY:
            return "كَا" + PEGON_DICTIONARY[stem]
    if w.startswith("di") and len(w) > 3:
        stem = w[2:]
        if stem in PEGON_DICTIONARY:
            return "دِي" + PEGON_DICTIONARY[stem]
    if w.startswith("sa") and len(w) > 3:
        stem = w[2:]
        if stem in PEGON_DICTIONARY:
            return "سَا" + PEGON_DICTIONARY[stem]
            
    res = []
    i = 0
    n = len(w)
    is_start = True
    
    while i < n:
        if i + 1 < n and w[i:i+2] == "eu":
            res.append("اَوْ" if is_start else "َوْ")
            i += 2
            is_start = False
            continue
        elif i + 1 < n and w[i:i+2] == "ai":
            res.append("اَايْ" if is_start else "َايْ")
            i += 2
            is_start = False
            continue
        elif i + 1 < n and w[i:i+2] == "au":
            res.append("اَاوْ" if is_start else "َاوْ")
            i += 2
            is_start = False
            continue
        
        if i + 1 < n and w[i:i+2] in CONSONANTS:
            c = CONSONANTS[w[i:i+2]]
            i += 2
            is_start = False
            if i < n:
                if i + 1 < n and w[i:i+2] == "eu":
                    res.append(c + "َوْ")
                    i += 2
                elif w[i] == 'a':
                    res.append(c + "َا")
                    i += 1
                elif w[i] == 'i':
                    res.append(c + "ِي")
                    i += 1
                elif w[i] == 'u':
                    res.append(c + "ُو")
                    i += 1
                elif w[i] in ['e', 'é']:
                    res.append(c + "َيْ")
                    i += 1
                elif w[i] == 'o':
                    res.append(c + "َاو")
                    i += 1
                else:
                    res.append(c + "ْ")
            else:
                res.append(c + "ْ")
            continue
            
        if w[i] in CONSONANTS:
            c = CONSONANTS[w[i]]
            i += 1
            is_start = False
            if i < n:
                if i + 1 < n and w[i:i+2] == "eu":
                    res.append(c + "َوْ")
                    i += 2
                elif w[i] == 'a':
                    res.append(c + "َا")
                    i += 1
                elif w[i] == 'i':
                    res.append(c + "ِي")
                    i += 1
                elif w[i] == 'u':
                    res.append(c + "ُو")
                    i += 1
                elif w[i] in ['e', 'é']:
                    res.append(c + "َيْ")
                    i += 1
                elif w[i] == 'o':
                    res.append(c + "َاو")
                    i += 1
                else:
                    res.append(c + "ْ")
            else:
                res.append(c + "ْ")
            continue
            
        if w[i] == 'a':
            res.append("اَ" if is_start else "َا")
        elif w[i] == 'i':
            res.append("اِي" if is_start else "ِي")
        elif w[i] == 'u':
            res.append("اُو" if is_start else "ُو")
        elif w[i] in ['e', 'é']:
            res.append("اَيْ" if is_start else "َيْ")
        elif w[i] == 'o':
            res.append("اَوْ" if is_start else "َاو")
        else:
            res.append(w[i])
        i += 1
        is_start = False

    return "".join(res)

def sunda_to_pegon_full(text: str) -> str:
    if not text:
        return ""
    tokens = re.findall(r'[\w\-]+|[^\w\s]|\s+', text, re.UNICODE)
    out = []
    for tok in tokens:
        if tok.isspace():
            out.append(tok)
        elif re.match(r'^[^\w\s]+$', tok):
            if tok == ',':
                out.append('،')
            elif tok == '?':
                out.append('؟')
            elif tok == ';':
                out.append('؛')
            else:
                out.append(tok)
        else:
            out.append(transliterate_word_pegon(tok))
    return "".join(out)

# Backward-compatibility alias
sunda_to_pegon = sunda_to_pegon_full

def is_arabic_script(s: str) -> bool:
    if not s:
        return False
    return any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' or '\u08A0' <= c <= '\u08FF' for c in s)

def ensure_sunda_klasik_tokens(tashkil: str, sunda_logat: str, tarkib_notes: list, parsed_tokens: list = None) -> list:
    if parsed_tokens and isinstance(parsed_tokens, list) and len(parsed_tokens) > 0:
        cleaned = []
        for t in parsed_tokens:
            if isinstance(t, dict) and t.get("word"):
                sunda = t.get("sunda", "")
                w_norm = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', t.get("word", "")).strip()
                role = t.get("role", "")
                sym = t.get("symbol", "-")
                if 'adapun' in sunda.lower():
                    sunda = re.sub(r'\badapun\b', 'anapon', sunda, flags=re.IGNORECASE)
                if w_norm == 'أما':
                    sunda = "anapon"
                    role = "Harf Syarth wa Tafshil"
                    sym = "تف"
                elif w_norm.startswith('أما ') or w_norm.startswith('أما_'):
                    sunda = "anapon " + re.sub(r'^(adapun|anapon)\s*', '', sunda, flags=re.IGNORECASE).strip()
                    role = "Harf Syarth wa Tafshil"
                    sym = "تف"
                elif w_norm == 'فأما':
                    sunda = "mangka anapon"
                    role = "Harf Syarth wa Tafshil"
                    sym = "تف"
                elif w_norm == 'وأما':
                    sunda = "jeung anapon"
                    role = "Harf Syarth wa Tafshil"
                    sym = "تف"
                elif w_norm == 'إما':
                    sunda = "boh yen"
                    role = "Harf Tafshil"
                    sym = "تف"
                elif w_norm.startswith('إما ') or w_norm.startswith('إما_'):
                    sunda = "boh yen " + re.sub(r'^(boh yen)\s*', '', sunda, flags=re.IGNORECASE).strip()
                    role = "Harf Tafshil"
                    sym = "تف"
                elif w_norm == 'وإما':
                    sunda = "jeung boh yen"
                    role = "Harf Tafshil"
                    sym = "تف"
                pegon = t.get("pegon")
                if not pegon or not is_arabic_script(pegon) or any(k in w_norm for k in ['أما', 'إما']) or 'adapun' in str(t.get("sunda", "")).lower():
                    pegon = sunda_to_pegon_full(sunda)
                cleaned.append({
                    "word": t.get("word", ""),
                    "symbol": sym,
                    "sunda": sunda,
                    "pegon": pegon,
                    "role": role
                })
        if cleaned:
            return cleaned

    ar_words = [w for w in re.split(r'[\s،.؛:!]+', tashkil) if w.strip()]
    if not ar_words:
        return []

    note_map = {}
    if tarkib_notes:
        for n in tarkib_notes:
            w_norm = re.sub(r'[\u064B-\u065F\u0670]', '', n.get("word", "")).strip()
            if w_norm:
                note_map[w_norm] = n

    result = []
    for w in ar_words:
        w_norm = re.sub(r'[\u064B-\u065F\u0670]', '', w).strip()
        matched_note = note_map.get(w_norm)
        symbol = "-"
        role = ""
        sunda = ""
        if w_norm == 'أما':
            symbol = "تف"
            role = "Harf Syarth wa Tafshil"
            sunda = "anapon"
        elif w_norm == 'فأما':
            symbol = "تف"
            role = "Harf Syarth wa Tafshil"
            sunda = "mangka anapon"
        elif w_norm == 'وأما':
            symbol = "تف"
            role = "Harf Syarth wa Tafshil"
            sunda = "jeung anapon"
        elif w_norm == 'إما':
            symbol = "تف"
            role = "Harf Tafshil"
            sunda = "boh yen"
        elif w_norm == 'وإما':
            symbol = "تف"
            role = "Harf Tafshil"
            sunda = "jeung boh yen"
        elif matched_note:
            pos = matched_note.get("position", "")
            role = pos
            pos_lower = pos.lower()
            if "mubtada" in pos_lower:
                symbol = "م"
                sunda = f"ari {w_norm}"
            elif "khabar" in pos_lower:
                symbol = "خ"
                sunda = f"eta {w_norm}"
            elif "fa'il" in pos_lower or "fail" in pos_lower:
                symbol = "فا"
                sunda = "saha / naon"
            elif "maf'ul" in pos_lower:
                symbol = "مف"
                sunda = "kana"
            elif "hal" in pos_lower:
                symbol = "ح"
                sunda = "halna"
            elif "jar" in pos_lower or "majrur" in pos_lower:
                symbol = "ج"
                sunda = "tetep dina"
            elif "mudhaf" in pos_lower:
                symbol = "مض"
            elif "athaf" in pos_lower:
                symbol = "ع"
                sunda = "jeung"
        else:
            if w.startswith("وَ") or w.startswith("و"):
                symbol = "ع"
                role = "'Athaf"
                sunda = "jeung"
            elif w.startswith("فَ") or w.startswith("ف"):
                symbol = "ف"
                role = "Rabitah/Sababiyyah"
                sunda = "mangka"

        result.append({
            "word": w,
            "symbol": symbol,
            "sunda": sunda,
            "pegon": sunda_to_pegon_full(sunda),
            "role": role
        })

    return result

def ensure_comprehensive_nahwu_shorof_analysis(tashkil: str, sunda_logat: str = "", tarkib_notes: list = None, klasik_tokens: list = None) -> list:
    words = [w for w in re.split(r'[\s،.؛:!]+', tashkil) if w.strip()]
    if not words and klasik_tokens:
        words = [t['word'] for t in klasik_tokens if isinstance(t, dict) and t.get('word')]
    if not words:
        return []

    klasik_map = {}
    if klasik_tokens:
        for t in klasik_tokens:
            if isinstance(t, dict) and t.get('word'):
                k_clean = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', t['word']).strip()
                klasik_map[k_clean] = t
                klasik_map[t['word'].strip()] = t

    notes_map = {}
    if tarkib_notes:
        for n in tarkib_notes:
            if isinstance(n, dict) and n.get('word'):
                n_clean = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', n['word']).strip()
                notes_map[n_clean] = n
                notes_map[n['word'].strip()] = n
            elif isinstance(n, str):
                m = re.search(r"['\"\(]([\u0600-\u06FF]+)['\"\) ]", n)
                if m:
                    w = m.group(1)
                    w_c = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', w).strip()
                    notes_map[w_c] = {'word': w, 'note': n, 'position': 'Nahwu', 'i_rab': "Mu'rab"}

    results = []

    HARF_JAR = {'من', 'إلى', 'عن', 'على', 'في', 'رب', 'حتى', 'مذ', 'منذ'}
    HARF_ATHAF = {'ثم', 'أو', 'أم', 'بل', 'لكن'}
    ROOT_TA_WORDS = {'نبات', 'فرات', 'أموات', 'أصوات', 'أبيات', 'قوت', 'وقت', 'موت', 'ثبات', 'فتات'}

    for idx, w_tashkil in enumerate(words):
        w_clean = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', w_tashkil).strip()
        matched_kl = klasik_map.get(w_clean) or klasik_map.get(w_tashkil)
        matched_nt = notes_map.get(w_clean) or notes_map.get(w_tashkil)

        if not matched_kl:
            for k, val in klasik_map.items():
                if w_clean in k or k in w_clean:
                    matched_kl = val
                    break
        if not matched_nt:
            for k, val in notes_map.items():
                if w_clean in k or k in w_clean:
                    matched_nt = val
                    break

        position = ''
        i_rab = ''
        shorof = ''
        symbol = '-'
        sunda = ''
        note = ''

        if matched_kl:
            symbol = matched_kl.get('symbol') or '-'
            sunda = matched_kl.get('sunda') or ''
            position = matched_kl.get('role') or ''

        if matched_nt:
            if isinstance(matched_nt, dict):
                position = matched_nt.get('position') or position
                i_rab = matched_nt.get('i_rab') or i_rab
                note = matched_nt.get('note') or note
                shorof = matched_nt.get('shorof') or shorof
            elif isinstance(matched_nt, str):
                note = matched_nt

        # Determine Shorof
        if w_clean in HARF_JAR or w_tashkil in ['مِنْ', 'مِنَ', 'إِلَى', 'عَنْ', 'عَلَى', 'فِي']:
            shorof = 'حَرْفُ جَرٍّ (مَبْنِيٌّ عَلَى السُّكُونِ / الْفَتْحِ)'
            if not position: position = 'Harf Jar'
            if not symbol or symbol == '-': symbol = 'ج'
            if not i_rab: i_rab = "Mabni, laa mahalla lahu minal i'rab"
        elif w_clean == 'إنما' or w_tashkil == 'إِنَّمَا':
            shorof = 'أَدَاةُ حَصْرٍ (كَافَّةٌ وَمَكْفُوفَةٌ)'
            if not position: position = 'Adat Hasyr / Qashr'
            if not symbol or symbol == '-': symbol = 'حصر'
            if not i_rab: i_rab = 'Kaffat wa makfufah, batil amalnya'
        elif w_clean in ['إن', 'أن'] or w_tashkil in ['إِنَّ', 'أَنَّ']:
            shorof = 'حَرْفُ تَوْكِيدٍ وَنَصْبٍ (مِنَ النَّوَاسِخِ)'
            if not position: position = 'Amil Nawasikh (Inna)'
            if not symbol or symbol == '-': symbol = 'إن'
            if not i_rab: i_rab = "Mabni 'alal fathi"
        elif w_clean == 'أما' or w_tashkil in ['أَمَّا', 'فَأَمَّا', 'وَأَمَّا'] or w_clean in ['فأما', 'وأما']:
            shorof = 'حَرْفُ شَرْطٍ وَتَفْصِيلٍ وَتَوْكِيدٍ (مَبْنِيٌّ عَلَى السُّكُونِ)'
            if not position: position = 'Harf Syarth wa Tafshil (Amma)'
            if not symbol or symbol == '-': symbol = 'تف'
            if not i_rab: i_rab = "Mabni 'alas-sukun, laa mahalla lahu minal i'rab"
            if not sunda:
                if w_clean.startswith('ف'): sunda = "mangka anapon"
                elif w_clean.startswith('و'): sunda = "jeung anapon"
                else: sunda = "anapon"
            if not note:
                note = "Harf Syarth & Tafshil; wajib dimaknai 'anapon' dina logat Sunda, jawabna wajib dibarengan ku Fa' rabithah."
        elif w_clean == 'إما' or w_tashkil in ['إِمَّا', 'وَإِمَّا'] or w_clean in ['وإما']:
            shorof = 'حَرْفُ تَفْصِيلٍ وَتَخْيِيرٍ (مَبْنِيٌّ عَلَى السُّكُونِ)'
            if not position: position = 'Harf Tafshil wa Takhyir (Imma)'
            if not symbol or symbol == '-': symbol = 'تف'
            if not i_rab: i_rab = "Mabni 'alas-sukun, laa mahalla lahu minal i'rab"
            if not sunda:
                if w_clean.startswith('و'): sunda = "jeung boh yen"
                else: sunda = "boh yen"
            if not note:
                note = "Harf Tafshil & Takhyir; wajib dimaknai 'boh yen' dina logat Sunda pasantren."
        elif w_clean == 'قد' or w_tashkil == 'قَدْ':
            shorof = 'حَرْفُ تَحْقِيقٍ'
            if not position: position = 'Harf Tahqiq'
            if not symbol or symbol == '-': symbol = 'تح'
            if not i_rab: i_rab = "Mabni 'alas sukun"
        elif w_clean in HARF_ATHAF or w_tashkil in ['ثُمَّ', 'أَوْ', 'بَلْ']:
            shorof = 'حَرْفُ عَطْفٍ (مَبْنِيٌّ)'
            if not position: position = "Harf 'Athaf"
            if not symbol or symbol == '-': symbol = 'ع'
            if not i_rab: i_rab = "Mabni 'alal fathi"
        elif w_clean in ['به', 'له', 'فيه', 'عليه', 'منه', 'عنه', 'بها', 'لها', 'فيها', 'عليها', 'منها', 'عنها']:
            shorof = 'مُرَكَّبٌ مِنْ حَرْفِ جَرٍّ وَضَمِيرٍ مُتَّصِلٍ'
            if not position: position = 'Jar wa Majrur (Syibhul Jumlah)'
            if not symbol or symbol == '-': symbol = 'ج مج'
            if not i_rab: i_rab = "Fi mahalli jarrin / Muta'alliq"
        elif w_clean in ['هو', 'هي', 'هم', 'أنت', 'أنا', 'نحن']:
            shorof = 'ضَمِيرٌ مُنْفَصِلٌ مَبْنِيٌّ'
            if not position: position = "Mubtada' (Dhamir)"
            if not symbol or symbol == '-': symbol = 'م'
            if not i_rab: i_rab = "Fi mahalli raf'in"
        elif w_clean in ['الذي', 'التي', 'الذين', 'اللاتي', 'اللائي']:
            shorof = 'اسْمٌ مَوْصُولٌ مَبْنِيٌّ'
            if not position: position = "Isim Maushul"
            if not symbol or symbol == '-': symbol = 'صلة'
            if not i_rab: i_rab = "Fi mahalli raf'in / nasbin / jarrin"

        # Fi'il detection
        if not shorof:
            stem = w_clean
            if (stem.startswith('و') or stem.startswith('ف')) and len(stem) > 3 and not stem.startswith('وال'):
                stem = stem[1:]

            if stem.startswith('أنزل') or stem.startswith('أخرج') or stem.startswith('أسس') or stem.startswith('أعان') or stem.startswith('أكرم') or stem.startswith('أرسل'):
                shorof = 'فِعْلٌ مَاضٍ، بَابُ أَفْعَلَ يُفْعِلُ (مَزِيدٌ بِهَمْزَةٍ)'
                if not position: position = "Fi'il Madhi"
                if not symbol or symbol == '-': symbol = 'ع فعل' if w_clean.startswith('و') or w_clean.startswith('ف') else 'فعل'
                if not i_rab: i_rab = "Mabni 'alal fathi"
            elif stem in ['كان', 'صار', 'ليس', 'أصبح', 'مازال', 'مادام']:
                shorof = 'فِعْلٌ مَاضٍ نَاقِصٌ (يَرْفَعُ الِاسْمَ وَيَنْصِبُ الْخَبَرَ)'
                if not position: position = "Fi'il Madhi Naqish (Kaana)"
                if not symbol or symbol == '-': symbol = 'كان'
                if not i_rab: i_rab = "Mabni 'alal fathi"
            elif stem.startswith('يشتمل') or stem.startswith('يجتمع') or stem.startswith('يختلف'):
                shorof = 'فِعْلٌ مُضَارِعٌ، بَابُ افْتَعَلَ يَفْتَعِلُ'
                if not position: position = "Fi'il Mudhari'"
                if not symbol or symbol == '-': symbol = 'فعل'
                if not i_rab: i_rab = "Marfu' bi adh-dhammah azh-zhahirah"
            elif stem.startswith('يتحير') or stem.startswith('يتقرب') or stem.startswith('يتعلم'):
                shorof = 'فِعْلٌ مُضَارِعٌ، بَابُ تَفَعَّلَ يَتَفَعَّلُ'
                if not position: position = "Fi'il Mudhari'"
                if not symbol or symbol == '-': symbol = 'فعل'
                if not i_rab: i_rab = "Marfu' bi adh-dhammah azh-zhahirah"
            elif stem.startswith('يستوعب') or stem.startswith('يستخدم') or stem.startswith('يستغفر'):
                shorof = 'فِعْلٌ مُضَارِعٌ، بَابُ اسْتَفْعَلَ يَسْتَفْعِلُ'
                if not position: position = "Fi'il Mudhari'"
                if not symbol or symbol == '-': symbol = 'فعل'
                if not i_rab: i_rab = "Marfu' bi adh-dhammah azh-zhahirah"
            elif stem in ['يكون', 'تكون', 'نكون', 'أكون']:
                shorof = 'فِعْلٌ مُضَارِعٌ نَاقِصٌ، أَصْلُهُ كَانَ'
                if not position: position = "Fi'il Mudhari' Naqish"
                if not symbol or symbol == '-': symbol = 'فعل'
                if not i_rab: i_rab = "Marfu' bi adh-dhammah azh-zhahirah"
            elif (stem.startswith('ي') or stem.startswith('ت') or stem.startswith('ن')) and len(stem) >= 3 and not stem.startswith('تع'):
                if w_tashkil.endswith('ُ') or w_tashkil.endswith('ُونَ'):
                    shorof = 'فِعْلٌ مُضَارِعٌ ثُلَاثِيٌّ مُجَرَّدٌ'
                    if not position: position = "Fi'il Mudhari'"
                    if not symbol or symbol == '-': symbol = 'فعل'
                    if not i_rab: i_rab = "Marfu' bi adh-dhammah azh-zhahirah"

        # Specific Nouns & Adjectives
        if not shorof:
            stem_isim = w_clean[2:] if w_clean.startswith('ال') else w_clean
            if w_clean.startswith('وال'): stem_isim = w_clean[3:]

            if stem_isim in ROOT_TA_WORDS:
                if stem_isim == 'نبات':
                    shorof = 'مَصْدَرٌ / اسْمُ مَعْنًى (وَزْنُ فَعَال)'
                elif stem_isim == 'فرات':
                    shorof = 'صِفَةٌ مُشَبَّهَةٌ (وَزْنُ فُعَال)'
                else:
                    shorof = 'اسْمٌ ثُلَاثِيٌّ'
            elif (w_clean.endswith('ات') or w_tashkil.endswith('َاتِ') or w_tashkil.endswith('َاتُ')) and stem_isim not in ROOT_TA_WORDS:
                shorof = 'جَمْعُ مُؤَنَّثٍ سَالِمٌ (مُفْرَدُهُ بِالتَّاءِ)'
            elif w_clean.endswith('ون') or w_clean.endswith('ين'):
                shorof = 'جَمْعُ مُذَكَّرٍ سَالِمٌ'
            elif stem_isim.startswith('مستوعب') or stem_isim.startswith('مستفعل'):
                shorof = 'اسْمُ مَفْعُولٍ، بَابُ اسْتَفْعَلَ'
            elif stem_isim.startswith('متقرب') or stem_isim.startswith('متجرد'):
                shorof = 'اسْمُ فَاعِلٍ، بَابُ تَفَعَّلَ'
            elif stem_isim.startswith('محجوب') or stem_isim.startswith('معلوم'):
                shorof = 'اسْمُ مَفْعُولٍ ثُلَاثِيٌّ مُجَرَّدٌ (وَزْنُ مَفْعُول)'
            elif stem_isim.startswith('تفصيل') or stem_isim.startswith('تعليم'):
                shorof = 'مَصْدَرٌ، بَابُ فَعَّلَ يُفَعِّلُ (وَزْنُ تَفْعِيل)'
            elif stem_isim.startswith('إدراك') or stem_isim.startswith('إنكار'):
                shorof = 'مَصْدَرٌ، بَابُ أَفْعَلَ يُفْعِلُ (وَزْنُ إِفْعَال)'
            elif stem_isim in ['علم', 'عمل', 'طلب', 'حب']:
                shorof = 'مَصْدَرٌ ثُلَاثِيٌّ مُجَرَّدٌ'
            elif stem_isim in ['فريضة', 'عظيم', 'كريم', 'جليل']:
                shorof = 'صِفَةٌ مُشَبَّهَةٌ (وَزْنُ فَعِيلَة)'
            elif w_clean.startswith('ال') and len(w_clean) > 4:
                shorof = 'اسْمٌ مَعْرِفَةٌ (مُحَلًّى بِـ أَلْ)'
            else:
                shorof = 'اسْمٌ ثُلَاثِيٌّ / جَامِدٌ'

        # Position inference if still missing
        if not position:
            if w_clean.startswith('وال') or (w_clean.startswith('و') and idx > 0):
                position = "Ma'thuf ('Athaf)"
                if not symbol or symbol == '-': symbol = 'ع'
            elif idx == 0 and (w_tashkil.endswith('ُ') or w_tashkil.endswith('ٌ')):
                position = "Mubtada'"
                if not symbol or symbol == '-': symbol = 'م'
            elif w_tashkil.endswith('ُ') or w_tashkil.endswith('ٌ'):
                position = "Khabar / Fa'il"
                if not symbol or symbol == '-': symbol = 'خ'
            elif w_tashkil.endswith('َ') or w_tashkil.endswith('ً'):
                position = "Maf'ul Bih"
                if not symbol or symbol == '-': symbol = 'مف'
            elif w_tashkil.endswith('ِ') or w_tashkil.endswith('ٍ'):
                position = "Mudhaf Ilaih / Majrur"
                if not symbol or symbol == '-': symbol = 'مض'
            else:
                position = "Isim Mu'rab"

        # I'rab inference if still missing
        if not i_rab:
            if w_tashkil.endswith('ُ') or w_tashkil.endswith('ٌ'):
                i_rab = "Marfu'un bi adh-dhammah azh-zhahirah"
            elif w_tashkil.endswith('َ') or w_tashkil.endswith('ً'):
                i_rab = "Manshubun bil-fathah azh-zhahirah"
            elif w_tashkil.endswith('ِ') or w_tashkil.endswith('ٍ'):
                i_rab = "Majrurun bil-kasrah azh-zhahirah"
            elif w_tashkil.endswith('ْ'):
                i_rab = "Mabni 'alas-sukun"
            elif w_clean.endswith('ون'):
                i_rab = "Marfu'un bil-wawu liannahu jam'u mudzakkar salim"
            elif w_clean.endswith('ين'):
                i_rab = "Manshub / Majrur bil-yaa' liannahu jam'u mudzakkar salim"
            else:
                i_rab = "Mu'rab / Mabni"

        if not note:
            if sunda:
                note = f"Logat Sunda: '{sunda}' (Kedudukan: {position})"
            else:
                note = f"Kedudukan nahwu: {position}. Harakat akhir: {i_rab}."

        results.append({
            'word': w_tashkil,
            'position': position,
            'shorof': shorof,
            'i_rab': i_rab,
            'symbol': symbol,
            'sunda': sunda,
            'note': note
        })

    return results

SAMPLE_PRESETS = {
    "sample_1": {
        "text": "طلب العلم فريضة على كل مسلم",
        "tashkil": "طَلَبُ الْعِلْمِ فَرِيْضَةٌ عَلَى كُلِّ مُسْلِمٍ",
        "tarkib_notes": [
            {"word": "طَلَبُ", "position": "Mubtada'", "i_rab": "Marfu' bil-dhammah", "note": "Mudhaf ka lafadz al-'ilmi"},
            {"word": "الْعِلْمِ", "position": "Mudhaf Ilaih", "i_rab": "Majrur bil-kasrah", "note": "Kata benda kedua dari idhafah"},
            {"word": "فَرِيْضَةٌ", "position": "Khabar Mubtada'", "i_rab": "Marfu' bit-tanwin", "note": "Penyempurna makna mubtada'"},
            {"word": "عَلَى كُلِّ", "position": "Jar wa Majrur", "i_rab": "Muta'alliq", "note": "Terkait ka lafadz fariidhatun"}
        ],
        "translation_id": "Menuntut ilmu itu adalah kewajiban bagi setiap orang muslim.",
        "translation_sunda_lemes": "Nyiar elmu teh mangrupikeun hiji kawajiban kanggo sakumna jalmi muslim.",
        "translation_sunda_logat": "Ari nyiar elmu, eta wajib hukumna, tetep ka unggal-unggal jalma islam.",
        "translation_sunda_klasik": [
            {"word": "طَلَبُ", "symbol": "م", "sunda": "ari nyiar", "pegon": "اَرِ ڽِيَارْ", "role": "Mubtada'"},
            {"word": "الْعِلْمِ", "symbol": "مض", "sunda": "kana elmu", "pegon": "كَانَا عِلْمُو", "role": "Mudhaf Ilaih"},
            {"word": "فَرِيْضَةٌ", "symbol": "خ", "sunda": "eta wajib hukumna", "pegon": "ايتَا وَاجِبْ حُكُومْنَا", "role": "Khabar"},
            {"word": "عَلَى", "symbol": "ج", "sunda": "tetep ka", "pegon": "تَتَڤْ كَا", "role": "Harf Jar"},
            {"word": "كُلِّ", "symbol": "مج", "sunda": "unggal-unggal", "pegon": "اوڠْݢَلْ-اوڠْݢَلْ", "role": "Majrur"},
            {"word": "مُسْلِمٍ", "symbol": "مض", "sunda": "jalma islam", "pegon": "جَلْمَا اِسْلَامْ", "role": "Mudhaf Ilaih"}
        ]
    },
    "sample_2": {
        "text": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى",
        "tashkil": "إِنَّمَا الْأَعْمَالُ بِالنِّيَّاتِ وَإِنَّمَا لِكُلِّ امْرِئٍ مَا نَوَى",
        "tarkib_notes": [
            {"word": "إِنَّمَا", "position": "Adat Hasyr (Qashr)", "i_rab": "Inna kaffat wa makfufah", "note": "Ngabatalkeun amal inna pikeun ngawates"},
            {"word": "الْأَعْمَالُ", "position": "Mubtada'", "i_rab": "Marfu' bil-dhammah", "note": "Jamak taksir tina 'amalun"},
            {"word": "بِالنِّيَّاتِ", "position": "Jar-Majrur Syibhul Jumlah", "i_rab": "Fi mahalli raf'in khabar", "note": "Khabar pikeun al-a'malu"},
            {"word": "مَا نَوَى", "position": "Mubtada' Mu'akhkhar", "i_rab": "Isim maushul mabni", "note": "Dina mahal rafa'"}
        ],
        "translation_id": "Sesungguhnya setiap amal perbuatan itu tergantung pada niatnya, dan sesungguhnya setiap orang akan mendapatkan sesuai dengan apa yang ia niatkan.",
        "translation_sunda_lemes": "Saestuna sakur amal perbuatan eta kumargi niatna, sareng saestuna unggal-unggal jalmi baris kenging naon anu diniatkeunana.",
        "translation_sunda_logat": "Anging pastina sakabeh pirang-pirang amal, eta tetep kalawan pirang-pirang niat. Jeung saestuna eta tetep pikeun unggal-unggal jalma, aya naon perkara anu geus niyat eta jalma.",
        "translation_sunda_klasik": [
            {"word": "إِنَّمَا", "symbol": "حصر", "sunda": "anging pastina", "pegon": "اَڠِيڠْ ڤَسْتِينَا", "role": "Adat Hasyr"},
            {"word": "الْأَعْمَالُ", "symbol": "م", "sunda": "ari sakabeh amal", "pegon": "اَرِ سَكَابَيهْ عَمَلْ", "role": "Mubtada'"},
            {"word": "بِالنِّيَّاتِ", "symbol": "خ", "sunda": "eta tetep kalawan niat", "pegon": "ايتَا تَتَڤْ كَلَاوَنْ نِيَّتْ", "role": "Khabar Syibhul Jumlah"},
            {"word": "وَإِنَّمَا", "symbol": "ع", "sunda": "jeung anging pastina", "pegon": "جَوْڠْ اَڠِيڠْ ڤَسْتِينَا", "role": "'Athaf"},
            {"word": "لِكُلِّ", "symbol": "خ مقدم", "sunda": "eta tetep pikeun unggal-unggal", "pegon": "ايتَا تَتَڤْ ڤِيكَوْنْ اوڠْݢَلْ", "role": "Khabar Muqaddam"},
            {"word": "امْرِئٍ", "symbol": "مض", "sunda": "jalma", "pegon": "جَلْمَا", "role": "Mudhaf Ilaih"},
            {"word": "مَا", "symbol": "م مؤخر", "sunda": "aya perkara", "pegon": "اَيَا ڤَرْكَارَا", "role": "Mubtada' Mu'akhkhar"},
            {"word": "نَوَى", "symbol": "صلة", "sunda": "anu geus niyat eta jalma", "pegon": "اَنُو ݢَوْسْ نِيَّتْ ايتَا جَلْمَا", "role": "Shilah"}
        ]
    },
    "sample_3": {
        "text": "العلم بلا عمل جنون والعمل بغير علم لا يكون",
        "tashkil": "اَلْعِلْمُ بِلَا عَمَلٍ جُنُوْنٌ وَالْعَمَلُ بِغَيْرِ عِلْمٍ لَا يَكُوْنُ",
        "tarkib_notes": [
            {"word": "اَلْعِلْمُ", "position": "Mubtada'", "i_rab": "Marfu' bil-dhammah", "note": "Isim ma'rifat di awal kalimah"},
            {"word": "بِلَا عَمَلٍ", "position": "Jar-Majrur", "i_rab": "Baa harf jar, laa nafy, 'amal majrur", "note": "Kayaan/Hal"},
            {"word": "جُنُوْنٌ", "position": "Khabar", "i_rab": "Marfu' bid-dhammah", "note": "Penyempurna kabar mubtada'"},
            {"word": "وَالْعَمَلُ", "position": "Ma'thuf / Mubtada' kadua", "i_rab": "Marfu'", "note": "Kalimah anyar diawalan wawu 'athaf"}
        ],
        "translation_id": "Ilmu tanpa amal adalah kegilaan, dan amal tanpa ilmu tidak akan pernah terwujud (sia-sia).",
        "translation_sunda_lemes": "Elmu anu henteu dibarengan ku amal eta kageloan (kabodoan), sedengkeun amal anu henteu nganggo elmu eta moal jadi nanaon (teu sah).",
        "translation_sunda_logat": "Ari elmu, halna henteu dibarengan ku amal, eta kageloan. Jeung ari amal, halna henteu make elmu, eta henteu bukti ayana (henteu sah/sampurna).",
        "translation_sunda_klasik": [
            {"word": "اَلْعِلْمُ", "symbol": "م", "sunda": "ari elmu", "pegon": "اَرِ عِلْمُو", "role": "Mubtada'"},
            {"word": "بِلَا عَمَلٍ", "symbol": "ح", "sunda": "halna henteu make amal", "pegon": "حَالْنَا هِنْتَوْ مَكَي عَمَلْ", "role": "Hal"},
            {"word": "جُنُوْنٌ", "symbol": "خ", "sunda": "eta kageloan", "pegon": "ايتَا كَاݢَيلُوئَانْ", "role": "Khabar"},
            {"word": "وَالْعَمَلُ", "symbol": "ع م", "sunda": "jeung ari amal", "pegon": "جَوْڠْ اَرِ عَمَلْ", "role": "Mubtada'"},
            {"word": "بِغَيْرِ عِلْمٍ", "symbol": "ح", "sunda": "halna henteu dibarengan elmu", "pegon": "حَالْنَا هِنْتَوْ دِيبَارَيڠَانْ عِلْمُو", "role": "Hal"},
            {"word": "لَا يَكُوْنُ", "symbol": "خ", "sunda": "eta henteu bukti ayana", "pegon": "ايتَا هِنْتَوْ بُوكْتِي اَيَانَا", "role": "Khabar"}
        ]
    },
    "sample_4": {
        "text": "قال تعالى يرفع الله الذين آمنوا منكم",
        "tashkil": "قَالَ تَعَالَى: يَرْفَعِ اللَّهُ الَّذِينَ آمَنُوا مِنكُمْ",
        "tarkib_notes": [
            {"word": "قَالَ", "position": "Fi'il Madhi", "i_rab": "Mabni 'alal fathi", "note": "Pagawean anu geus kaliwat"},
            {"word": "تَعَالَى", "position": "Jumlatun I'tiradhiyyah / Hal", "i_rab": "Fi'il madhi mabni", "note": "Bari Maha Luhur Gusti Allah"},
            {"word": "يَرْفَعِ", "position": "Fi'il Mudhari'", "i_rab": "Marfu' kasrah 'aridhah", "note": "Dikasrahkeun karana panggih dua sukun"},
            {"word": "اللَّهُ", "position": "Fa'il (Lafdzul Jalalah)", "i_rab": "Marfu' bid-dhammah", "note": "Cukup dimaknai 'saha Gusti Allah' tanpa 'anjeunna'"},
            {"word": "الَّذِينَ آمَنُوا", "position": "Maf'ul Bih (Makhluk Hirup)", "i_rab": "Isim maushul mabni", "note": "Maf'ul makhluk hirup nganggo awalan 'ka'"}
        ],
        "translation_id": "Allah Ta'ala berfirman: 'Allah akan meninggikan orang-orang yang beriman di antara kamu.'",
        "translation_sunda_lemes": "Gusti Allah Nu Maha Luhur parantos ngadawuh: 'Gusti Allah baris ngangkat darajat jalmi-jalmi anu ariman ti antawis anjeun sadaya.'",
        "translation_sunda_logat": "Geus ngadawuh saha Gusti Allah Nu Maha Luhur: Baris ngangkat saha Gusti Allah ka jalma-jalma anu ariman ti maraneh sadaya.",
        "translation_sunda_klasik": [
            {"word": "قَالَ", "symbol": "فعل", "sunda": "geus ngadawuh", "pegon": "ݢَوْسْ ڠَادَاوُوهْ", "role": "Fi'il Madhi"},
            {"word": "تَعَالَى", "symbol": "اعتراض", "sunda": "bari Maha Luhur", "pegon": "بَارِ مَاهَا لُوهُورْ", "role": "I'tiradhiyyah"},
            {"word": "يَرْفَعِ", "symbol": "فعل", "sunda": "baris ngangkat", "pegon": "بَارِسْ ڠَاڠْكَتْ", "role": "Fi'il Mudhari'"},
            {"word": "اللَّهُ", "symbol": "فا", "sunda": "saha Gusti Allah", "pegon": "سَاهَا ݢُوسْتِي اَللَّهْ", "role": "Fa'il"},
            {"word": "الَّذِينَ", "symbol": "مف", "sunda": "ka jalma-jalma", "pegon": "كَا جَلْمَا-جَلْمَا", "role": "Maf'ul Bih"},
            {"word": "آمَنُوا", "symbol": "صلة", "sunda": "anu geus ariman", "pegon": "اَنُو ݢَوْسْ اَرِيمَانْ", "role": "Shilah"},
            {"word": "مِنكُمْ", "symbol": "ج", "sunda": "ti maraneh sadaya", "pegon": "تِي مَارَانَيهْ سَدَايَا", "role": "Jar-Majrur"}
        ]
    },
    "sample_5": {
        "text": "قد أفلح المؤمنون",
        "tashkil": "قَدْ أَفْلَحَ الْمُؤْمِنُونَ",
        "tarkib_notes": [
            {"word": "قَدْ", "position": "Harf Tahqiq", "i_rab": "Mabni 'alas sukun", "note": "Asup kana fi'il madhi, maknana 'temen-temen'"},
            {"word": "أَفْلَحَ", "position": "Fi'il Madhi", "i_rab": "Mabni 'alal fathi", "note": "Pagawean anu geus kaliwat"},
            {"word": "الْمُؤْمِنُونَ", "position": "Fa'il", "i_rab": "Marfu' bil-wawi", "note": "Jamak mudzakkar salim tanda rafa' wau"}
        ],
        "translation_id": "Sungguh beruntung orang-orang yang beriman.",
        "translation_sunda_lemes": "Saéstuna parantos bagja pisan jalmi-jalmi anu ariman.",
        "translation_sunda_logat": "Temen-temen geus bagja saha jalma-jalma anu ariman.",
        "translation_sunda_klasik": [
            {"word": "قَدْ", "symbol": "تح", "sunda": "temen-temen", "pegon": "تَمَنْ-تَمَنْ", "role": "Harf Tahqiq"},
            {"word": "أَفْلَحَ", "symbol": "فعل", "sunda": "geus bagja", "pegon": "ݢَوْسْ بَاݢْجَا", "role": "Fi'il Madhi"},
            {"word": "الْمُؤْمِنُونَ", "symbol": "فا", "sunda": "saha jalma-jalma nu ariman", "pegon": "سَاهَا جَلْمَا-جَلْمَا نُو اَرِيمَانْ", "role": "Fa'il"}
        ]
    },
    "sample_6": {
        "text": "كاد الفقر أن يكون كفرا",
        "tashkil": "كَادَ الْفَقْرُ أَنْ يَكُونَ كُفْرًا",
        "tarkib_notes": [
            {"word": "كَادَ", "position": "Fi'il Muqorobah", "i_rab": "Mabni 'alal fathi", "note": "Amil nawasikh maknana 'ampir-ampiran / méh-méhan'"},
            {"word": "الْفَقْرُ", "position": "Isim Kaada", "i_rab": "Marfu' bid-dhammah", "note": "Isim tina fi'il muqorobah kaada"},
            {"word": "أَنْ يَكُونَ كُفْرًا", "position": "Khabar Kaada", "i_rab": "Fi mahalli nashbin", "note": "Jumlah an masydariyyah jeung fi'il khabar kaada"}
        ],
        "translation_id": "Hampir-hampir kefakiran itu menjadi sebuah kekufuran.",
        "translation_sunda_lemes": "Ampir-ampiran (méh-méhan) kamiskinan téh ngajantenkeun kana kakufuran.",
        "translation_sunda_logat": "Ampir-ampiran naon kafakiran, yén aya itu kafakiran téh, eta kufur.",
        "translation_sunda_klasik": [
            {"word": "كَادَ", "symbol": "كاد", "sunda": "ampir-ampiran", "pegon": "اَمْڤِيرْ-اَمْڤِيرَانْ", "role": "Fi'il Muqorobah"},
            {"word": "الْفَقْرُ", "symbol": "اسم", "sunda": "naon kafakiran", "pegon": "نَاوُنْ كَافَاكِيرَانْ", "role": "Isim Kaada"},
            {"word": "أَنْ يَكُونَ", "symbol": "خبر", "sunda": "yen aya itu kafakiran teh", "pegon": "يَينْ اَيَا اِيتُو كَافَاكِيرَانْ تَيْهْ", "role": "Khabar Kaada"},
            {"word": "كُفْرًا", "symbol": "خبر كان", "sunda": "eta kufur", "pegon": "ايتَا كُوفُورْ", "role": "Khabar Kaana"}
        ]
    },
    "sample_7": {
        "text": "وقد أسسته على أربعة أرباع وهي ربع العبادات وربع العادات وربع المهلكات وربع المنجيات",
        "tashkil": "وَقَدْ أَسَّسْتُهُ عَلَى أَرْبَعَةِ أَرْبَاعٍ، وَهِيَ: رُبْعُ الْعِبَادَاتِ، وَرُبْعُ الْعَادَاتِ، وَرُبْعُ الْمُهْلِكَاتِ، وَرُبْعُ الْمُنْجِيَاتِ.",
        "tarkib_notes": [
            {"word": "وَقَدْ", "position": "Harf Tahqiq", "i_rab": "Mabni 'alas sukun", "note": "Asup kana fi'il madhi maknana 'temen-temen'"},
            {"word": "أَسَّسْتُ", "position": "Fi'il Madhi + Ta Mutakallim", "i_rab": "Mabni 'alas sukun", "note": "Dhamir mutakallim maknana 'kaula'"},
            {"word": "ـهُ", "position": "Maf'ul Bih", "i_rab": "Dhamir muttashil", "note": "Mulang ka kitab Ihya: 'kana ieu kitab'"},
            {"word": "عَلَى أَرْبَعَةِ أَرْبَاعٍ", "position": "Jar-Majrur Syibhul Jumlah", "i_rab": "Muta'alliq", "note": "Khabar/Hal diawalan 'eta tetep'"},
            {"word": "وَهِيَ", "position": "Mubtada'", "i_rab": "Dhamir munfashil", "note": "Marja' dibedah: 'jeung ari ieu opat bagean teh'"},
            {"word": "رُبْعُ الْعِبَادَاتِ", "position": "Khabar Mubtada'", "i_rab": "Marfu' bid-dhammah", "note": "Khabar mufrad diawalan 'eta...'"}
        ],
        "translation_id": "Dan sungguh aku telah menyusun kitab ini atas empat bagian, yaitu: seperempat ibadah, seperempat adat kebiasaan, seperempat hal-hal yang membinasakan, dan seperempat hal-hal yang menyelamatkan.",
        "translation_sunda_lemes": "Sareng saéstuna sim kuring parantos ngadamel susunan ieu kitab kana opat bagean, nyaéta: saparapat ibadah, saparapat adat kabiasaan, saparapat perkara anu ngabinasakeun, sareng saparapat perkara anu nyalametkeun.",
        "translation_sunda_logat": "Jeung temen-temen nyusun kaula kana ieu kitab, eta tetep di luhureun opat pirang-pirang bagean. Jeung ari ieu opat bagean teh, eta saparapat pirang-pirang ibadah, jeung saparapat pirang-pirang adat kabiasaan, jeung saparapat pirang-pirang perkara anu ngabinasakeun, jeung saparapat pirang-pirang perkara anu nyalametkeun.",
        "translation_sunda_klasik": [
            {"word": "وَقَدْ", "symbol": "ع تح", "sunda": "jeung temen-temen", "pegon": "جَوْڠْ تَمَنْ-تَمَنْ", "role": "'Athaf + Tahqiq"},
            {"word": "أَسَّسْتُ", "symbol": "فعل فا", "sunda": "nyusun kaula", "pegon": "ڽُوسُونْ كَاوْلَا", "role": "Fi'il + Fa'il (Kaula)"},
            {"word": "ـهُ", "symbol": "مف", "sunda": "kana ieu kitab", "pegon": "كَانَا اِيئوُ كِتَابْ", "role": "Maf'ul Bih"},
            {"word": "عَلَى أَرْبَعَةِ", "symbol": "خ", "sunda": "eta tetep di luhureun opat", "pegon": "ايتَا تَتَڤْ دِي لُوهُورَوْنْ اَوْڤَتْ", "role": "Khabar Syibhul Jumlah"},
            {"word": "أَرْبَاعٍ", "symbol": "مض", "sunda": "pirang-pirang bagean", "pegon": "ڤِيرَاڠْ-ڤِيرَاڠْ بَاݢَايَانْ", "role": "Mudhaf Ilaih"},
            {"word": "وَهِيَ", "symbol": "م", "sunda": "jeung ari ieu opat bagean teh", "pegon": "جَوْڠْ اَرِ اِيئوُ اَوْڤَتْ بَاݢَايَانْ تَيْهْ", "role": "Mubtada'"},
            {"word": "رُبْعُ", "symbol": "خ", "sunda": "eta saparapat", "pegon": "ايتَا سَاڤَارَاڤَتْ", "role": "Khabar"},
            {"word": "الْعِبَادَاتِ", "symbol": "مض", "sunda": "pirang-pirang ibadah", "pegon": "ڤِيرَاڠْ-ڤِيرَاڠْ عِبَادَةْ", "role": "Mudhaf Ilaih"},
            {"word": "وَرُبْعُ", "symbol": "ع", "sunda": "jeung saparapat", "pegon": "جَوْڠْ سَاڤَارَاڤَتْ", "role": "'Athaf"},
            {"word": "الْعَادَاتِ", "symbol": "مض", "sunda": "pirang-pirang adat", "pegon": "ڤِيرَاڠْ-ڤِيرَاڠْ عَادَةْ", "role": "Mudhaf Ilaih"},
            {"word": "وَرُبْعُ", "symbol": "ع", "sunda": "jeung saparapat", "pegon": "جَوْڠْ سَاڤَارَاڤَتْ", "role": "'Athaf"},
            {"word": "الْمُهْلِكَاتِ", "symbol": "مض", "sunda": "perkara nu ngabinasakeun", "pegon": "ڤَرْكَارَا نُو ڠَابِينَاسَاكَوْنْ", "role": "Mudhaf Ilaih"},
            {"word": "وَرُبْعُ", "symbol": "ع", "sunda": "jeung saparapat", "pegon": "جَوْڠْ سَاڤَارَاڤَتْ", "role": "'Athaf"},
            {"word": "الْمُنْجِيَاتِ", "symbol": "مض", "sunda": "perkara nu nyalametkeun", "pegon": "ڤَرْكَارَا نُو ڽَالَمَتْكَوْنْ", "role": "Mudhaf Ilaih"}
        ]
    },
    "sample_8": {
        "text": "وأنزل الماء الفرات من المعصرات فأخرج به الحب والنبات",
        "tashkil": "وَأَنْزَلَ الْمَاءَ الْفُرَاتَ مِنَ الْمُعْصِرَاتِ فَأَخْرَجَ بِهِ الْحَبَّ وَالنَّبَاتَ",
        "tarkib_notes": [
            {"word": "وَأَنْزَلَ", "position": "Fi'il Madhi", "i_rab": "Mabni 'alal fathi", "note": "Fa'il mustatir jawazan taqdiruhu Huwa (saha Gusti Allah)"},
            {"word": "الْمَاءَ", "position": "Maf'ul Bih", "i_rab": "Manshub bil-fathah", "note": "Objek mati diawalan 'kana'"},
            {"word": "الْفُرَاتَ", "position": "Na'at / Shifat", "i_rab": "Manshub bil-fathah", "note": "Nuturkeun man'ut al-maa'a: 'anu tawar'"},
            {"word": "مِنَ الْمُعْصِرَاتِ", "position": "Jar wa Majrur", "i_rab": "Muta'alliq", "note": "Berta'alluq ka anjala: 'tina mega anu meres cai'"},
            {"word": "فَأَخْرَجَ", "position": "Fi'il Madhi Ma'thuf", "i_rab": "Mabni 'alal fathi", "note": "Fa rabithah/sababiyyah: 'mangka geus ngaluarkeun'"},
            {"word": "بِهِ", "position": "Jar-Majrur", "i_rab": "Baa sababiyyah", "note": "ku sabab eta cai teh"},
            {"word": "الْحَبَّ", "position": "Maf'ul Bih", "i_rab": "Manshub bil-fathah", "note": "kana siki-sikian"},
            {"word": "وَالنَّبَاتَ", "position": "Ma'thuf", "i_rab": "Manshub bil-fathah", "note": "jeung kana tutuwuhan"}
        ],
        "translation_id": "Dan Dia menurunkan air yang tawar dari awan pemeras air, lalu Dia mengeluarkan dengannya biji-bijian dan tumbuh-tumbuhan.",
        "translation_sunda_lemes": "Sareng Gusti Allah parantos nurunkeun cai anu seger tina mega anu ngepriskeun cai, lajeng Anjeunna ngaluarkeun ku sabab eta cai kana saniskanten sisikian sareng tutuwuhan.",
        "translation_sunda_logat": "Jeung geus nurunkeun saha Gusti Allah kana cai anu tawar tina mega anu meres cai, mangka geus ngaluarkeun saha Gusti Allah ku sabab eta cai teh kana siki-sikian jeung kana tutuwuhan.",
        "translation_sunda_logat_pegon": "جَوْڠْ ݢَوْسْ نُورُونَكَوْنْ سَاهَا ݢُوسْتِي اَللَّهْ كَانَا چَايْ اَنُو تَاوَارْ تِينَا مَيݢَا اَنُو مَيرَسْ چَايْ، مَڠْكَا ݢَوْسْ ڠَالُوَارْكَوْنْ سَاهَا ݢُوسْتِي اَللَّهْ كُو سَبَبْ ايتَا چَايْ تَيْهْ كَانَا سِيكِي-سِيكِيَانْ جَوْڠْ كَانَا تُوتُوُوُوهَانْ.",
        "translation_sunda_klasik": [
            {"word": "وَأَنْزَلَ", "symbol": "ع فعل", "sunda": "jeung geus nurunkeun saha Gusti Allah", "pegon": "جَوْڠْ ݢَوْسْ نُورُونَكَوْنْ سَاهَا ݢُوسْتِي اَللَّهْ", "role": "Fi'il Madhi + Fa'il"},
            {"word": "الْمَاءَ", "symbol": "مف", "sunda": "kana cai", "pegon": "كَانَا چَايْ", "role": "Maf'ul Bih"},
            {"word": "الْفُرَاتَ", "symbol": "ص", "sunda": "anu tawar", "pegon": "اَنُو تَاوَارْ", "role": "Na'at / Shifat"},
            {"word": "مِنَ الْمُعْصِرَاتِ", "symbol": "ج مج", "sunda": "tina mega anu meres cai", "pegon": "تِينَا مَيݢَا اَنُو مَيرَسْ چَايْ", "role": "Jar-Majrur"},
            {"word": "فَأَخْرَجَ", "symbol": "ع فعل", "sunda": "mangka geus ngaluarkeun saha Gusti Allah", "pegon": "مَڠْكَا ݢَوْسْ ڠَالُوَارْكَوْنْ سَاهَا ݢُوسْتِي اَللَّهْ", "role": "Fi'il Madhi Ma'thuf"},
            {"word": "بِهِ", "symbol": "ج مج", "sunda": "ku sabab eta cai teh", "pegon": "كُو سَبَبْ ايتَا چَايْ تَيْهْ", "role": "Jar-Majrur Sababiyyah"},
            {"word": "الْحَبَّ", "symbol": "مف", "sunda": "kana siki-sikian", "pegon": "كَانَا سِيكِي-سِيكِيَانْ", "role": "Maf'ul Bih"},
            {"word": "وَالنَّبَاتَ", "symbol": "ع", "sunda": "jeung kana tutuwuhan", "pegon": "جَوْڠْ كَانَا تُوتُوُوُوهَانْ", "role": "Ma'thuf"}
        ]
    }
}

# Pastikeun sadaya preset ngagaduhan translation_sunda_logat_pegon sareng token pegon anu lengkep
for _k, _v in SAMPLE_PRESETS.items():
    if "translation_sunda_logat_pegon" not in _v:
        _v["translation_sunda_logat_pegon"] = sunda_to_pegon_full(_v.get("translation_sunda_logat", ""))
    for _token in _v.get("translation_sunda_klasik", []):
        if not _token.get("pegon") or not is_arabic_script(_token.get("pegon", "")):
            _token["pegon"] = sunda_to_pegon_full(_token.get("sunda", ""))

def extract_json_response(raw_text: str) -> dict:
    if not raw_text:
        raise ValueError("Respon dari AI kosong.")

    raw_text = raw_text.strip()

    # 1. Try direct parse
    try:
        return json.loads(raw_text)
    except Exception:
        pass

    # 2. Try markdown block ```json ... ```
    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    # 3. Find outermost { and }
    first_brace = raw_text.find('{')
    last_brace = raw_text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = raw_text[first_brace:last_brace + 1].strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass
        # Models often leave a trailing comma before } or ]
        try:
            return json.loads(re.sub(r',(\s*[}\]])', r'\1', candidate))
        except Exception:
            pass

    # 4. Broken JSON: rescue the text fields that are still intact
    salvaged = {}
    for field in ("tashkil", "translation_id", "translation_sunda_lemes", "translation_sunda_logat", "translation_sunda_logat_pegon"):
        field_match = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
        if field_match:
            try:
                salvaged[field] = json.loads(f'"{field_match.group(1)}"')
            except Exception:
                salvaged[field] = field_match.group(1)
    if salvaged.get("tashkil") and salvaged.get("translation_id"):
        log_debug("Broken JSON from model, salvaged the text fields")
        salvaged.update({"tarkib_notes": [], "translation_sunda_klasik": []})
        return salvaged

    # 5. Nothing usable: callers turn this into a clear error
    return {
        "_parse_failed": True,
        "tashkil": raw_text,
        "tarkib_notes": [
            {"word": "Teks", "position": "Keterangan", "i_rab": "-", "note": "Respon AI dalam bentuk narasi"}
        ],
        "translation_id": raw_text,
        "translation_sunda_lemes": "Mangga tingali teks di luhur",
        "translation_sunda_logat": "Mangga tingali teks di luhur",
        "translation_sunda_klasik": []
    }

# API Endpoints
@app.get("/api/status")
def get_status():
    env_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    total_pages = 1706
    total_kitabs = 40
    total_glossary = 111
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM pesantren_glossary;")
        total_glossary = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass

    return {
        "database_connected": True,
        "total_pages": total_pages,
        "total_kitabs": total_kitabs,
        "total_glossary": total_glossary,
        "env_api_key_configured": env_key,
        "default_model": "gemini-3.5-flash",
        "message": "Sistem siap digunakan."
    }

@app.post("/api/save-key")
def save_key(req: KeyRequest):
    key = req.api_key.strip()
    if key:
        os.environ["GEMINI_API_KEY"] = key
        try:
            with open(ENV_PATH, "w", encoding="utf-8") as f:
                f.write(f"GEMINI_API_KEY={key}\n")
        except Exception:
            pass
        return {"success": True, "message": "API Key berhasil disimpan di file .env dan server!"}
    else:
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        if ENV_PATH.exists():
            try:
                ENV_PATH.unlink()
            except Exception:
                pass
        return {"success": True, "message": "API Key dihapus dari server."}

@app.post("/api/verify-key")
async def verify_key(req: KeyRequest):
    key = req.api_key.strip() or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise HTTPException(status_code=400, detail="API Key tidak boleh kosong.")
    
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    
    last_err = ""
    for test_model in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]:
        try:
            interaction = client.interactions.create(
                model=test_model,
                input="Ping"
            )
            if interaction:
                return {"valid": True, "message": f"Koneksi API Gemini berhasil! Model {test_model} aktif dan siap digunakan."}
        except Exception as e_int:
            err_str = str(e_int)
            last_err = err_str
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                return {"valid": False, "message": "API Key tidak valid. Mohon periksa kembali kunci Anda dari Google AI Studio."}
            
            # Try models API as fallback
            try:
                res = client.models.generate_content(
                    model=test_model,
                    contents="Ping",
                    config=types.GenerateContentConfig(max_output_tokens=5)
                )
                if res:
                    return {"valid": True, "message": f"Koneksi API Gemini berhasil! Model {test_model} aktif dan siap digunakan."}
            except Exception as e_mod:
                last_err = str(e_mod)
                if "API_KEY_INVALID" in last_err or "API key not valid" in last_err:
                    return {"valid": False, "message": "API Key tidak valid. Mohon periksa kembali kunci Anda dari Google AI Studio."}

    if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
        return {"valid": False, "message": "Batas kuota gratis (Rate Limit 429) tercapai. Silakan coba beberapa saat lagi atau gunakan API key lain."}
    elif "503" in last_err or "high demand" in last_err.lower():
        return {"valid": True, "message": "API Key valid! Server Google sedang mengalami lonjakan trafik (503), sistem akan otomatis mencoba model cadangan."}
    return {"valid": False, "message": f"Respon API: {last_err[:200]}"}

# Glossary Endpoints
@app.get("/api/glossary")
def get_glossary(q: Optional[str] = None, category: Optional[str] = None, limit: int = 200):
    conn = get_db()
    cur = conn.cursor()
    sql = "SELECT id, arabic_word, arabic_norm, grammar_role, pesantren_marker, sunda_meaning, indo_meaning, category, notes, created_at FROM pesantren_glossary"
    params = []
    clauses = []
    if q:
        norm_q = normalize_arabic(q)
        clauses.append("(arabic_word LIKE ? OR arabic_norm LIKE ? OR sunda_meaning LIKE ? OR indo_meaning LIKE ?)")
        term = f"%{q}%"
        norm_term = f"%{norm_q}%"
        params.extend([term, norm_term, term, term])
    if category:
        clauses.append("category = ?")
        params.append(category)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?;"
    params.append(limit)
    
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.get("/api/alfiyyah/versions")
def get_alfiyyah_versions():
    return [
        {
            "id": "ibnu_aqil",
            "name": "شرح ابن عقيل",
            "name_display": "Syarah Ibnu 'Aqil",
            "desc": "Syarah paling mashur tur otoritatif di pasantren, ngajelaskeun i'rab, hukum nahwu, jeung syahid bait kalawan rinci.",
            "badge": "Standar Pasantren"
        },
        {
            "id": "audhah",
            "name": "أوضح المسالك إلى ألفية ابن مالك",
            "name_display": "Audhah al-Masalik (Ibnu Hisyam)",
            "desc": "Karya agung Sulthanul I'rab Ibnu Hisyam al-Anshari, ngabedah struktur kalam kalawan dalil anu jero tur taliti.",
            "badge": "Analisis Matang"
        },
        {
            "id": "matan",
            "name": "الخلاصة الألفية (متن ابن مالك)",
            "name_display": "Matan Murni Alfiyyah",
            "desc": "1004 bait nadhom murni Imam Ibnu Malik bersyakal lengkep, bahr rajaz, jeung wazan nahwu sharaf.",
            "badge": "Teks Asli"
        },
        {
            "id": "sunda_logat",
            "name": "Makna Gandul & Logat Pasantren Sunda",
            "name_display": "Makna Gandul Sunda & Ihya'",
            "desc": "Tarjamah ngalogat Sunda harfiah per kecap, rumus baku tarkib pasantren, sarta korelasi langsung kana Kitab Ihya 'Ulum al-Din.",
            "badge": "Kaidah Ngalogat"
        }
    ]

@app.get("/api/alfiyyah/chapters")
def get_alfiyyah_chapters():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT chapter_num, name_ar, name_su, start_bayt, end_bayt, bayt_count,
                   syarah_ibnu_aqil, syarah_audhah, sunda_formula, ihya_link, ihya_logat
            FROM alfiyyah_chapters
            ORDER BY chapter_num ASC;
        """)
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log_debug(f"Error fetching alfiyyah_chapters: {e}")
        rows = []
    finally:
        conn.close()
    return rows

@app.get("/api/alfiyyah/chapter/{chapter_num}")
def get_alfiyyah_chapter(chapter_num: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM alfiyyah_chapters WHERE chapter_num = ?;", (chapter_num,))
        ch = cur.fetchone()
        if not ch:
            raise HTTPException(status_code=404, detail="Bab Alfiyyah henteu kapendak")
        result = dict(ch)
        cur.execute("""
            SELECT bayt_num, chapter_num, sadr, ajz, full_bayt, sunda_logat, syarah_ibnu_aqil, syarah_audhah, ihya_link
            FROM alfiyyah_bayts
            WHERE chapter_num = ?
            ORDER BY bayt_num ASC;
        """, (chapter_num,))
        result["bayts"] = [dict(b) for b in cur.fetchall()]
    finally:
        conn.close()
    return result

@app.get("/api/alfiyyah/bayts")
def get_alfiyyah_bayts(
    chapter: Optional[int] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    limit: int = 100
):
    conn = get_db()
    cur = conn.cursor()
    try:
        query = "SELECT * FROM alfiyyah_bayts WHERE 1=1"
        params = []
        if chapter is not None:
            query += " AND chapter_num = ?"
            params.append(chapter)
        if start is not None:
            query += " AND bayt_num >= ?"
            params.append(start)
        if end is not None:
            query += " AND bayt_num <= ?"
            params.append(end)
        query += " ORDER BY bayt_num ASC LIMIT ?;"
        params.append(limit)
        cur.execute(query, params)
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return rows

@app.get("/api/alfiyyah/search")
def search_alfiyyah(q: str = Query(..., min_length=2)):
    conn = get_db()
    cur = conn.cursor()
    try:
        like_q = f"%{q}%"
        cur.execute("""
            SELECT chapter_num, name_ar, name_su, start_bayt, end_bayt, bayt_count,
                   syarah_ibnu_aqil, syarah_audhah, sunda_formula, ihya_link, ihya_logat
            FROM alfiyyah_chapters
            WHERE name_ar LIKE ? OR name_su LIKE ? OR sunda_formula LIKE ? OR syarah_ibnu_aqil LIKE ?
            ORDER BY chapter_num ASC;
        """, (like_q, like_q, like_q, like_q))
        matching_chapters = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT b.*, c.name_ar as chapter_name_ar, c.name_su as chapter_name_su
            FROM alfiyyah_bayts b
            JOIN alfiyyah_chapters c ON b.chapter_num = c.chapter_num
            WHERE b.full_bayt LIKE ? OR b.sunda_logat LIKE ? OR b.syarah_ibnu_aqil LIKE ? OR b.syarah_audhah LIKE ?
            ORDER BY b.bayt_num ASC
            LIMIT 50;
        """, (like_q, like_q, like_q, like_q))
        matching_bayts = [dict(r) for r in cur.fetchall()]

        return {
            "query": q,
            "chapters_count": len(matching_chapters),
            "chapters": matching_chapters,
            "bayts_count": len(matching_bayts),
            "bayts": matching_bayts
        }
    finally:
        conn.close()

@app.get("/api/alfiyyah")
def get_alfiyyah_knowledge():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM alfiyyah_chapters;")
        if cur.fetchone()[0] > 0:
            cur.execute("""
                SELECT chapter_num as bab_id, name_ar as bab_name, name_su as bab_sunda,
                       start_bayt, end_bayt, bayt_count,
                       (SELECT full_bayt FROM alfiyyah_bayts WHERE chapter_num = c.chapter_num LIMIT 1) as nadhom_key,
                       syarah_ibnu_aqil as syarah_summary,
                       sunda_formula, ihya_link as ihya_example, ihya_logat
                FROM alfiyyah_chapters c
                ORDER BY chapter_num ASC;
            """)
            rows = [dict(r) for r in cur.fetchall()]
        else:
            cur.execute("SELECT * FROM alfiyyah_knowledge ORDER BY bab_id ASC;")
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log_debug(f"Alfiyyah knowledge error: {e}")
        rows = []
    finally:
        conn.close()
    return rows

@app.post("/api/glossary")
def add_or_update_glossary(item: GlossaryItem):
    arabic_word = item.arabic_word.strip()
    if not arabic_word or not item.sunda_meaning.strip():
        raise HTTPException(status_code=400, detail="Lafadz Arab dan Arti Sunda Pesantren wajib diisi.")
    
    norm = normalize_arabic(arabic_word)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO pesantren_glossary 
            (arabic_word, arabic_norm, grammar_role, pesantren_marker, sunda_meaning, indo_meaning, category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(arabic_word, grammar_role) DO UPDATE SET
                pesantren_marker = excluded.pesantren_marker,
                sunda_meaning = excluded.sunda_meaning,
                indo_meaning = excluded.indo_meaning,
                category = excluded.category,
                notes = excluded.notes;
        """, (
            arabic_word,
            norm,
            item.grammar_role or "umum",
            item.pesantren_marker or "",
            item.sunda_meaning.strip(),
            item.indo_meaning or "",
            item.category or "umum",
            item.notes or ""
        ))
        conn.commit()
        last_id = cur.lastrowid
        conn.close()
        return {"success": True, "message": f"Kosa kata '{arabic_word}' berhasil disimpan ke kamus!", "id": last_id}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan ke kamus: {e}")

@app.delete("/api/glossary/{item_id}")
def delete_glossary_item(item_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pesantren_glossary WHERE id = ?;", (item_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Kosa kata berhasil dihapus dari kamus."}

@app.get("/api/books")
def get_books():
    return [{k: b.get(k) for k in ("id", "title", "title_latin", "navigation", "default")} for b in BOOKS]

@app.get("/api/volumes")
def get_volumes(book: Optional[str] = None):
    cfg = hadith_book(book)
    if cfg:
        conn = get_book_db(cfg)
        rows = conn.execute("""
            SELECT volume as volume_number, count(*) as hadith_count,
                   min(number) as first_hadith, max(number_end) as last_hadith
            FROM hadiths GROUP BY volume ORDER BY volume;
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.volume_number, v.title_ar, v.title_id, 
               min(p.volume_page) as min_vol_page, max(p.volume_page) as max_vol_page, 
               count(p.global_page_id) as total_pages
        FROM volumes v
        JOIN pages p ON v.volume_number = p.volume
        GROUP BY v.volume_number
        ORDER BY v.volume_number;
    """)
    vols = [dict(row) for row in cur.fetchall()]
    conn.close()
    return vols

@app.get("/api/kitabs")
def get_kitabs(vol: Optional[int] = None, book: Optional[str] = None):
    cfg = hadith_book(book)
    if cfg:
        conn = get_book_db(cfg)
        rows = conn.execute("""
            SELECT k.id, k.title, k.title_en, k.first_hadith, k.last_hadith, k.hadith_count,
                   (SELECT count(*) FROM babs b WHERE b.kitab_id = k.id) as bab_count
            FROM kitabs k ORDER BY k.id;
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT k.id, k.volume_number, k.kitab_number, k.title_short, k.title_full,
               k.start_page as start_global_page, k.end_page as end_global_page,
               p1.volume_page as start_vol_page, p2.volume_page as end_vol_page,
               k.page_count
        FROM kitabs k
        JOIN pages p1 ON k.start_page = p1.global_page_id
        JOIN pages p2 ON k.end_page = p2.global_page_id
    """
    if vol:
        query += " WHERE k.volume_number = ? ORDER BY k.id;"
        cur.execute(query, (vol,))
    else:
        query += " ORDER BY k.id;"
        cur.execute(query)
    kitabs = [dict(row) for row in cur.fetchall()]
    conn.close()
    return kitabs

@app.get("/api/babs")
def get_babs(book: str = Query(...), kitab: int = Query(..., ge=1)):
    cfg = hadith_book(book)
    if not cfg:
        raise HTTPException(status_code=400, detail="Kitab ini tidak dibagi per bab hadis.")
    conn = get_book_db(cfg)
    rows = conn.execute("""
        SELECT b.id, b.title, b.intro, min(h.number) as first_hadith, max(h.number_end) as last_hadith, count(h.number) as hadith_count
        FROM babs b LEFT JOIN hadiths h ON h.bab_id = b.id
        WHERE b.kitab_id = ? GROUP BY b.id ORDER BY b.id;
    """, (kitab,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

HADITH_COLUMNS = """
    h.number, h.number_end, h.volume, h.page, h.text, h.source,
    h.kitab_id, k.title as kitab_title, h.bab_id, b.title as bab_title, b.intro as bab_intro
"""
HADITH_JOINS = "FROM hadiths h JOIN kitabs k ON k.id = h.kitab_id LEFT JOIN babs b ON b.id = h.bab_id"

@app.get("/api/hadith")
def get_hadith(book: str = Query(...), number: int = Query(..., ge=1)):
    cfg = hadith_book(book)
    if not cfg:
        raise HTTPException(status_code=400, detail="Kitab ini dibaca per halaman, bukan per hadis.")
    conn = get_book_db(cfg)
    # A text can carry a range of numbers, so any number inside the range finds it
    row = conn.execute(f"SELECT {HADITH_COLUMNS} {HADITH_JOINS} WHERE h.number <= ? AND h.number_end >= ?;", (number, number)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Hadis nomor {number} tidak ditemukan.")
    result = dict(row)
    result["prev_number"] = conn.execute("SELECT max(number) FROM hadiths WHERE number < ?;", (row["number"],)).fetchone()[0]
    result["next_number"] = conn.execute("SELECT min(number) FROM hadiths WHERE number > ?;", (row["number"],)).fetchone()[0]
    result["last_number"] = conn.execute("SELECT max(number_end) FROM hadiths;").fetchone()[0]
    conn.close()
    return result

@app.get("/api/hadiths")
def list_hadiths(book: str = Query(...), kitab: Optional[int] = None, bab: Optional[int] = None,
                 offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    cfg = hadith_book(book)
    if not cfg:
        raise HTTPException(status_code=400, detail="Kitab ini dibaca per halaman, bukan per hadis.")
    if not kitab and not bab:
        raise HTTPException(status_code=400, detail="Sebutkan kitab atau bab.")
    where, params = ("h.bab_id = ?", [bab]) if bab else ("h.kitab_id = ?", [kitab])
    conn = get_book_db(cfg)
    total = conn.execute(f"SELECT count(*) FROM hadiths h WHERE {where};", params).fetchone()[0]
    rows = conn.execute(f"SELECT {HADITH_COLUMNS} {HADITH_JOINS} WHERE {where} ORDER BY h.number LIMIT ? OFFSET ?;", params + [limit, offset]).fetchall()
    conn.close()
    return {"total": total, "offset": offset, "limit": limit, "hadiths": [dict(r) for r in rows]}

@app.get("/api/page")
def get_page(vol: int = Query(..., ge=1, le=4), page: int = Query(..., ge=1), book: Optional[str] = None):
    if hadith_book(book):
        raise HTTPException(status_code=400, detail="Kitab ini dibaca per hadis. Gunakan /api/hadith.")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT global_page_id, volume, volume_page, rub_title, kitab_id, kitab_title, bab_title, fasal_title, content_clean
        FROM pages
        WHERE volume = ? AND volume_page = ?;
    """, (vol, page))
    row = cur.fetchone()
    
    if not row:
        cur.execute("""
            SELECT global_page_id, volume, volume_page, rub_title, kitab_id, kitab_title, bab_title, fasal_title, content_clean
            FROM pages
            WHERE volume = ?
            ORDER BY ABS(volume_page - ?) ASC
            LIMIT 1;
        """, (vol, page))
        row = cur.fetchone()

    cur.execute("SELECT min(volume_page), max(volume_page) FROM pages WHERE volume = ?;", (vol,))
    min_p, max_p = cur.fetchone()

    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Halaman tidak ditemukan.")
    
    result = dict(row)
    result["min_vol_page"] = min_p
    result["max_vol_page"] = max_p
    return result

def normalize_ar(text: str) -> str:
    if not text:
        return ""
    # Strip diacritics / tashkil
    text = re.sub(r'[\u0617-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]', '', text)
    # Normalize alef variants
    text = re.sub(r'[أإآٱ]', 'ا', text)
    # Normalize ya / alif maqsura
    text = re.sub(r'ى', 'ي', text)
    # Normalize ta marbuta
    text = re.sub(r'ة', 'ه', text)
    return text.strip()

MARK_OPEN = '<mark class="bg-amber-200 text-amber-900 px-1 rounded font-bold">'

def search_hadith(cfg: Dict[str, Any], q: str, vol: Optional[int], limit: int):
    conn = get_book_db(cfg)
    raw_q = q.strip()
    base = f"""
        SELECT h.number, h.number_end, h.volume, k.title as kitab_title, b.title as bab_title,
               snippet(hadiths_norm_fts, 1, '{MARK_OPEN}', '</mark>', '...', 25) as excerpt
        FROM hadiths_norm_fts f
        JOIN hadiths h ON h.number = f.number
        JOIN kitabs k ON k.id = h.kitab_id
        LEFT JOIN babs b ON b.id = h.bab_id
        WHERE hadiths_norm_fts MATCH ?
    """
    if vol:
        base += " AND h.volume = ?"

    # A plain number jumps straight to that hadith
    if raw_q.isdigit():
        row = conn.execute("""
            SELECT h.number, h.number_end, h.volume, k.title as kitab_title, b.title as bab_title, substr(h.text, 1, 200) as excerpt
            FROM hadiths h JOIN kitabs k ON k.id = h.kitab_id LEFT JOIN babs b ON b.id = h.bab_id
            WHERE h.number <= ? AND h.number_end >= ?;
        """, (int(raw_q), int(raw_q))).fetchone()
        conn.close()
        return [dict(row)] if row else []

    norm_q = normalize_ar(raw_q)
    words = [w for w in norm_q.split() if len(w) > 1]
    queries = ([f'"{norm_q}"', " AND ".join(words[:6])] if len(words) > 1 else [norm_q]) if norm_q else []
    results = []
    for query_str in queries:
        params = [query_str] + ([vol] if vol else []) + [limit]
        try:
            results = [dict(r) for r in conn.execute(base + " ORDER BY h.number LIMIT ?;", params).fetchall()]
        except Exception:
            results = []
        if results:
            break

    # Whole-word search misses forms with a prefix, such as بالنية for النية
    seen = {r["number"] for r in results}
    if re.search(r'\w', norm_q) and len(results) < limit:
        escaped = norm_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql = """
            SELECT h.number, h.number_end, h.volume, k.title as kitab_title, b.title as bab_title, f.text_norm as body
            FROM hadiths_norm_fts f
            JOIN hadiths h ON h.number = f.number
            JOIN kitabs k ON k.id = h.kitab_id
            LEFT JOIN babs b ON b.id = h.bab_id
            WHERE f.text_norm LIKE ? ESCAPE '\\'
        """
        params = [f"%{escaped}%"]
        if vol:
            sql += " AND h.volume = ?"
            params.append(vol)
        for row in conn.execute(sql + " ORDER BY h.number;", params):
            if len(results) >= limit:
                break
            if row["number"] in seen:
                continue
            item = dict(row)
            body = item.pop("body")
            at = body.find(norm_q)
            start = max(0, at - 90)
            end = at + len(norm_q) + 90
            item["excerpt"] = (
                ("..." if start else "") + body[start:at] + MARK_OPEN + norm_q + "</mark>"
                + body[at + len(norm_q):end] + ("..." if end < len(body) else "")
            )
            seen.add(item["number"])
            results.append(item)

    # A bab title can name the topic even when the hadith text never says the word
    if raw_q and '"' not in raw_q and len(results) < limit:
        sql = """
            SELECT h.number, h.number_end, h.volume, k.title as kitab_title, b.title as bab_title, substr(h.text, 1, 200) as excerpt
            FROM hadiths_fts f
            JOIN hadiths h ON h.number = f.number
            JOIN kitabs k ON k.id = h.kitab_id
            LEFT JOIN babs b ON b.id = h.bab_id
            WHERE hadiths_fts MATCH ?
        """
        params = [f'bab_title : "{raw_q}"']
        if vol:
            sql += " AND h.volume = ?"
            params.append(vol)
        try:
            for row in conn.execute(sql + " ORDER BY h.number;", params):
                if len(results) >= limit:
                    break
                if row["number"] not in seen:
                    seen.add(row["number"])
                    results.append(dict(row))
        except Exception:
            pass
    conn.close()
    return results

@app.get("/api/search")
def search_kitab(q: str = Query(..., min_length=1), vol: Optional[int] = None, limit: int = 25, book: Optional[str] = None):
    cfg = hadith_book(book)
    if cfg:
        return search_hadith(cfg, q, vol, limit)
    if len(q) < 2:
        raise HTTPException(status_code=422, detail="Minimal 2 huruf.")
    conn = get_db()
    cur = conn.cursor()

    raw_q = q.strip()
    norm_q = normalize_ar(raw_q)
    results = []

    # Strategy 1: Search in pages_norm_fts using normalized query
    if norm_q:
        words = [w for w in norm_q.split() if len(w) > 1]
        queries_to_try = []
        if len(words) > 1:
            queries_to_try.append(f'"{norm_q}"')
            queries_to_try.append(" AND ".join(words[:6]))
        else:
            queries_to_try.append(norm_q)

        for query_str in queries_to_try:
            sql = """
                SELECT volume, volume_page, kitab_title, bab_title,
                       snippet(pages_norm_fts, 5, '<mark class="bg-amber-200 text-amber-900 px-1 rounded font-bold">', '</mark>', '...', 25) as excerpt
                FROM pages_norm_fts
                WHERE pages_norm_fts MATCH ?
            """
            params = [query_str]
            if vol:
                sql += " AND volume = ?"
                params.append(str(vol))
            sql += " LIMIT ?;"
            params.append(limit)

            try:
                cur.execute(sql, params)
                res = [dict(row) for row in cur.fetchall()]
                if res:
                    results = res
                    break
            except Exception:
                pass

    # Strategy 2: Fallback to pages_fts with raw query
    if not results:
        raw_words = [w for w in raw_q.split() if len(w) > 1]
        if raw_words:
            sql = """
                SELECT volume, volume_page, kitab_title, bab_title,
                       snippet(pages_fts, 5, '<mark class="bg-amber-200 text-amber-900 px-1 rounded font-bold">', '</mark>', '...', 25) as excerpt
                FROM pages_fts
                WHERE pages_fts MATCH ?
            """
            params = [f'"{raw_q}"' if len(raw_words) > 1 else raw_q]
            if vol:
                sql += " AND volume = ?"
                params.append(str(vol))
            sql += " LIMIT ?;"
            params.append(limit)

            try:
                cur.execute(sql, params)
                results = [dict(row) for row in cur.fetchall()]
            except Exception:
                pass

    # Strategy 3: LIKE search fallback
    if not results:
        like_term = f"%{norm_q or raw_q}%"
        like_sql = """
            SELECT volume, volume_page, kitab_title, bab_title, substr(content_clean, 1, 200) as excerpt
            FROM pages
            WHERE content_clean LIKE ?
        """
        like_params = [like_term]
        if vol:
            like_sql += " AND volume = ?"
            like_params.append(vol)
        like_sql += " LIMIT ?;"
        like_params.append(limit)
        try:
            cur.execute(like_sql, like_params)
            results = [dict(row) for row in cur.fetchall()]
        except Exception:
            pass

    conn.close()
    return results

# ---------------------------------------------------------------------------
# Gemini cascade: one call path per model, hard time budget, dead models skipped
# ---------------------------------------------------------------------------
GEMINI_MODEL_CHAIN = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]
# Paragraf panjang memang bisa makan beberapa menit; tetap di bawah batas 300 detik Vercel.
GEMINI_TOTAL_BUDGET_S = 240.0
GEMINI_ATTEMPT_TIMEOUT_S = 200.0
# A stuck model should fall through quickly: core normally answers within 45s, analysis of 806 letters took 111s.
GEMINI_ATTEMPT_TIMEOUT_CORE_S = 90.0
GEMINI_ATTEMPT_TIMEOUT_ANALYSIS_S = 150.0
_model_blocked_until: Dict[str, float] = {}

# Added on top of SYSTEM_INSTRUCTION for hadith books, which open with a chain of narrators.
HADITH_RULES = """
### KAIDAH TAMBAHAN UNTUK TEKS HADIS (SANAD & MATAN):
Teks ini adalah hadis Shahih al-Bukhari: sanad (rangkaian perawi) lalu matan (isi hadis). Terapkan semua kaidah di atas pada keduanya.

* SANAD:
  1. Nama perawi JANGAN diterjemahkan. Beri syakal yang akurat pada 'tashkil', dan tulis dengan huruf Latin yang lazim pada terjemahan (Al-Humaidi, Sufyan, Yahya bin Sa'id). Nama perawi adalah satu-satunya pengecualian dari larangan transliterasi.
  2. Lafadz periwayatan dalam 'translation_sunda_logat', mengikuti kaidah fa'il 'saha' dan mutakallim 'kaula':
     - حَدَّثَنَا -> 'geus nyaritakeun ka abdi sadayana saha [perawi]'
     - حَدَّثَنِي -> 'geus nyaritakeun ka kaula saha [perawi]'
     - أَخْبَرَنَا -> 'geus ngawartosan ka abdi sadayana saha [perawi]'
     - أَخْبَرَنِي -> 'geus ngawartosan ka kaula saha [perawi]'
     - سَمِعْتُ -> 'geus ngadangu kaula ka [perawi]'
     - عَنْ di antara perawi -> 'ti [perawi]'
     - قَالَ -> 'geus ngucap saha [perawi]'
  3. Dalam 'translation_id': 'telah menceritakan kepada kami', 'telah mengabarkan kepada kami', 'aku mendengar', 'dari', 'ia berkata'.
  4. Terjemahkan seluruh sanad apa adanya, jangan diringkas dan jangan dilewati.

* MATAN:
  1. صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ ditulis 'SAW' setelah 'Kanjeng Nabi' atau 'Rasulullah'. رَضِيَ اللَّهُ عَنْهُ dan bentuk sejenisnya WAJIB ditulis 'RA', DILARANG ditulis 'Radhiyallahu 'Anhu'.
  2. Ucapan Nabi SAW tetap diterjemahkan sebagai kutipan langsung.
  3. Jangan menambahkan syarah, penjelasan, atau nomor hadis di luar teks.
  4. Orang pertama jamak (نَحْنُ / ـنَا) WAJIB 'abdi sadayana', bukan 'kami' atau 'abdi sadaya'. Kecuali bila yang berbicara Allah SWT, tetap 'Kami'.
"""

def instruction_for(book_cfg: Dict[str, Any]) -> str:
    if book_cfg["navigation"] == "hadith":
        return SYSTEM_INSTRUCTION.replace("(Ihya 'Ulum al-Din)", f"({book_cfg['title_latin']})") + HADITH_RULES
    return SYSTEM_INSTRUCTION

# The logat rules live only in SYSTEM_INSTRUCTION. These only narrow which fields a stage returns.
STAGE_SCOPE_CORE = """
### BATASAN UNTUK PERMINTAAN INI (MENGGANTIKAN SCHEMA DI ATAS):
Terapkan semua kaidah di atas, tetapi kerjakan HANYA: tashkil, translation_id, translation_sunda_lemes, translation_sunda_logat, translation_sunda_logat_pegon.
JANGAN membuat tarkib_notes dan translation_sunda_klasik; keduanya dibuat pada permintaan terpisah.

Jawablah HANYA dalam JSON valid dengan schema:
{
  "tashkil": "teks arab bersyakal lengkap",
  "translation_id": "terjemahan bahasa indonesia...",
  "translation_sunda_lemes": "terjemahan basa sunda lemes...",
  "translation_sunda_logat": "logat pasantren sunda dina aksara latin...",
  "translation_sunda_logat_pegon": "logat pasantren sunda dina aksara arab pegon..."
}
"""

STAGE_SCOPE_ANALYSIS = """
### BATASAN UNTUK PERMINTAAN INI (MENGGANTIKAN SCHEMA DI ATAS):
Terapkan semua kaidah di atas, tetapi kerjakan HANYA: tarkib_notes dan translation_sunda_klasik, untuk SETIAP kata sesuai urutan teks bersyakal di bawah.
Makna pada translation_sunda_klasik WAJIB selaras dengan terjemahan logat di bawah bila tersedia.
Agar ringkas: JANGAN menulis bidang 'note' dan 'pegon' (aksara Pegon per kata dibuat oleh sistem), dan tulis tiap bidang sesingkat mungkin.

Jawablah HANYA dalam JSON valid dengan schema:
{
  "tarkib_notes": [
    {"word": "lafadz", "position": "Kedudukan Nahwu", "shorof": "Wazan singkat", "i_rab": "Tanda I'rab", "symbol": "م"}
  ],
  "translation_sunda_klasik": [
    {"word": "lafadz", "symbol": "م", "sunda": "makna sunda latin", "role": "Mubtada'"}
  ]
}
"""


def _is_quota_error(s: str) -> bool:
    return "429" in s or "RESOURCE_EXHAUSTED" in s


def _is_gone_error(s: str) -> bool:
    return "404" in s or "NOT_FOUND" in s


def _is_bad_key_error(s: str) -> bool:
    return "API_KEY_INVALID" in s or "API key not valid" in s


def _gemini_call_sync(key: str, model: str, prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    try:
        interaction = client.interactions.create(model=model, input=prompt)
        text = getattr(interaction, "output_text", None)
        if not text and getattr(interaction, "outputs", None):
            text = getattr(interaction.outputs[-1], "text", None)
        if text:
            return text
    except Exception as e_int:
        err = str(e_int)
        if _is_quota_error(err) or _is_gone_error(err) or _is_bad_key_error(err):
            raise
        log_debug(f"Interactions ({model}) error, falling back to generate_content: {err[:160]}")

    res = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    if res and res.text:
        return res.text
    raise RuntimeError("Respon kosong dari model.")


async def run_gemini(prompt: str, candidate_keys: List[str], preferred_model: str, attempt_timeout: float = None):
    """Returns (raw_text, model). Gives up cleanly once the time budget is spent."""
    models = [preferred_model] + [m for m in GEMINI_MODEL_CHAIN if m != preferred_model]
    deadline = time.monotonic() + GEMINI_TOTAL_BUDGET_S
    attempt_timeout = attempt_timeout or GEMINI_ATTEMPT_TIMEOUT_S
    errors: List[str] = []
    out_of_time = False

    for key_idx, key in enumerate(candidate_keys, 1):
        log_debug(f"Attempting key #{key_idx}/{len(candidate_keys)} ({key[:8]}...)")
        for model in models:
            remaining = deadline - time.monotonic()
            if remaining < 3:
                out_of_time = True
                break
            tag = f"{key[:8]}|{model}"
            if _model_blocked_until.get(tag, 0) > time.time():
                errors.append(f"K#{key_idx}-{model}: dilewati (429/404 sebelumnya)")
                continue
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(_gemini_call_sync, key, model, prompt),
                    timeout=min(attempt_timeout, remaining),
                )
                log_debug(f"Success with {model} on key #{key_idx}")
                return text, model
            except asyncio.TimeoutError:
                errors.append(f"K#{key_idx}-{model}: timeout")
                log_debug(f"{model} timed out")
            except Exception as e:
                err = str(e)
                errors.append(f"K#{key_idx}-{model}: {err[:90]}")
                log_debug(f"Key #{key_idx} {model} error: {err[:200]}")
                if _is_quota_error(err):
                    daily = "day" in err.lower()
                    _model_blocked_until[tag] = time.time() + (1800 if daily else 60)
                elif _is_gone_error(err):
                    _model_blocked_until[tag] = time.time() + 86400
                elif _is_bad_key_error(err):
                    break
                elif "503" in err:
                    await asyncio.sleep(0.5)
        if out_of_time:
            break

    full_err = " | ".join(errors)
    log_debug(f"ALL ATTEMPTS FAILED: {full_err}")
    if "API_KEY_INVALID" in full_err or "API key not valid" in full_err:
        raise HTTPException(
            status_code=400,
            detail="API Key yang Anda masukkan tidak valid. Silakan periksa kembali dan salin kunci dari https://aistudio.google.com/apikey",
        )
    if "429" in full_err or "RESOURCE_EXHAUSTED" in full_err or "quota" in full_err.lower():
        raise HTTPException(
            status_code=429,
            detail="Kuota gratis Gemini untuk kunci ini sudah habis (batasnya sekitar 20 permintaan per hari per model). Coba lagi besok, atau pakai API Key lain.",
        )
    if out_of_time or "timeout" in full_err:
        raise HTTPException(
            status_code=504,
            detail="Gemini terlalu lama menjawab. Coba lagi, atau pilih teks yang lebih pendek.",
        )
    if "503" in full_err or "high demand" in full_err.lower():
        raise HTTPException(
            status_code=503,
            detail="Server Google Gemini sedang sibuk (503). Silakan coba lagi sebentar lagi.",
        )
    raise HTTPException(status_code=500, detail=f"Gagal memproses dengan Google Gemini API: {full_err[:350]}")


def parse_model_json(raw_text: str) -> dict:
    parsed = extract_json_response(raw_text)
    if parsed.get("_parse_failed"):
        log_debug(f"Unparseable model response ({len(raw_text)} chars)")
        raise HTTPException(status_code=502, detail="Hasil dari AI rusak. Silakan coba lagi, atau pakai teks yang lebih pendek.")
    return parsed


def _glossary_context(cleaned_input: str) -> str:
    _, matched_vocab = get_matched_glossary(cleaned_input)
    if not matched_vocab:
        return ""
    ctx = "\n### KOSA KATA RUJUKAN DARI KAMUS PESANTREN (Gunakan Arti Ini Secara Alami Sesuai Konteks):\n"
    for mv in matched_vocab[:15]:
        raw_s = mv.get('sunda_meaning', '').strip()
        clean_s = raw_s.split('/')[0].strip() if '/' in raw_s else raw_s
        marker_str = f" [Penanda: {mv['pesantren_marker']}]" if mv.get('pesantren_marker') else ""
        ctx += f"- Lafadz '{mv['arabic_word']}'{marker_str} -> '{clean_s}'\n"
    return ctx


def _cache_get(text_hash: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT tashkil, tarkib_notes_json, translation_id, translation_sunda_lemes, translation_sunda_logat, translation_sunda_klasik_json, translation_sunda_logat_pegon
            FROM translations_cache
            WHERE text_hash = ?
        """, (text_hash,))
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as e_cache:
        log_debug(f"Cache check error: {e_cache}")
        return None


def _cache_put(text_hash: str, raw_arabic: str, d: dict):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO translations_cache
            (text_hash, raw_arabic, tashkil, tarkib_notes_json, translation_id, translation_sunda_lemes, translation_sunda_logat, translation_sunda_klasik_json, translation_sunda_logat_pegon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            text_hash,
            raw_arabic,
            d.get("tashkil", ""),
            json.dumps(d.get("tarkib_notes", []), ensure_ascii=False),
            d.get("translation_id", ""),
            d.get("translation_sunda_lemes", ""),
            d.get("translation_sunda_logat", ""),
            json.dumps(d.get("translation_sunda_klasik", []), ensure_ascii=False),
            d.get("translation_sunda_logat_pegon", ""),
        ))
        conn.commit()
        conn.close()
        log_debug(f"Saved result into translations_cache (hash: {text_hash[:8]})")
    except Exception as e_save:
        log_debug(f"Cache save error: {e_save}")


def _full_from_row(row) -> dict:
    tashkil_val = row["tashkil"]
    logat_val = row["translation_sunda_logat"]
    logat_pegon_val = ""
    try:
        logat_pegon_val = row["translation_sunda_logat_pegon"] or ""
    except Exception:
        pass
    if not logat_pegon_val or not is_arabic_script(logat_pegon_val):
        logat_pegon_val = sunda_to_pegon_full(logat_val)

    tarkib_val = json.loads(row["tarkib_notes_json"]) if row["tarkib_notes_json"] else []
    klasik_val = []
    try:
        if row["translation_sunda_klasik_json"]:
            klasik_val = json.loads(row["translation_sunda_klasik_json"])
    except Exception:
        pass
    klasik_val = ensure_sunda_klasik_tokens(tashkil_val, logat_val, tarkib_val, klasik_val)
    tarkib_val = ensure_comprehensive_nahwu_shorof_analysis(tashkil_val, logat_val, tarkib_val, klasik_val)
    return {
        "tashkil": tashkil_val,
        "tarkib_notes": tarkib_val,
        "translation_id": row["translation_id"],
        "translation_sunda_lemes": row["translation_sunda_lemes"],
        "translation_sunda_logat": logat_val,
        "translation_sunda_logat_pegon": logat_pegon_val,
        "translation_sunda_klasik": klasik_val,
        "cached": True,
        "stage": "full",
    }


@app.post("/api/process")
async def process_text(req: ProcessRequest):
    cleaned_input = req.text.strip()
    if not cleaned_input:
        raise HTTPException(status_code=400, detail="Teks Arab tidak boleh kosong.")

    stage = (req.stage or "full").lower()
    if stage not in ("full", "core", "analysis"):
        raise HTTPException(status_code=400, detail="Parameter stage tidak dikenal.")

    book_cfg = resolve_book(req.book)
    is_default_book = book_cfg is DEFAULT_BOOK

    # 1. Check for sample presets (written for Ihya, so they would hide hadith rules elsewhere)
    for k, v in (SAMPLE_PRESETS.items() if is_default_book else ()):
        if v["text"] in cleaned_input or cleaned_input in v["text"]:
            res_v = dict(v)
            tashkil_p = res_v.get("tashkil", "")
            logat_p = res_v.get("translation_sunda_logat", "")
            tarkib_p = res_v.get("tarkib_notes", [])
            klasik_p = res_v.get("translation_sunda_klasik", [])
            klasik_val = ensure_sunda_klasik_tokens(tashkil_p, logat_p, tarkib_p, klasik_p)
            tarkib_val = ensure_comprehensive_nahwu_shorof_analysis(tashkil_p, logat_p, tarkib_p, klasik_val)
            res_v["translation_sunda_klasik"] = klasik_val
            res_v["tarkib_notes"] = tarkib_val
            res_v["stage"] = "full"
            return res_v

    # 2. A finished full result is always served from cache, whatever stage was asked for
    # The same words get different rules per book, so other books never share Ihya's cache keys
    book_prefix = "" if is_default_book else book_cfg["id"] + ":"
    text_hash = hashlib.sha256((book_prefix + cleaned_input).encode('utf-8')).hexdigest()
    core_hash = hashlib.sha256((book_prefix + "core:" + cleaned_input).encode('utf-8')).hexdigest()
    cached_row = _cache_get(text_hash)
    if cached_row:
        log_debug(f"Retrieved full result from cache (hash: {text_hash[:8]})")
        return _full_from_row(cached_row)

    if stage == "core":
        core_row = _cache_get(core_hash)
        if core_row:
            log_debug(f"Retrieved core result from cache (hash: {core_hash[:8]})")
            logat_val = core_row["translation_sunda_logat"]
            pegon_val = core_row["translation_sunda_logat_pegon"] or ""
            if not pegon_val or not is_arabic_script(pegon_val):
                pegon_val = sunda_to_pegon_full(logat_val)
            return {
                "tashkil": core_row["tashkil"],
                "translation_id": core_row["translation_id"],
                "translation_sunda_lemes": core_row["translation_sunda_lemes"],
                "translation_sunda_logat": logat_val,
                "translation_sunda_logat_pegon": pegon_val,
                "cached": True,
                "stage": "core",
            }

    # 3. Resolve API Key Pool (comma/newline separated keys rotate automatically)
    raw_keys_input = (req.api_key or "").strip() or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    candidate_keys = [k.strip() for k in re.split(r'[,;\n\s]+', raw_keys_input) if k.strip().startswith("AIzaSy") or len(k.strip()) > 20]
    if not candidate_keys:
        raise HTTPException(
            status_code=401,
            detail="API Key Gemini belum disetel. Silakan masukkan Gemini API Key Anda di Setelan."
        )

    log_debug(f"Processing text (length: {len(cleaned_input)}, stage: {stage}) with {len(candidate_keys)} candidate key(s)")
    glossary_context = _glossary_context(cleaned_input)
    preferred_model = req.model_name or "gemini-3.5-flash"
    instruction = instruction_for(book_cfg)

    # ---- Stage: analysis (nahwu-shorof + makna miring), built on top of the core result ----
    if stage == "analysis":
        arabic_for_analysis = (req.tashkil or "").strip() or cleaned_input
        prompt = f"""
{instruction}
{STAGE_SCOPE_ANALYSIS}
{glossary_context}

Teks Arab yang harus dianalisis:
\"\"\"{arabic_for_analysis}\"\"\"

Terjemahan logat teks tersebut:
\"\"\"{(req.logat or "").strip()}\"\"\"

Kembalikan jawaban HANYA berupa JSON valid sesuai skema yang diminta.
"""
        raw_response_text, successful_model = await run_gemini(prompt, candidate_keys, preferred_model, GEMINI_ATTEMPT_TIMEOUT_ANALYSIS_S)
        parsed = parse_model_json(raw_response_text)
        core_row = _cache_get(core_hash)
        tashkil_val = (req.tashkil or "").strip() or (core_row["tashkil"] if core_row else cleaned_input)
        logat_val = (req.logat or "").strip() or (core_row["translation_sunda_logat"] if core_row else "")
        tarkib_val = parsed.get("tarkib_notes", [])
        klasik_val = ensure_sunda_klasik_tokens(tashkil_val, logat_val, tarkib_val, parsed.get("translation_sunda_klasik", []))
        tarkib_full = ensure_comprehensive_nahwu_shorof_analysis(tashkil_val, logat_val, tarkib_val, klasik_val)
        if core_row:
            full = _full_from_row(core_row)
            full["tarkib_notes"] = tarkib_full
            full["translation_sunda_klasik"] = klasik_val
            _cache_put(text_hash, cleaned_input, full)
        return {
            "tarkib_notes": tarkib_full,
            "translation_sunda_klasik": klasik_val,
            "cached": False,
            "model_used": successful_model,
            "stage": "analysis",
        }

    # ---- Stage: core (tashkil + translations only, small output) ----
    if stage == "core":
        prompt = f"""
{instruction}
{STAGE_SCOPE_CORE}
{glossary_context}

Kutipan teks bahasa Arab yang harus diproses:
\"\"\"{cleaned_input}\"\"\"

Kembalikan jawaban HANYA berupa JSON valid sesuai skema yang diminta.
"""
        raw_response_text, successful_model = await run_gemini(prompt, candidate_keys, preferred_model, GEMINI_ATTEMPT_TIMEOUT_CORE_S)
        parsed = parse_model_json(raw_response_text)
        logat_val = parsed.get("translation_sunda_logat", "")
        pegon_val = parsed.get("translation_sunda_logat_pegon")
        if not pegon_val or not is_arabic_script(pegon_val):
            pegon_val = sunda_to_pegon_full(logat_val)
        core = {
            "tashkil": parsed.get("tashkil", ""),
            "translation_id": parsed.get("translation_id", ""),
            "translation_sunda_lemes": parsed.get("translation_sunda_lemes", ""),
            "translation_sunda_logat": logat_val,
            "translation_sunda_logat_pegon": pegon_val,
        }
        _cache_put(core_hash, cleaned_input, core)
        core.update({"cached": False, "model_used": successful_model, "stage": "core"})
        return core

    # ---- Stage: full (original single-call behaviour) ----
    active_instruction = SYSTEM_INSTRUCTION_FAST if req.fast_mode else instruction
    prompt = f"""
{active_instruction}
{glossary_context}

Kutipan teks bahasa Arab yang harus diproses:
\"\"\"{cleaned_input}\"\"\"

Kembalikan jawaban HANYA berupa JSON valid sesuai skema yang diminta.
"""
    raw_response_text, successful_model = await run_gemini(prompt, candidate_keys, preferred_model)

    parsed_result = parse_model_json(raw_response_text)
    tashkil_val = parsed_result.get("tashkil", "")
    logat_val = parsed_result.get("translation_sunda_logat", "")
    logat_pegon_val = parsed_result.get("translation_sunda_logat_pegon")
    if not logat_pegon_val or not is_arabic_script(logat_pegon_val):
        logat_pegon_val = sunda_to_pegon_full(logat_val)
    parsed_result["translation_sunda_logat_pegon"] = logat_pegon_val

    tarkib_val = parsed_result.get("tarkib_notes", [])
    klasik_val = ensure_sunda_klasik_tokens(tashkil_val, logat_val, tarkib_val, parsed_result.get("translation_sunda_klasik", []))
    tarkib_full = ensure_comprehensive_nahwu_shorof_analysis(tashkil_val, logat_val, tarkib_val, klasik_val)
    parsed_result["translation_sunda_klasik"] = klasik_val
    parsed_result["tarkib_notes"] = tarkib_full

    _cache_put(text_hash, cleaned_input, parsed_result)

    parsed_result["cached"] = False
    parsed_result["model_used"] = successful_model
    parsed_result["fast_mode"] = req.fast_mode
    parsed_result["stage"] = "full"
    return parsed_result

# Serve UI
@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/index", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
def index(request: Request):
    candidates = [
        BASE_DIR / "templates" / "index.html",
        PROJECT_DIR / "app" / "templates" / "index.html",
        Path.cwd() / "app" / "templates" / "index.html",
        Path("/var/task/app/templates/index.html")
    ]
    html_file = None
    for c in candidates:
        if c.exists():
            html_file = c
            break
    content = html_file.read_text(encoding="utf-8") if (html_file and html_file.exists()) else "<h1>Templates index.html belum dibuat.</h1>"
    resp = HTMLResponse(content=content)
    resp.headers["X-Debug-Path"] = request.url.path
    resp.headers["X-Debug-Scope"] = str(request.scope.get("path"))
    resp.headers["X-Debug-Query"] = str(request.url.query)
    resp.headers["X-Debug-Matched"] = request.headers.get("x-matched-path", "")
    return resp

@app.get("/{full_path:path}")
def catch_all(request: Request, full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        return JSONResponse({"detail": f"API endpoint /{full_path} not found"}, status_code=404)
    return index(request)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port)
