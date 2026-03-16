#!/usr/bin/env python3
"""
update_bills.py
Scrapes parabellumprovisions.com/2026-legislation/ for RI bills
and regenerates BOTH index.html and letters.html with up-to-date data.

No API key required. Run: python update_bills.py
"""

import re
import json
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE_URL = "https://parabellumprovisions.com/2026-legislation/"

# ── Classification ────────────────────────────────────────────────────
RESTRICTION_KW = [
    "prohibit","ban","restrict","limit","require","registration",
    "background check","waiting period","accountability","liability",
    "do-not-sell","red flag","storage mandate","microstamp","bump stock",
    "assault weapon","ghost gun","disqualif","surrender","insurance",
    "ammunition background","one firearm per","one gun per",
]
EXPANSION_KW = [
    "reciprocity","permitless","constitutional carry","repeal",
    "allow","authorize carry","exempt","tax exempt","sales tax",
    "armed campus","silencer","suppressor","civil liability for",
    "carry permit","appeal process","suitable person","concealed carry",
    "disarming a peace","felony for.*disarm",
]

def classify(title, desc, changes=""):
    text = (title + " " + desc + " " + changes).lower()
    r = sum(1 for kw in RESTRICTION_KW if kw in text)
    e = sum(1 for kw in EXPANSION_KW if kw in text)
    if e > r: return "expansion"
    if r > 0: return "restriction"
    return "mixed"

def infer_pbp(title, desc, changes=""):
    """Infer Para Bellum stance from bill content keywords."""
    text = (title + " " + desc + " " + changes).lower()
    # Red keywords = bills PBP typically opposes
    red_kw = ["prohibit","ban","restrict","require training","background check",
               "waiting period","accountability act","liability","insurance mandate",
               "disqualif","surrender","ammunition background","one firearm per",
               "one gun per","involuntary","possession of prohibited","minor.*possess"]
    # Green keywords = bills PBP typically supports
    green_kw = ["reciprocity","permitless","constitutional carry","repeal",
                "sales tax exempt","armed campus","silencer","suppressor",
                "civil liability for","carry permit.*appeal","disarming a peace",
                "stolen firearm","felony.*disarm"]
    r_score = sum(1 for kw in red_kw if re.search(kw, text))
    g_score = sum(1 for kw in green_kw if re.search(kw, text))
    if g_score > r_score: return "green"
    if r_score > g_score: return "red"
    return "orange"

# ── HTML Parser ───────────────────────────────────────────────────────
class PBPParser(HTMLParser):
    LABEL_MAP = {
        "bill number":"num","bill number:":"num",
        "sponsors":"sponsor","sponsors:":"sponsor",
        "bill title":"title","bill title:":"title",
        "official description":"desc","official description:":"desc",
        "what changes":"changes","what changes:":"changes",
        "current status":"status","current status:":"status",
    }

    def __init__(self):
        super().__init__()
        self.bills = []
        self._cur = {}
        self._in_strong = False
        self._label = None
        self._buf = ""
        self._last_href = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "strong":
            self._in_strong = True
            self._buf = ""
        if tag == "a":
            self._last_href = d.get("href","")
            # Detect PBP color from link style/class
            cls = d.get("class","").lower()
            style = d.get("style","").lower()
            if "green" in cls or "green" in style:
                self._cur["_pbp"] = "green"
            elif "red" in cls or "red" in style:
                self._cur["_pbp"] = "red"
            elif "orange" in cls or "orange" in style:
                self._cur["_pbp"] = "orange"

    def handle_endtag(self, tag):
        if tag == "strong":
            self._in_strong = False
            label = self._buf.strip().rstrip(":").lower()
            self._label = self.LABEL_MAP.get(label)
            self._buf = ""
        if tag == "a":
            href = self._last_href or ""
            if "rilegislature.gov" in href and self._cur:
                self._cur["pdfUrl"] = href
            self._last_href = None
        if tag in ("p","li","div","h3","h4") and self._label and self._buf.strip():
            val = re.sub(r"^\s*:\s*","",self._buf.strip()).strip()
            if val:
                self._cur[self._label] = val
            self._buf = ""
            self._label = None

    def handle_data(self, data):
        text = data.strip()
        if not text: return
        if self._in_strong:
            self._buf += text
            return
        if self._label:
            self._buf += (" " + text) if self._buf else text
        # Detect bill number in text
        if re.match(r"^(H|S)\d{4,5}$", text) and self._label == "num":
            if self._cur.get("num") and self._cur.get("num") != text:
                self._save()
            self._cur["num"] = text
            self._buf = ""
            self._label = None

    def _save(self):
        b = self._cur
        if not b.get("num"): return
        if not re.match(r"^(H|S)\d{4,5}$", b.get("num","").strip()): return
        self.bills.append(dict(b))
        self._cur = {}

    def close(self):
        super().close()
        self._save()

def fetch_page(url, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ri-legislation-tracker/2.0)",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url}")

def regex_fallback(html):
    clean = re.sub(r"<[^>]+>"," ",html)
    clean = re.sub(r"&nbsp;"," ",clean)
    clean = re.sub(r"\s+"," ",clean)
    bills = []
    chunks = re.split(r"(?=Bill [Nn]umber\s*:?\s*[HS]\d{4})", clean)
    for chunk in chunks:
        m = re.search(r"Bill [Nn]umber\s*:?\s*([HS]\d{4,5})", chunk)
        if not m: continue
        def ef(label, text):
            r = re.search(rf"{label}\s*:?\s*(.+?)(?=Bill [Nn]umber|Sponsors|Bill Title|Official Description|What Changes|Current Status|$)", text, re.DOTALL|re.IGNORECASE)
            return r.group(1).strip()[:500] if r else ""
        bills.append({"num":m.group(1),"sponsor":ef("Sponsors",chunk),
                      "title":ef("Bill Title",chunk),"desc":ef("Official Description",chunk),
                      "changes":ef("What Changes",chunk),"status":ef("Current Status",chunk)})
    return bills

def extract_date(s):
    m = re.search(r"(\d{2}/\d{2}/\d{4})",s)
    if m:
        try: return datetime.strptime(m.group(1),"%m/%d/%Y").strftime("%b %d, %Y")
        except: pass
    m2 = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}",s,re.I)
    return m2.group(0) if m2 else "2026"

def infer_pdf(num):
    n = num.strip().upper()
    yr = "26"
    if n.startswith("S"):
        return f"https://webserver.rilegislature.gov/BillText{yr}/SenateText{yr}/{n}.pdf"
    return f"https://webserver.rilegislature.gov/BillText{yr}/HouseText{yr}/{n}.pdf"

def scrape_bills(html):
    parser = PBPParser()
    parser.feed(html)
    parser.close()
    raw = parser.bills or regex_fallback(html)
    bills = []
    for b in raw:
        num = b.get("num","").strip().upper()
        if not re.match(r"^(H|S)\d{4,5}$",num): continue
        title   = b.get("title","").strip()
        desc    = b.get("desc","").strip()
        changes = b.get("changes","").strip()
        sponsor = re.sub(r"\s+"," ",b.get("sponsor","").strip())
        status  = b.get("status","Referred to Judiciary Committee").strip()
        pdf_url = b.get("pdfUrl","").strip() or infer_pdf(num)
        btype   = classify(title, desc, changes)
        pbp     = b.get("_pbp") or infer_pbp(title, desc, changes)
        bills.append({
            "num": num,
            "chamber": "Senate" if num.startswith("S") else "House",
            "type": btype,
            "pbp": pbp,
            "title": title or f"RI {num}",
            "desc": desc or title,
            "changes": changes,
            "status": status,
            "introduced": extract_date(status),
            "sponsor": sponsor or "See bill text",
            "pdfUrl": pdf_url,
        })
    bills.sort(key=lambda x:(0 if x["chamber"]=="House" else 1, x["num"]))
    # Also build sponsors list for letters.html (last names only)
    for b in bills:
        sp = b.get("sponsor","")
        # Extract last names from sponsor string
        names = re.findall(r"(?:Rep\.|Sen\.)\s+(?:\w+\s+)?(\w+)", sp)
        b["sponsorNames"] = names
    print(f"  Parsed {len(bills)} bills")
    return bills

# ── Read static template sections from letters.html ───────────────────
def read_letters_template():
    try:
        content = open("letters.html","r").read()
        script_start = content.find("<script>")
        bills_start  = content.find("const BILLS = [", script_start)
        bills_end    = content.find("];\n\nconst TYPE_META", bills_start) + 2
        return content[:script_start], content[script_start:bills_start], content[bills_end:]
    except Exception as e:
        print(f"Warning: Could not read letters.html template: {e}")
        return None, None, None

# ── Read static template sections from index.html ────────────────────
def read_index_template():
    try:
        content = open("index.html","r").read()
        script_start = content.find("<script>")
        bills_start  = content.find("const BILLS = [", script_start)
        bills_end    = content.find("];\n\nconst TYPE_META", bills_start) + 2
        return content[:script_start], content[script_start:bills_start], content[bills_end:]
    except Exception as e:
        print(f"Warning: Could not read index.html template: {e}")
        return None, None, None

# ── Generate index.html ───────────────────────────────────────────────
def generate_index(bills, before_script, before_bills, after_bills):
    updated = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    total = len(bills)

    # Build index-friendly bill objects (no sponsorNames)
    index_bills = [{k:v for k,v in b.items() if k != "sponsorNames"} for b in bills]
    bills_json = json.dumps(index_bills, indent=2)

    # Update subtitle with current count
    updated_before = re.sub(
        r'\d+ confirmed bills · [^<"]+2026',
        f'{total} confirmed bills · Updated {datetime.now(timezone.utc).strftime("%B %d, %Y")}',
        before_script
    )

    return updated_before + before_bills + bills_json + after_bills

# ── Generate letters.html ─────────────────────────────────────────────
def generate_letters(bills, before_script, before_bills, after_bills):
    # Build letters-friendly bill objects with sponsorNames array
    letters_bills = []
    for b in bills:
        lb = {
            "num":      b["num"],
            "chamber":  b["chamber"],
            "pbp":      b["pbp"],
            "title":    b["title"],
            "desc":     b["desc"],
            "sponsors": b.get("sponsorNames", []),
        }
        letters_bills.append(lb)
    bills_json = json.dumps(letters_bills, indent=2)
    return before_script + before_bills + bills_json + after_bills

# ── Main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Fetching {SOURCE_URL} ...")
    try:
        html = fetch_page(SOURCE_URL)
        print(f"  Downloaded {len(html):,} bytes")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)

    print("Parsing bills from Para Bellum Provisions...")
    bills = scrape_bills(html)

    if not bills:
        print("WARNING: No bills found — page structure may have changed. Aborting.")
        raise SystemExit(1)

    counts = {"restriction":0,"expansion":0,"mixed":0}
    for b in bills:
        counts[b["type"]] += 1
    print(f"\nBill summary:")
    for t,c in counts.items():
        print(f"  {t:12s}: {c}")
    print(f"  {'total':12s}: {len(bills)}")

    # Update index.html
    print("\nUpdating index.html...")
    ib_script, ib_before, ib_after = read_index_template()
    if ib_script:
        html_out = generate_index(bills, ib_script, ib_before, ib_after)
        open("index.html","w").write(html_out)
        print("  ✓ index.html updated")
    else:
        print("  ✗ Could not update index.html — template read failed")

    # Update letters.html
    print("Updating letters.html...")
    lb_script, lb_before, lb_after = read_letters_template()
    if lb_script:
        html_out = generate_letters(bills, lb_script, lb_before, lb_after)
        open("letters.html","w").write(html_out)
        print("  ✓ letters.html updated")
    else:
        print("  ✗ Could not update letters.html — template read failed")

    print(f"\nDone — {len(bills)} bills written to both files")
    print(f"Source: {SOURCE_URL}")
    print(f"Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
