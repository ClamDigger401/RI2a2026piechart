#!/usr/bin/env python3
"""
update_bills.py
Fetches RI 2026 bill data from Para Bellum Provisions WordPress API
and regenerates BOTH index.html and letters.html with up-to-date data.
No API key required. Run: python update_bills.py
"""

import re, json, time, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE_URL = "https://parabellumprovisions.org/wp-json/wp/v2/pages/36120"

# ── Classification ────────────────────────────────────────────────────
RESTRICTION_KW = [
    "prohibit","ban","restrict","limit","require","registration",
    "background check","waiting period","accountability","liability",
    "do-not-sell","red flag","storage mandate","microstamp","bump stock",
    "assault weapon","ghost gun","disqualif","surrender","insurance",
    "ammunition background","one firearm per","one gun per","felony conviction",
    "large capacity","minor.*possess","unlawful.*possess",
]
EXPANSION_KW = [
    "reciprocity","permitless","constitutional carry","repeal",
    "allow","authorize carry","exempt","tax exempt","sales tax",
    "armed campus","silencer","suppressor","civil liability for",
    "carry permit","appeal process","suitable person","concealed carry",
    "disarming a peace","felony for.*disarm","stun gun.*purchase",
    "electronic dart gun.*purchase",
]

def classify(title, desc, changes=""):
    text = (title + " " + desc + " " + changes).lower()
    r = sum(1 for kw in RESTRICTION_KW if re.search(kw, text))
    e = sum(1 for kw in EXPANSION_KW if re.search(kw, text))
    if e > r: return "expansion"
    if r > 0: return "restriction"
    return "mixed"

def strip_tags(html):
    """Remove HTML tags and decode common entities."""
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&amp;', '&').replace('&nbsp;', ' ').replace('&#8212;', '—')
    html = html.replace('&#8216;', "'").replace('&#8217;', "'").replace('&#8220;', '"').replace('&#8221;', '"')
    html = re.sub(r'&#\d+;', '', html)
    html = re.sub(r'&[a-z]+;', '', html)
    return re.sub(r'\s+', ' ', html).strip()

def fetch_api(url, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ri-legislation-tracker/2.0)",
        "Accept": "application/json",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
                data = json.loads(raw)
                html = data.get("content", {}).get("rendered", "")
                if not html:
                    raise RuntimeError("No content.rendered in API response")
                print(f"  Downloaded {len(html):,} bytes from WordPress API")
                return html
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url}")

def clean_html(html):
    """Strip all HTML tags including BZ_Pyq_fadeIn spans, decode entities."""
    # Remove all tags
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&amp;', '&').replace('&nbsp;', ' ').replace('&#8212;', '—')
    text = text.replace('&#8216;', "'").replace('&#8217;', "'")
    text = text.replace('&#8220;', '"').replace('&#8221;', '"')
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'&[a-z]+;', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_elementor_bills(html):
    """
    Parse Elementor-structured bill HTML.
    Match each text-editor block with the button that immediately follows it
    (positional matching) — not by PDF URL, which can be wrong on the source site.
    """
    bills = []

    # Split HTML into ordered chunks: text-editor blocks and button blocks
    # We process them in order so each bill gets the button that follows it
    chunks = re.split(
        r'(<div[^>]*elementor-widget-(?:text-editor|button)[^>]*>)',
        html
    )

    # Build ordered list of (type, content) pairs
    ordered = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if 'elementor-widget-text-editor' in chunk:
            # Grab the content that follows this opening tag
            content_chunk = chunks[i+1] if i+1 < len(chunks) else ""
            ordered.append(('text', chunk + content_chunk))
            i += 2
        elif 'elementor-widget-button' in chunk:
            content_chunk = chunks[i+1] if i+1 < len(chunks) else ""
            ordered.append(('button', chunk + content_chunk))
            i += 2
        else:
            i += 1

    print(f"  Found {sum(1 for t,_ in ordered if t=='text')} text blocks, {sum(1 for t,_ in ordered if t=='button')} button blocks")

    # Now process: for each text block, find the next button block
    for idx, (typ, block) in enumerate(ordered):
        if typ != 'text':
            continue

        clean = clean_html(block)
        num_m = re.search(r'\b([HS]\d{4,5})\b', clean)
        if not num_m:
            continue
        num = num_m.group(1).upper()
        if not re.match(r'^[HS]\d{4,5}$', num):
            continue

        # Find the next button block after this text block
        pbp_color = 'orange'
        pdf_url = ''
        for j in range(idx+1, min(idx+4, len(ordered))):
            next_typ, next_block = ordered[j]
            if next_typ == 'button':
                color_m = re.search(r'elementor-button-(danger|success|warning)', next_block)
                href_m  = re.search(r'href="([^"]*rilegislature\.gov[^"]*)"', next_block)
                if color_m:
                    pbp_color = {'danger':'red','success':'green','warning':'orange'}.get(color_m.group(1), 'orange')
                if href_m:
                    pdf_url = href_m.group(1).replace('.htm', '.pdf')
                break

        if not pdf_url:
            yr = "26"
            if num.startswith('S'):
                pdf_url = f"https://webserver.rilegislature.gov/BillText{yr}/SenateText{yr}/{num}.pdf"
            else:
                pdf_url = f"https://webserver.rilegislature.gov/BillText{yr}/HouseText{yr}/{num}.pdf"

        def extract_field(label, text):
            """Extract field value from clean text using label as anchor."""
            pattern = rf'{label}\s*:?\s*(.*?)(?=Bill Number|Bill number|Sponsors|Bill Title|Official Description|What Changes|Current Status|$)'
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                val = re.split(r'\s+(?:Bill Number|Sponsors|Bill Title|Official Description|What Changes|Current Status)', val)[0]
                return val.strip()
            return ""

        sponsor_raw = extract_field(r'Sponsors?', clean)
        sponsor = re.sub(r'^Introduced by:\s*', '', sponsor_raw).strip()
        sponsor_names = re.findall(r'(?:Rep\.|Sen\.)\s+(?:\w+\s+)?(\w+)', sponsor)
        if not sponsor_names:
            parts = [n.strip().rstrip(';,') for n in re.split(r'[;,]', sponsor) if n.strip()]
            sponsor_names = [p.split()[-1] for p in parts if p.split()]

        title   = extract_field(r'Bill Title', clean)
        desc    = extract_field(r'Official Description', clean)
        changes = extract_field(r'What Changes', clean)
        status  = extract_field(r'Current Status', clean)
        status  = re.sub(r'^:\s*', '', status).strip()
        # pbp_color and pdf_url already set from positional button matching above

        btype = classify(title, desc, changes)
        chamber = "Senate" if num.startswith("S") else "House"

        bills.append({
            "num": num,
            "chamber": chamber,
            "type": btype,
            "pbp": pbp_color,
            "title": title or f"RI {num}",
            "desc": desc or title,
            "changes": changes,
            "status": status or "Referred to Judiciary Committee",
            "introduced": "2026",
            "sponsor": sponsor or "See bill text",
            "sponsorNames": sponsor_names,
            "pdfUrl": pdf_url,
        })

    # Deduplicate by bill number, keeping first occurrence
    seen = set()
    unique = []
    for b in bills:
        if b["num"] not in seen:
            seen.add(b["num"])
            unique.append(b)

    unique.sort(key=lambda x: (0 if x["chamber"] == "House" else 1, x["num"]))
    print(f"  Parsed {len(unique)} unique bills")
    return unique

def read_template(fname):
    """Read HTML file and split around the BILLS array."""
    try:
        content = open(fname, "r").read()
        if len(content) < 5000:
            print(f"  ERROR: {fname} is too small ({len(content)} bytes) — file may be corrupted")
            return None, None, None

        script_start = content.find("<script>")
        if script_start == -1:
            print(f"  ERROR: No <script> tag found in {fname}")
            return None, None, None

        bills_start = content.find("const BILLS = [", script_start)
        if bills_start == -1:
            print(f"  ERROR: No 'const BILLS = [' found in {fname}")
            return None, None, None

        # Find end of BILLS array — try multiple possible endings
        bills_end = -1
        for marker in ["];\n\nconst TYPE_META", "];\n\nconst LEGISLATORS",
                        "];\n\n// ──", "];\n\nfunction", "];\n\nconst FROM"]:
            pos = content.find(marker, bills_start)
            if pos != -1:
                bills_end = pos + 2  # include "];"
                print(f"  Found BILLS end at marker: {repr(marker[:20])}")
                break

        if bills_end == -1:
            print(f"  ERROR: Could not find end of BILLS array in {fname}")
            return None, None, None

        before = content[:script_start]
        middle = content[script_start:bills_start]
        after  = content[bills_end:]

        print(f"  Template: before={len(before)}, middle={len(middle)}, after={len(after)} bytes")

        if len(before) < 500 or len(after) < 500:
            print(f"  ERROR: Template split looks wrong — refusing to continue")
            return None, None, None

        return before, middle, after
    except Exception as e:
        print(f"  ERROR reading {fname}: {e}")
        return None, None, None

def update_file(fname, bills, is_letters=False):
    before_script, before_bills, after_bills = read_template(fname)
    if before_script is None:
        return False
    if len(bills) < 10:
        print(f"  SAFETY: Refusing to write {len(bills)} bills to {fname} — minimum is 10")
        return False
    # Verify the template looks valid
    if 'DOCTYPE html' not in before_script and '<!DOCTYPE' not in before_script:
        print(f"  SAFETY: Template for {fname} looks invalid — aborting")
        return False

    # Build bill objects
    if is_letters:
        bill_objs = [{
            "num":      b["num"],
            "chamber":  b["chamber"],
            "pbp":      b["pbp"],
            "title":    b["title"],
            "desc":     b["desc"],
            "sponsors": b.get("sponsorNames", []),
        } for b in bills]
    else:
        bill_objs = [{k: v for k, v in b.items() if k != "sponsorNames"} for b in bills]

    bills_json = json.dumps(bill_objs, indent=2)

    # Update subtitle count in index.html
    total = len(bills)
    if not is_letters:
        before_script = re.sub(
            r'\d+ confirmed bills · [^<"]+',
            f'{total} confirmed bills · Updated {datetime.now(timezone.utc).strftime("%B %d, %Y")}',
            before_script
        )

    # before_bills ends just before "const BILLS = [" so we must restore that prefix
    result = before_script + before_bills + "const BILLS = " + bills_json + after_bills
    open(fname, "w").write(result)
    return True

if __name__ == "__main__":
    print(f"Fetching WordPress API...")
    try:
        html = fetch_api(SOURCE_URL)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)

    print("Parsing bills from Elementor content...")
    bills = parse_elementor_bills(html)

    if len(bills) < 10:
        print(f"WARNING: Only {len(bills)} bills found — expected 30+. Aborting to prevent data loss.")
        print("This likely means the parser needs updating. Site files NOT modified.")
        raise SystemExit(1)

    counts = {"restriction": 0, "expansion": 0, "mixed": 0}
    for b in bills:
        counts[b["type"]] += 1

    print(f"\nBill summary:")
    for t, c in counts.items():
        print(f"  {t:12s}: {c}")
    print(f"  {'total':12s}: {len(bills)}")
    print()

    print("Updating index.html...")
    if update_file("index.html", bills, is_letters=False):
        print("  ✓ index.html updated")
    else:
        print("  ✗ index.html update FAILED")

    print("Updating letters.html...")
    if update_file("letters.html", bills, is_letters=True):
        print("  ✓ letters.html updated")
    else:
        print("  ✗ letters.html update FAILED")

    print(f"\nDone — {len(bills)} bills written")
    print(f"New bills detected: {', '.join(b['num'] for b in bills)}")
