#!/usr/bin/env python3
"""
update_bills.py
Scrapes parabellumprovisions.com/2026-legislation/ for RI firearms bills
and regenerates index.html with up-to-date data.

No API key required — scrapes Para Bellum Provisions directly.
Run with: python update_bills.py
"""

import re
import json
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE_URL = "https://parabellumprovisions.com/2026-legislation/"

# ── Keyword-based classifier ──────────────────────────────────────────
RESTRICTION_KEYWORDS = [
    "prohibit", "ban", "restrict", "limit", "require", "registration",
    "background check", "waiting period", "accountability", "liability",
    "do-not-sell", "red flag", "storage mandate", "microstamp", "bump stock",
    "assault weapon", "ghost gun", "disqualif", "surrender", "insurance",
    "ammunition background", "one firearm per", "one gun per",
]
EXPANSION_KEYWORDS = [
    "reciprocity", "permitless", "constitutional carry", "repeal",
    "allow", "authorize carry", "exempt", "tax exempt", "sales tax",
    "armed campus", "silencer", "suppressor", "civil liability for",
    "carry permit", "appeal process", "suitable person", "concealed carry",
    "disarming a peace", "felony for.*disarm",
]

def classify(title, desc, changes=""):
    text = (title + " " + desc + " " + changes).lower()
    r_score = sum(1 for kw in RESTRICTION_KEYWORDS if kw in text)
    e_score = sum(1 for kw in EXPANSION_KEYWORDS if kw in text)
    if e_score > r_score:
        return "expansion"
    elif r_score > 0:
        return "restriction"
    return "mixed"


# ── Minimal HTML parser ───────────────────────────────────────────────
class PBPParser(HTMLParser):
    """
    Parses the Para Bellum Provisions legislation page.
    
    The page structure for each bill looks roughly like:
    
    <div class="bill-entry"> (or similar wrapper)
      <p><strong>Bill Number:</strong> H7035</p>
      <p><strong>Sponsors:</strong> ...</p>
      <p><strong>Bill Title:</strong> ...</p>
      <p><strong>Official Description:</strong> ...</p>
      <p><strong>What Changes:</strong> ...</p>
      <p><strong>Current Status:</strong> ...</p>
      <a href="https://webserver.rilegislature.gov/...">Bill Text</a>
      [green/red/orange button for PBP assessment]
    </div>
    
    We parse by tracking <strong> labels and collecting following text.
    """

    def __init__(self):
        super().__init__()
        self.bills = []
        self._current = {}
        self._in_strong = False
        self._current_label = None
        self._buffer = ""
        self._last_href = None
        self._in_anchor = False
        self._anchor_text = ""

    # Label map: page text → dict key
    LABEL_MAP = {
        "bill number":           "num",
        "bill number:":          "num",
        "sponsors":              "sponsor",
        "sponsors:":             "sponsor",
        "bill title":            "title",
        "bill title:":           "title",
        "official description":  "desc",
        "official description:": "desc",
        "what changes":          "changes",
        "what changes:":         "changes",
        "current status":        "status",
        "current status:":       "status",
    }

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "strong":
            self._in_strong = True
            self._buffer = ""
        if tag == "a":
            self._last_href = attrs_dict.get("href", "")
            self._in_anchor = True
            self._anchor_text = ""
            # Detect PBP color assessment from button classes/style
            cls = attrs_dict.get("class", "").lower()
            style = attrs_dict.get("style", "").lower()
            if "green" in cls or "green" in style or "#00" in style:
                self._current["_pbp_hint"] = "green"
            elif "red" in cls or "red" in style or "#e7" in style or "#c0" in style:
                self._current["_pbp_hint"] = "red"
            elif "orange" in cls or "orange" in style or "#e8" in style or "#f0" in style:
                self._current["_pbp_hint"] = "orange"

    def handle_endtag(self, tag):
        if tag == "strong":
            self._in_strong = False
            label = self._buffer.strip().rstrip(":").lower()
            self._current_label = self.LABEL_MAP.get(label)
            self._buffer = ""
        if tag == "a":
            href = self._last_href or ""
            txt = self._anchor_text.strip().lower()
            # Capture PDF/bill text link
            if ("rilegislature.gov" in href or "webserver.ri" in href) and self._current:
                self._current["pdfUrl"] = href
            # Capture bill text links by anchor text
            if "bill text" in txt and href and self._current:
                self._current["pdfUrl"] = href
            self._in_anchor = False
            self._last_href = None

        # When we hit a closing </p> or </div>, flush the buffer into current bill
        if tag in ("p", "li", "div", "h3", "h4") and self._current_label and self._buffer.strip():
            value = self._buffer.strip()
            # Strip leading colon/whitespace artifacts
            value = re.sub(r"^\s*:\s*", "", value).strip()
            if value:
                self._current[self._current_label] = value
            self._buffer = ""
            self._current_label = None

        # Detect end of a bill block — when we see a new "Bill Number" that
        # triggers a save of the previous block
        # (handled in handle_data by detecting the pattern)

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_strong:
            self._buffer += text
            return
        if self._in_anchor:
            self._anchor_text += text
        if self._current_label:
            self._buffer += " " + text if self._buffer else text

        # Detect bill number pattern directly in text (e.g. "H7035" or "S2726")
        # This helps us split bills even if wrapper divs aren't clean
        bill_num_match = re.match(r"^(H|S)\d{4,5}$", text)
        if bill_num_match and self._current_label == "num":
            # Save previous bill if it has enough data
            if self._current.get("num") and self._current.get("num") != text:
                self._save_current()
            self._current["num"] = text
            self._buffer = ""
            self._current_label = None

    def _save_current(self):
        b = self._current
        if not b.get("num"):
            return
        # Must look like a bill number
        if not re.match(r"^(H|S)\d{4,5}$", b.get("num", "").strip()):
            return
        self.bills.append(dict(b))
        self._current = {}

    def close(self):
        super().close()
        self._save_current()  # Don't forget the last bill


def fetch_page(url, retries=3):
    """Fetch a URL with retries and a browser-like User-Agent."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; RI-legislation-tracker/1.0; "
            "+https://github.com)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


def infer_chamber(num):
    return "Senate" if num.upper().startswith("S") else "House"


def infer_pdf_url(num):
    num = num.strip().upper()
    year = "26"
    if num.startswith("S"):
        return f"https://webserver.rilegislature.gov/BillText{year}/SenateText{year}/{num}.pdf"
    return f"https://webserver.rilegislature.gov/BillText{year}/HouseText{year}/{num}.pdf"


def infer_pbp(bill_data, html_snippet=""):
    """
    Infer PBP stance from hint captured during parsing, or fall back to
    keyword analysis of title/desc/changes.
    """
    hint = bill_data.get("_pbp_hint")
    if hint in ("green", "red", "orange"):
        return hint

    # Fallback: look for color words near the bill number in the raw HTML
    num = bill_data.get("num", "")
    pattern = re.compile(
        rf"{re.escape(num)}.{{0,500}}?"
        r"(background(?:-color)?|color)\s*:\s*"
        r"(#[0-9a-fA-F]{{3,6}}|green|red|orange)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(html_snippet)
    if m:
        color_val = m.group(2).lower()
        if "green" in color_val or color_val.startswith("#0") or color_val.startswith("#2"):
            return "green"
        if "red" in color_val or color_val.startswith("#c0") or color_val.startswith("#e7"):
            return "red"
        return "orange"

    return "orange"  # default neutral if unknown


def scrape_bills(html):
    """Parse raw HTML and return a cleaned list of bill dicts."""
    parser = PBPParser()
    parser.feed(html)
    parser.close()

    raw_bills = parser.bills

    # If parser got nothing (site structure changed), try regex fallback
    if not raw_bills:
        print("  HTML parser found no bills — trying regex fallback...")
        raw_bills = regex_fallback(html)

    bills = []
    for b in raw_bills:
        num = b.get("num", "").strip().upper()
        if not re.match(r"^(H|S)\d{4,5}$", num):
            continue

        title   = b.get("title", "").strip()
        desc    = b.get("desc", "").strip()
        changes = b.get("changes", "").strip()
        sponsor = b.get("sponsor", "").strip()
        status  = b.get("status", "Referred to Judiciary Committee").strip()
        pdf_url = b.get("pdfUrl", "").strip() or infer_pdf_url(num)

        # Clean up sponsor — remove excess whitespace
        sponsor = re.sub(r"\s+", " ", sponsor)

        btype = classify(title, desc, changes)
        pbp   = infer_pbp(b, html)

        bills.append({
            "num":      num,
            "chamber":  infer_chamber(num),
            "type":     btype,
            "pbp":      pbp,
            "title":    title or f"RI {num} — Firearms Bill",
            "desc":     desc or title,
            "changes":  changes,
            "status":   status,
            "introduced": extract_date(status),
            "sponsor":  sponsor or "See bill text",
            "pdfUrl":   pdf_url,
        })

    # Sort House then Senate, then by number
    bills.sort(key=lambda x: (0 if x["chamber"] == "House" else 1, x["num"]))
    print(f"  Parsed {len(bills)} bills from Para Bellum Provisions")
    return bills


def regex_fallback(html):
    """
    Last-resort regex extraction if BeautifulSoup-style parsing fails.
    Looks for patterns like 'Bill Number: H7035' in the raw text.
    """
    bills = []
    # Strip HTML tags for text extraction
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"&amp;", "&", clean)
    clean = re.sub(r"\s+", " ", clean)

    # Split on bill number anchors
    chunks = re.split(r"(?=Bill [Nn]umber\s*:?\s*[HS]\d{4})", clean)
    for chunk in chunks:
        num_m = re.search(r"Bill [Nn]umber\s*:?\s*([HS]\d{4,5})", chunk)
        if not num_m:
            continue
        num = num_m.group(1).strip()

        def extract_field(label, text):
            m = re.search(
                rf"{label}\s*:?\s*(.+?)(?=Bill [Nn]umber|Sponsors|Bill Title|"
                r"Official Description|What Changes|Current Status|$)",
                text, re.DOTALL | re.IGNORECASE
            )
            return m.group(1).strip()[:500] if m else ""

        bills.append({
            "num":      num,
            "sponsor":  extract_field("Sponsors", chunk),
            "title":    extract_field("Bill Title", chunk),
            "desc":     extract_field("Official Description", chunk),
            "changes":  extract_field("What Changes", chunk),
            "status":   extract_field("Current Status", chunk),
        })
    return bills


def extract_date(status_text):
    """Try to pull an introduced date from a status string."""
    m = re.search(r"(\d{2}/\d{2}/\d{4})", status_text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y").strftime("%b %d, %Y")
        except ValueError:
            pass
    m2 = re.search(r"(January|February|March|April|May|June|July|August"
                   r"|September|October|November|December)\s+\d{1,2},?\s*\d{4}",
                   status_text, re.IGNORECASE)
    return m2.group(0) if m2 else "2026"


# ── HTML generator ────────────────────────────────────────────────────
def count_by_type(bills):
    counts = {"restriction": 0, "expansion": 0, "mixed": 0}
    for b in bills:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    return counts


def generate_html(bills):
    counts = count_by_type(bills)
    total  = len(bills)
    updated = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    bills_json = json.dumps(bills, indent=2)
    pie_json = json.dumps([
        {"type": "restriction", "count": counts["restriction"], "color": "#c0392b"},
        {"type": "expansion",   "count": counts["expansion"],   "color": "#2eab7a"},
        {"type": "mixed",       "count": counts["mixed"],       "color": "#e8a838"},
    ])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Rhode Island 2026 — Firearms Legislation</title>
  <meta name="description" content="Interactive breakdown of all confirmed firearms bills in the Rhode Island 2026 legislative session, sourced from Para Bellum Provisions." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background:#0d1520; color:#e8edf2; font-family:'DM Sans',sans-serif; min-height:100vh; padding:40px 20px 80px; }}
    a {{ text-decoration:none; }}
    .wrap {{ max-width:900px; margin:0 auto; }}
    .eyebrow {{ text-align:center; font-size:10px; letter-spacing:4px; color:#c0392b; text-transform:uppercase; margin-bottom:10px; }}
    h1 {{ font-family:'Playfair Display',serif; font-size:clamp(22px,5vw,36px); font-weight:700; text-align:center; color:#e8edf2; line-height:1.2; margin-bottom:8px; }}
    .subtitle {{ text-align:center; color:#566778; font-size:12.5px; margin-bottom:4px; }}
    .updated {{ text-align:center; font-size:11px; color:#3a5060; margin-bottom:4px; }}
    .source-credit {{ text-align:center; font-size:11px; color:#3a5060; margin-bottom:36px; }}
    .source-credit a {{ color:#4a9fd4; }}
    .pie-row {{ display:flex; gap:32px; align-items:center; justify-content:center; flex-wrap:wrap; margin-bottom:36px; }}
    #pie-svg {{ overflow:visible; display:block; cursor:pointer; }}
    .legend {{ display:flex; flex-direction:column; gap:10px; min-width:220px; }}
    .legend-item {{ display:flex; align-items:center; gap:12px; cursor:pointer; padding:10px 14px; border-radius:8px; border:1px solid transparent; transition:all 0.2s ease; }}
    .legend-dot {{ width:14px; height:14px; border-radius:4px; flex-shrink:0; }}
    .legend-label {{ font-size:13px; color:#a0b8cc; font-weight:500; }}
    .legend-sub {{ font-size:11px; color:#566778; }}
    .legend-count {{ font-size:20px; font-weight:700; }}
    #filter-badge {{ text-align:center; margin-bottom:18px; min-height:28px; }}
    .badge {{ display:inline-block; font-size:12px; padding:4px 14px; border-radius:20px; border:1px solid; }}
    .badge .clear {{ cursor:pointer; text-decoration:underline; }}
    #bill-list {{ display:flex; flex-direction:column; gap:10px; }}
    .bill-card {{ border-radius:10px; padding:14px 16px; transition:all 0.25s ease; border-left-width:3px; border-left-style:solid; border-top:1px solid; border-right:1px solid; border-bottom:1px solid; }}
    .bill-card.dimmed {{ opacity:0.3; }}
    .card-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; margin-bottom:6px; flex-wrap:wrap; }}
    .card-tags {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .tag {{ font-family:monospace; font-weight:800; font-size:13px; padding:2px 8px; border-radius:5px; letter-spacing:0.5px; }}
    .tag-sm {{ font-size:10px; padding:2px 7px; border-radius:4px; letter-spacing:1px; text-transform:uppercase; }}
    .card-links {{ display:flex; gap:8px; flex-shrink:0; }}
    .btn-link {{ font-size:10px; padding:3px 8px; border-radius:4px; font-weight:600; white-space:nowrap; transition:opacity 0.15s; }}
    .btn-link:hover {{ opacity:0.75; }}
    .btn-text {{ color:#4a9fd4; background:#4a9fd420; }}
    .card-title {{ font-family:'Playfair Display',serif; font-size:14px; color:#d8e8f2; margin-bottom:4px; line-height:1.4; }}
    .card-desc {{ font-size:12px; color:#8fa8bc; line-height:1.6; margin-bottom:6px; }}
    .card-changes {{ font-size:11.5px; color:#6a8898; line-height:1.6; margin-bottom:8px; border-left:2px solid #1e3a55; padding-left:10px; }}
    .card-meta {{ display:flex; gap:16px; flex-wrap:wrap; }}
    .card-meta span {{ font-size:11px; color:#566778; }}
    .card-meta em {{ color:rgba(74,159,212,0.4); font-style:normal; }}
    .note {{ margin-top:32px; padding:14px 18px; background:#121e2b; border-radius:8px; border-left:3px solid #1e3a55; font-size:11.5px; color:#4a6070; line-height:1.7; }}
    .note strong {{ color:#4a9fd4; }}
    .pbp-badge {{ display:inline-block; font-size:9px; padding:1px 6px; border-radius:3px; font-weight:700; letter-spacing:0.5px; margin-left:4px; vertical-align:middle; }}
    .pbp-green {{ background:#1a4a2a; color:#2eab7a; }}
    .pbp-red {{ background:#3a1a1a; color:#e74c3c; }}
    .pbp-orange {{ background:#3a2e1a; color:#e8a838; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Rhode Island · 2026 Session</div>
  <h1>Firearms Legislation</h1>
  <p class="subtitle">{total} confirmed bills · Auto-updated weekly</p>
  <p class="updated">Last updated: {updated}</p>
  <p class="source-credit">
    Source: <a href="https://parabellumprovisions.com/2026-legislation/" target="_blank" rel="noopener">Para Bellum Provisions</a>
    · Bill text links go to official RI Legislature
    · Color badges reflect Para Bellum's assessment
  </p>
  <div class="pie-row">
    <svg id="pie-svg" width="220" height="220" viewBox="0 0 220 220"></svg>
    <div class="legend" id="legend"></div>
  </div>
  <div id="filter-badge"></div>
  <div id="bill-list"></div>
  <div class="note">
    <strong>Sources &amp; Methodology: </strong>
    Bill data scraped automatically from
    <a href="https://parabellumprovisions.com/2026-legislation/" target="_blank" rel="noopener" style="color:#4a9fd4">Para Bellum Provisions</a>
    and verified against the RI Legislature's official website.
    Color badges (Favorable / Unfavorable / Neutral) reflect Para Bellum Provisions' editorial assessment.
    Classification (Restriction / Expansion / Mixed) is determined by keyword analysis.
    Session ongoing — this page updates every Monday at 8am UTC.
    Hover or tap the pie chart or legend to filter by type.
  </div>
</div>
<script>
const BILLS = {bills_json};
const PIE_DATA = {pie_json};
const TOTAL = BILLS.length;
const TYPE_META = {{
  restriction: {{ label:"Restriction / Control", color:"#c0392b", bg:"rgba(192,57,43,0.13)" }},
  expansion:   {{ label:"Expansion of Rights",   color:"#2eab7a", bg:"rgba(46,171,122,0.13)" }},
  mixed:       {{ label:"Mixed / Regulatory",     color:"#e8a838", bg:"rgba(232,168,56,0.13)" }},
}};
let activeType = null;

function buildPie(active) {{
  const svg=document.getElementById('pie-svg'); svg.innerHTML='';
  const cx=110,cy=110,r=82,ir=44; let angle=-Math.PI/2;
  PIE_DATA.forEach(d=>{{
    const frac=d.count/TOTAL,start=angle,end=angle+frac*2*Math.PI; angle=end;
    const mid=(start+end)/2,isAct=active===d.type;
    const outerR=isAct?r+10:r,ox=isAct?Math.cos(mid)*6:0,oy=isAct?Math.sin(mid)*6:0;
    const largeArc=frac>0.5?1:0;
    const pt=(rad,a)=>[cx+ox+rad*Math.cos(a),cy+oy+rad*Math.sin(a)];
    const [x1,y1]=pt(outerR,start),[x2,y2]=pt(outerR,end);
    const [ix1,iy1]=pt(ir,start),[ix2,iy2]=pt(ir,end);
    const pd=`M ${{ix1}} ${{iy1}} L ${{x1}} ${{y1}} A ${{outerR}} ${{outerR}} 0 ${{largeArc}} 1 ${{x2}} ${{y2}} L ${{ix2}} ${{iy2}} A ${{ir}} ${{ir}} 0 ${{largeArc}} 0 ${{ix1}} ${{iy1}} Z`;
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',pd); path.setAttribute('fill',d.color);
    path.setAttribute('stroke','#0d1520'); path.setAttribute('stroke-width','1.5');
    path.style.cursor='pointer'; path.style.transition='all 0.25s cubic-bezier(.34,1.56,.64,1)';
    path.style.filter=isAct?`drop-shadow(0 3px 10px ${{d.color}}99)`:'none';
    path.addEventListener('mouseenter',()=>setActive(d.type));
    path.addEventListener('mouseleave',()=>setActive(null));
    path.addEventListener('click',()=>setActive(activeType===d.type?null:d.type));
    svg.appendChild(path);
  }});
  const mt=(txt,y,sz,fill,w,fam)=>{{
    const t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',cx);t.setAttribute('y',y);t.setAttribute('text-anchor','middle');
    t.setAttribute('fill',fill);t.style.fontSize=sz+'px';t.style.fontWeight=w;
    t.style.fontFamily=fam||"'Playfair Display',serif";t.textContent=txt;svg.appendChild(t);
  }};
  mt(active?PIE_DATA.find(d=>d.type===active).count:TOTAL,cy+8,28,'#e8edf2',700);
  mt('BILLS',cy+26,10,'#7a8fa0',400,"'DM Sans',sans-serif");
}}

function buildLegend(active) {{
  const el=document.getElementById('legend'); el.innerHTML='';
  PIE_DATA.forEach(d=>{{
    const meta=TYPE_META[d.type],isAct=active===d.type;
    const item=document.createElement('div'); item.className='legend-item';
    item.style.background=isAct?meta.bg:'transparent';
    item.style.borderColor=isAct?meta.color+'55':'transparent';
    item.innerHTML=`<div class="legend-dot" style="background:${{d.color}}"></div>
      <div style="flex:1"><div class="legend-label" style="color:${{isAct?'#e8edf2':'#a0b8cc'}}">${{meta.label}}</div>
      <div class="legend-sub">${{d.count}} bills · ${{Math.round(d.count/TOTAL*100)}}%</div></div>
      <span class="legend-count" style="color:${{d.color}}">${{d.count}}</span>`;
    item.addEventListener('mouseenter',()=>setActive(d.type));
    item.addEventListener('mouseleave',()=>setActive(null));
    item.addEventListener('click',()=>setActive(activeType===d.type?null:d.type));
    el.appendChild(item);
  }});
}}

function buildBadge(active) {{
  const el=document.getElementById('filter-badge');
  if(!active){{el.innerHTML='';return;}}
  const meta=TYPE_META[active],count=BILLS.filter(b=>b.type===active).length;
  el.innerHTML=`<span class="badge" style="color:${{meta.color}};background:${{meta.bg}};border-color:${{meta.color}}44">
    Showing: ${{meta.label}} &middot; ${{count}} bills
    &nbsp;&middot;&nbsp;<span class="clear" id="clear-filter">clear filter</span></span>`;
  document.getElementById('clear-filter').addEventListener('click',()=>setActive(null));
}}

function buildCards(active) {{
  const el=document.getElementById('bill-list'); el.innerHTML='';
  const pbpC={{green:'pbp-green',red:'pbp-red',orange:'pbp-orange'}};
  const pbpL={{green:'✓ Favorable',red:'✗ Unfavorable',orange:'~ Neutral'}};
  BILLS.forEach(bill=>{{
    const meta=TYPE_META[bill.type],h=!active||bill.type===active;
    const card=document.createElement('div');
    card.className='bill-card'+(h?'':' dimmed');
    card.style.borderLeftColor=meta.color;
    card.style.borderTopColor=h?meta.color+'55':'#1e3045';
    card.style.borderRightColor=h?meta.color+'55':'#1e3045';
    card.style.borderBottomColor=h?meta.color+'55':'#1e3045';
    card.style.background=h?meta.bg:'#121e2b';
    const changesHtml=bill.changes?`<div class="card-changes">${{bill.changes}}</div>`:'';
    card.innerHTML=`
      <div class="card-top">
        <div class="card-tags">
          <span class="tag" style="color:${{meta.color}};background:${{meta.bg}}">${{bill.num}}</span>
          <span class="tag-sm" style="color:#7a8fa0;background:#1a2d3e">${{bill.chamber}}</span>
          <span class="tag-sm" style="color:${{meta.color}};background:${{meta.bg}}">${{meta.label}}</span>
          <span class="pbp-badge ${{pbpC[bill.pbp]}}">${{pbpL[bill.pbp]}}</span>
        </div>
        <div class="card-links">
          <a href="${{bill.pdfUrl}}" target="_blank" rel="noopener noreferrer" class="btn-link btn-text">Bill Text ↗</a>
        </div>
      </div>
      <div class="card-title">${{bill.title}}</div>
      <div class="card-desc">${{bill.desc}}</div>
      ${{changesHtml}}
      <div class="card-meta">
        <span><em>Introduced </em>${{bill.introduced}}</span>
        <span><em>Status </em>${{bill.status}}</span>
        <span><em>Sponsor </em>${{bill.sponsor}}</span>
      </div>`;
    el.appendChild(card);
  }});
}}

function setActive(type) {{
  activeType=type;
  buildPie(type); buildLegend(type); buildBadge(type); buildCards(type);
}}
setActive(null);
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Fetching {SOURCE_URL} ...")
    try:
        html = fetch_page(SOURCE_URL)
        print(f"  Downloaded {len(html):,} bytes")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        print("Could not reach Para Bellum Provisions. Check the URL or your network.")
        raise SystemExit(1)

    print("Parsing bills...")
    bills = scrape_bills(html)

    if not bills:
        print("WARNING: No bills found. The page structure may have changed.")
        print("Check parabellumprovisions.com manually and update the parser if needed.")
        raise SystemExit(1)

    print(f"\nSummary:")
    counts = count_by_type(bills)
    for btype, count in counts.items():
        print(f"  {btype:12s}: {count}")
    print(f"  {'total':12s}: {len(bills)}")

    print("\nGenerating index.html...")
    html_out = generate_html(bills)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_out)
    print("✓ index.html written successfully")
    print(f"  Source: {SOURCE_URL}")
    print(f"  Bills:  {len(bills)}")
    print(f"  Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
