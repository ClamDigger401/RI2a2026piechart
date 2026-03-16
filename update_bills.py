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

def parse_elementor_bills(html):
    """
    Parse Elementor-structured bill HTML.
    Each bill is a text-editor widget followed by a button widget.
    Button class tells us PBP color: danger=red, success=green, warning=orange.
    """
    bills = []

    # Split into text-editor sections
    # Each bill block = one elementor-widget-text-editor div
    text_blocks = re.findall(
        r'elementor-widget-text-editor.*?<div class="elementor-widget-container">\s*(.*?)\s*</div>\s*</div>\s*</div>',
        html, re.DOTALL
    )

    # Also extract all button blocks with their color and href
    button_blocks = re.findall(
        r'elementor-button-(danger|success|warning)[^"]*"[^>]*>.*?href="([^"]+)"',
        html, re.DOTALL
    )

    # Build a lookup: bill_number -> (pbp_color, pdf_url)
    # from the button blocks
    bill_button_map = {}
    for color, href in button_blocks:
        if 'rilegislature.gov' in href:
            # extract bill number from URL
            m = re.search(r'/([HS]\d{4,5})\.htm', href, re.I)
            if m:
                num = m.group(1).upper()
                pbp = {'danger': 'red', 'success': 'green', 'warning': 'orange'}.get(color, 'orange')
                # Use .pdf instead of .htm
                pdf = href.replace('.htm', '.pdf')
                bill_button_map[num] = (pbp, pdf)

    print(f"  Found {len(text_blocks)} text blocks, {len(bill_button_map)} bill buttons")

    for block in text_blocks:
        # Try to find bill number
        num_m = re.search(r'Bill [Nn]umber\s*:?\s*</strong>\s*([HS]\d{4,5})', block)
        if not num_m:
            # Try alternate format
            num_m = re.search(r'>([HS]\d{4,5})<', block)
        if not num_m:
            continue

        num = num_m.group(1).upper().strip()
        if not re.match(r'^[HS]\d{4,5}$', num):
            continue

        def extract(label):
            # Try <strong>Label:</strong> Value pattern
            pattern = rf'<strong[^>]*>\s*{label}\s*:?\s*</strong>\s*(.*?)(?=<strong|<p[^>]*>|$)'
            m = re.search(pattern, block, re.DOTALL | re.IGNORECASE)
            if m:
                return strip_tags(m.group(1))
            # Try label at end of strong: <strong>Label: value</strong>
            pattern2 = rf'<strong[^>]*>\s*{label}\s*:\s*(.*?)</strong>'
            m2 = re.search(pattern2, block, re.DOTALL | re.IGNORECASE)
            if m2:
                return strip_tags(m2.group(1))
            return ""

        # Extract fields
        sponsor_raw = extract("Sponsors?")
        # Clean up sponsor names - remove "Introduced by:" prefix
        sponsor = re.sub(r'^Introduced by:\s*', '', sponsor_raw).strip()
        # Extract last names for letters.html
        sponsor_names = re.findall(r'(?:Rep\.|Sen\.)\s+(?:\w+\s+)?(\w+)', sponsor)
        if not sponsor_names:
            # Try just last names after semicolons
            sponsor_names = [n.strip().rstrip(';').rstrip(',') for n in re.split(r'[;,]', sponsor) if n.strip()]
            sponsor_names = [n.split()[-1] for n in sponsor_names if n.split()]

        title   = strip_tags(extract("Bill Title"))
        desc    = strip_tags(extract("Official Description"))
        changes = strip_tags(extract("What Changes"))
        status  = strip_tags(extract("Current Status"))

        # Clean up status
        status = re.sub(r'^:\s*', '', status).strip()

        # Get PBP color and PDF URL from button map
        pbp_color, pdf_url = bill_button_map.get(num, ('orange', ''))
        if not pdf_url:
            # Infer PDF URL
            yr = "26"
            if num.startswith('S'):
                pdf_url = f"https://webserver.rilegislature.gov/BillText{yr}/SenateText{yr}/{num}.pdf"
            else:
                pdf_url = f"https://webserver.rilegislature.gov/BillText{yr}/HouseText{yr}/{num}.pdf"

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
    """Read HTML file and split into before/after the BILLS array."""
    try:
        content = open(fname, "r").read()
        script_start = content.find("<script>")
        bills_start  = content.find("const BILLS = [", script_start)
        # Find end of BILLS array
        bills_end = content.find("];\n\nconst TYPE_META", bills_start)
        if bills_end == -1:
            bills_end = content.find("];\n\n// ──", bills_start)
        if bills_end == -1:
            bills_end = content.find("];\n\nconst LEGISLATORS", bills_start)
        if bills_end == -1:
            print(f"  WARNING: Could not find end of BILLS array in {fname}")
            return None, None, None
        bills_end += 2  # include the "];"
        return content[:script_start], content[script_start:bills_start], content[bills_end:]
    except Exception as e:
        print(f"  ERROR reading {fname}: {e}")
        return None, None, None

def update_file(fname, bills, is_letters=False):
    before_script, before_bills, after_bills = read_template(fname)
    if before_script is None:
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

    result = before_script + before_bills + bills_json + after_bills
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

    if not bills:
        print("WARNING: No bills found — aborting to prevent data loss.")
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
