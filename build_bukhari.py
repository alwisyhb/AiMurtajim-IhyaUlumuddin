import os
import re
import json
import sqlite3
import urllib.request

# Shamela book 1681 as archived by OpenITI, pinned so a rebuild gives the same text.
SOURCE_COMMIT = "47dfd28db9e158c7101c7df1162d4dc99bb70303"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/OpenITI/0275AH/{SOURCE_COMMIT}"
    "/data/0256Bukhari/0256Bukhari.Sahih/0256Bukhari.Sahih.Shamela0001681-ara1"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(BASE_DIR, "bukhari_shamela_raw.txt")
KITABS_PATH = os.path.join(BASE_DIR, "data", "bukhari_kitabs.json")
NUMBERING_PATH = os.path.join(BASE_DIR, "data", "bukhari_numbering.json")
DB_PATH = os.path.join(BASE_DIR, "bukhari.db")

LAST_HADITH = 7563

HADITH_HEADING = re.compile(r"^### \|+ *(\d{1,4})(?: ms\d+)? *-\s*$")
HADITH_ALIAS = re.compile(r"^# *(\d{1,4}) *-\s*$")
PAGE_MARK = re.compile(r"PageV0*(\d+)P0*(\d+)")
BOOK_LINE = re.compile(r"^# *((?:كتاب|أبواب) .{1,40})$")
# The source leaves a few hadiths without a number, right under a bab heading
HADITH_START = re.compile(r"^(و?حدثن|و?حدثت|و?أخبرن)")


def normalize_arabic(text):
    t = re.sub(r"[ً-ٰٟـ]", "", text)
    t = re.sub(r"[إأآٱ]", "ا", t)
    return t.replace("ى", "ي").replace("ة", "ه")


def strip_marks(text):
    text = re.sub(r"PageV\d+P\d+", " ", text)
    text = re.sub(r"\bms\d+\b", " ", text)
    text = re.sub(r"</?span[^>]*>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse(body):
    """Walks the mARkdown lines and returns (babs, hadiths) in book order."""
    main = body[body.index("### | بدء الوحي"):]
    babs, hadiths = [], []
    hadith, volume, page = None, None, None

    def new_bab(title):
        nonlocal hadith
        hadith = None
        if babs and babs[-1]["title"] == "باب" and not babs[-1]["intro"] and not babs[-1]["has_hadith"]:
            babs[-1]["title"] = title
        else:
            babs.append({"title": title, "intro": [], "has_hadith": False})

    def add_text(text, new_paragraph):
        target = hadith["text"] if hadith else (babs[-1]["intro"] if babs else None)
        if target is None or not text:
            return
        if new_paragraph or not target:
            target.append(text)
        else:
            target[-1] += " " + text

    for line in main.split("\n"):
        for v, p in PAGE_MARK.findall(line):
            if int(v) > 0:
                volume, page = int(v), int(p)

        heading = HADITH_HEADING.match(strip_ms_only(line))
        if heading:
            hadith = {"number": int(heading.group(1)), "text": [], "bab": len(babs) - 1, "volume": volume, "page": page}
            hadiths.append(hadith)
            if babs:
                babs[-1]["has_hadith"] = True
            continue

        alias = HADITH_ALIAS.match(line.strip())
        if alias and hadith and not hadith["text"]:
            continue  # several numbers share one text; number_end is set from the next hadith

        if line.startswith("###"):
            title = strip_marks(re.sub(r"^#+ *\|* *", "", line))
            if title and not title.startswith("[ص:") and not title.startswith("[تعليق"):
                new_bab(title)
            continue

        book = BOOK_LINE.match(strip_marks(line))
        if book:
            new_bab(book.group(1))
            continue

        if line.startswith("~~"):
            add_text(strip_marks(line[2:]), False)
        elif line.startswith("#"):
            text = strip_marks(line[1:])
            if text == "باب":
                new_bab("باب")
            else:
                if HADITH_START.match(text) and (hadith is None or hadith["number"] is None) and babs:
                    hadith = {"number": None, "text": [], "bab": len(babs) - 1, "volume": volume, "page": page}
                    hadiths.append(hadith)
                    babs[-1]["has_hadith"] = True
                add_text(text, True)
    return babs, hadiths


def apply_numbering(hadiths, numbering):
    """Applies the audited corrections in data/bukhari_numbering.json, then derives the ranges."""
    relabel = {r["from"]: r["to"] for r in numbering["relabel"]}
    assign = {a["prefix"]: a["number"] for a in numbering["assign"]}
    backfill = {b["number"]: b["text"] for b in numbering["backfill"]}
    for h in hadiths:
        h["source"] = "shamela"
        if h["number"] is None:
            h["number"] = assign[" ".join(h["text"])[:50]]
            h["assigned"] = True
        elif h["number"] in relabel:
            h["number"] = relabel[h["number"]]
        if h["number"] in backfill and not "".join(h["text"]).strip():
            h["text"] = [backfill[h["number"]]]
            h["source"] = "hadith-api"
    # An unnumbered chain can share its number with the numbered text after it
    by_number, unique = {}, []
    for h in hadiths:
        first = by_number.get(h["number"])
        if first is None:
            by_number[h["number"]] = h
            unique.append(h)
        elif first.get("assigned") or h.get("assigned"):
            first["text"] += h["text"]
        else:
            raise ValueError(f"Duplicate hadith number: {h['number']}")
    hadiths[:] = unique
    hadiths.sort(key=lambda h: h["number"])
    for current, following in zip(hadiths, hadiths[1:]):
        current["number_end"] = following["number"] - 1
    hadiths[-1]["number_end"] = LAST_HADITH


def strip_ms_only(line):
    return re.sub(r"PageV\d+P\d+", "", line).rstrip()


def main():
    if not os.path.exists(RAW_PATH):
        print(f"Downloading source: {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, RAW_PATH)

    with open(RAW_PATH, "r", encoding="utf-8", errors="ignore") as f:
        body = f.read().split("#META#Header#End#", 1)[1]
    with open(KITABS_PATH, "r", encoding="utf-8") as f:
        kitabs = json.load(f)

    with open(NUMBERING_PATH, "r", encoding="utf-8") as f:
        numbering = json.load(f)

    babs, hadiths = parse(body)
    apply_numbering(hadiths, numbering)

    def kitab_of(number):
        for k in kitabs:
            if k["first_hadith"] <= number <= k["last_hadith"]:
                return k["number"]
        # Numbers merged across a kitab boundary belong to the kitab before them
        return max(k["number"] for k in kitabs if k["first_hadith"] <= number)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE kitabs (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        title_en TEXT,
        first_hadith INTEGER,
        last_hadith INTEGER,
        hadith_count INTEGER
    );
    CREATE TABLE babs (
        id INTEGER PRIMARY KEY,
        kitab_id INTEGER REFERENCES kitabs(id),
        title TEXT NOT NULL,
        intro TEXT
    );
    CREATE TABLE hadiths (
        number INTEGER PRIMARY KEY,
        number_end INTEGER NOT NULL,
        kitab_id INTEGER REFERENCES kitabs(id),
        bab_id INTEGER REFERENCES babs(id),
        volume INTEGER,
        page INTEGER,
        text TEXT NOT NULL,
        source TEXT NOT NULL
    );
    CREATE INDEX idx_hadiths_kitab ON hadiths(kitab_id);
    CREATE INDEX idx_hadiths_bab ON hadiths(bab_id);
    CREATE INDEX idx_babs_kitab ON babs(kitab_id);
    CREATE VIRTUAL TABLE hadiths_fts USING fts5(number UNINDEXED, kitab_title, bab_title, text);
    CREATE VIRTUAL TABLE hadiths_norm_fts USING fts5(number UNINDEXED, text_norm);
    """)

    cur.executemany("INSERT INTO metadata VALUES (?, ?)", [
        ("book_id", "bukhari"),
        ("title", "صحيح البخاري"),
        ("author", "أبو عبد الله محمد بن إسماعيل البخاري (المتوفى: 256هـ)"),
        ("edition", "دار طوق النجاة، مصورة عن السلطانية، ترقيم محمد فؤاد عبد الباقي"),
        ("volumes", "9"),
        ("numbering", "fuad_abdul_baqi"),
        ("source_url", SOURCE_URL),
    ])

    counts = {}
    for h in hadiths:
        h["kitab"] = kitab_of(h["number"])
        counts[h["kitab"]] = counts.get(h["kitab"], 0) + 1

    for k in kitabs:
        cur.execute(
            "INSERT INTO kitabs VALUES (?, ?, ?, ?, ?, ?)",
            (k["number"], k["title"], k["title_en"], k["first_hadith"], k["last_hadith"], counts.get(k["number"], 0)),
        )

    # A bab belongs to the kitab of the first hadith after its heading
    next_hadith_of_bab = {}
    for h in hadiths:
        next_hadith_of_bab.setdefault(h["bab"], h)
    bab_kitab = {}
    last_kitab = 1
    for i in range(len(babs)):
        if i in next_hadith_of_bab:
            last_kitab = next_hadith_of_bab[i]["kitab"]
        bab_kitab[i] = last_kitab
    for i, b in enumerate(babs):
        cur.execute(
            "INSERT INTO babs VALUES (?, ?, ?, ?)",
            (i + 1, bab_kitab[i], b["title"], "\n".join(b["intro"]) or None),
        )

    kitab_titles = {k["number"]: k["title"] for k in kitabs}
    for h in hadiths:
        text = "\n".join(h["text"]).strip()
        bab_title = babs[h["bab"]]["title"] if h["bab"] >= 0 else ""
        cur.execute(
            "INSERT INTO hadiths VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (h["number"], h["number_end"], h["kitab"], h["bab"] + 1, h["volume"], h["page"], text, h["source"]),
        )
        cur.execute(
            "INSERT INTO hadiths_fts(number, kitab_title, bab_title, text) VALUES (?, ?, ?, ?)",
            (h["number"], kitab_titles[h["kitab"]], bab_title, text),
        )
        cur.execute(
            "INSERT INTO hadiths_norm_fts(number, text_norm) VALUES (?, ?)",
            (h["number"], normalize_arabic(text)),
        )

    conn.commit()
    cur.execute("VACUUM")
    conn.close()
    print(f"Done: {len(kitabs)} kitab, {len(babs)} bab, {len(hadiths)} hadiths -> {DB_PATH}")


if __name__ == "__main__":
    main()
