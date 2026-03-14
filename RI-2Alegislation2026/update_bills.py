#!/usr/bin/env python3
"""
update_bills.py
Fetches Rhode Island firearms bills from the LegiScan API
and regenerates index.html with up-to-date data.

Required env var: LEGISCAN_API_KEY
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

API_KEY = os.environ["LEGISCAN_API_KEY"]
BASE_URL = "https://api.legiscan.com/"

FIREARM_KEYWORDS = [
    "firearm", "firearms", "gun", "guns", "weapon", "weapons",
    "ammunition", "ammo", "pistol", "rifle", "shotgun",
    "concealed carry", "assault weapon", "ghost gun",
]

TYPE_RULES = {
    "restriction": [
        "ban", "prohibit", "restrict", "limit", "require", "registration",
        "background check", "waiting period", "accountability", "liability",
        "do-not-sell", "red flag", "storage", "microstamp", "bump stock",
        "assault weapon", "ghost gun",
    ],
    "expansion": [
        "reciprocity", "permitless", "constitutional carry", "repeal",
        "expand rights", "allow", "authorize carry",
    ],
    "mixed": [
        "stun gun", "taser", "penalty", "transfer", "regulatory",
    ],
}

def api_call(op, params=None):
    """Make a LegiScan API call and return parsed JSON."""
    query = {"key": API_KEY, "op": op}
    if params:
        query.update(params)
    url = BASE_URL + "?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())

def get_ri_session_id():
    """Get the current Rhode Island legislative session ID."""
    data = api_call("getSessionList", {"state": "RI"})
    sessions = data.get("sessions", [])
    # Find the most recent active session
    for s in sorted(sessions, key=lambda x: x.get("year_start", 0), reverse=True):
        if s.get("special", 0) == 0:  # regular session
            return s["session_id"], s.get("year_start", "")
    return sessions[0]["session_id"], "" if sessions else (None, "")

def is_firearms_bill(title, description=""):
    """Return True if bill appears to be firearms-related."""
    text = (title + " " + description).lower()
    return any(kw in text for kw in FIREARM_KEYWORDS)

def classify_bill(title, description=""):
    """Classify a bill as restriction, expansion, or mixed."""
    text = (title + " " + description).lower()
    scores = {t: 0 for t in TYPE_RULES}
    for btype, keywords in TYPE_RULES.items():
        for kw in keywords:
            if kw in text:
                scores[btype] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "mixed"

def get_bill_detail(bill_id):
    """Fetch full bill detail including sponsor and status."""
    data = api_call("getBill", {"id": bill_id})
    return data.get("bill", {})

def fetch_firearms_bills():
    """Search LegiScan for RI firearms bills and return structured list."""
    session_id, year = get_ri_session_id()
    print(f"Using RI session {session_id} ({year})")

    results = []
    seen_ids = set()

    for keyword in ["firearm", "gun", "weapon", "concealed carry", "assault weapon"]:
        print(f"  Searching: '{keyword}'")
        try:
            data = api_call("getSearch", {
                "state": "RI",
                "query": keyword,
                "year": 2,  # current session
            })
            search_results = data.get("searchresult", {})
            for key, bill in search_results.items():
                if key == "summary":
                    continue
                bill_id = bill.get("bill_id")
                if not bill_id or bill_id in seen_ids:
                    continue
                title = bill.get("title", "")
                if not is_firearms_bill(title):
                    continue
                seen_ids.add(bill_id)
                results.append(bill)
        except Exception as e:
            print(f"  Warning: search for '{keyword}' failed: {e}")

    print(f"Found {len(results)} candidate bills, fetching details...")

    bills = []
    for b in results:
        try:
            detail = get_bill_detail(b["bill_id"])
            if not detail:
                continue

            num = detail.get("bill_number", "")
            chamber = "Senate" if num.startswith("S") else "House"
            title = detail.get("title", "No title")
            description = detail.get("description", "")
            btype = classify_bill(title, description)

            # Sponsor
            sponsors = detail.get("sponsors", [])
            sponsor_name = sponsors[0].get("name", "Unknown") if sponsors else "Unknown"
            sponsor_party = sponsors[0].get("party", "") if sponsors else ""
            sponsor_str = f"{sponsor_party} — {sponsor_name}" if sponsor_party else sponsor_name
            if len(sponsors) > 1:
                sponsor_str += f" (+{len(sponsors)-1} co-sponsors)"

            # Status
            progress = detail.get("progress", [])
            status = "Introduced"
            for p in reversed(progress):
                if p.get("event"):
                    status = p["event"]
                    break

            # Dates
            introduced = detail.get("status_date", "")[:10] if detail.get("status_date") else ""

            # URLs
            legiscan_url = f"https://legiscan.com/RI/bill/{num}/{year}"
            year_short = str(year)[-2:] if year else "26"
            senate_or_house = "SenateText" if chamber == "Senate" else "HouseText"
            pdf_url = f"https://webserver.rilegislature.gov/BillText{year_short}/{senate_or_house}{year_short}/{num}.pdf"

            bills.append({
                "num": num,
                "chamber": chamber,
                "type": btype,
                "title": title,
                "desc": description or title,
                "status": status,
                "introduced": introduced,
                "legiscanUrl": legiscan_url,
                "pdfUrl": pdf_url,
                "sponsor": sponsor_str,
            })
            print(f"  ✓ {num}: {title[:60]}")
        except Exception as e:
            print(f"  ✗ Failed to process bill {b.get('bill_id')}: {e}")

    # Sort by bill number
    bills.sort(key=lambda x: x["num"])
    return bills, year

def count_by_type(bills):
    counts = {"restriction": 0, "expansion": 0, "mixed": 0}
    for b in bills:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    return counts

def generate_html(bills, year):
    """Render the full standalone HTML page with updated bill data."""
    counts = count_by_type(bills)
    total = len(bills)
    updated = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

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
  <title>Rhode Island {year} — Firearms Legislation</title>
  <meta name="description" content="Interactive breakdown of all confirmed firearms bills introduced in the Rhode Island {year} legislative session." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0d1520; color: #e8edf2;
      font-family: 'DM Sans', sans-serif;
      min-height: 100vh; padding: 40px 20px 80px;
    }}
    a {{ text-decoration: none; }}
    .wrap {{ max-width: 820px; margin: 0 auto; }}
    .eyebrow {{ text-align:center; font-size:10px; letter-spacing:4px; color:#c0392b; text-transform:uppercase; margin-bottom:10px; }}
    h1 {{ font-family:'Playfair Display',serif; font-size:clamp(22px,5vw,36px); font-weight:700; text-align:center; color:#e8edf2; line-height:1.2; margin-bottom:8px; }}
    .subtitle {{ text-align:center; color:#566778; font-size:12.5px; margin-bottom:4px; }}
    .updated {{ text-align:center; color:#3a5060; font-size:11px; margin-bottom:36px; }}
    .pie-row {{ display:flex; gap:32px; align-items:center; justify-content:center; flex-wrap:wrap; margin-bottom:36px; }}
    #pie-svg {{ overflow:visible; display:block; cursor:pointer; }}
    .legend {{ display:flex; flex-direction:column; gap:10px; min-width:200px; }}
    .legend-item {{ display:flex; align-items:center; gap:12px; cursor:pointer; padding:10px 14px; border-radius:8px; border:1px solid transparent; transition:all 0.2s ease; }}
    .legend-dot {{ width:14px; height:14px; border-radius:4px; flex-shrink:0; }}
    .legend-label {{ font-size:13px; color:#a0b8cc; font-weight:500; transition:color 0.2s; }}
    .legend-sub {{ font-size:11px; color:#566778; }}
    .legend-count {{ font-size:20px; font-weight:700; }}
    #filter-badge {{ text-align:center; margin-bottom:18px; min-height:28px; }}
    .badge {{ display:inline-block; font-size:12px; padding:4px 14px; border-radius:20px; border:1px solid; }}
    .badge .clear {{ cursor:pointer; text-decoration:underline; }}
    #bill-list {{ display:flex; flex-direction:column; gap:10px; }}
    .bill-card {{ border-radius:10px; padding:14px 16px; transition:all 0.25s ease; border-left-width:3px; border-left-style:solid; border-top:1px solid; border-right:1px solid; border-bottom:1px solid; }}
    .bill-card.dimmed {{ opacity:0.35; }}
    .card-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; margin-bottom:6px; flex-wrap:wrap; }}
    .card-tags {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .tag {{ font-family:monospace; font-weight:800; font-size:13px; padding:2px 8px; border-radius:5px; letter-spacing:0.5px; }}
    .tag-sm {{ font-size:10px; padding:2px 7px; border-radius:4px; letter-spacing:1px; text-transform:uppercase; }}
    .card-links {{ display:flex; gap:8px; flex-shrink:0; }}
    .btn-link {{ font-size:10px; padding:3px 8px; border-radius:4px; letter-spacing:0.5px; font-weight:600; white-space:nowrap; transition:opacity 0.15s; }}
    .btn-link:hover {{ opacity:0.75; }}
    .btn-legiscan {{ color:#4a9fd4; background:#4a9fd420; }}
    .btn-pdf {{ color:#a0b0c0; background:#1a2d3e; }}
    .card-title {{ font-family:'Playfair Display',serif; font-size:14px; color:#d8e8f2; margin-bottom:6px; line-height:1.4; }}
    .card-desc {{ font-size:12px; color:#8fa8bc; line-height:1.6; margin-bottom:8px; }}
    .card-meta {{ display:flex; gap:16px; flex-wrap:wrap; }}
    .card-meta span {{ font-size:11px; color:#566778; }}
    .card-meta em {{ color:rgba(74,159,212,0.4); font-style:normal; }}
    .note {{ margin-top:32px; padding:14px 18px; background:#121e2b; border-radius:8px; border-left:3px solid #1e3a55; font-size:11.5px; color:#4a6070; line-height:1.7; }}
    .note strong {{ color:#4a9fd4; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Rhode Island · {year} Session</div>
  <h1>Firearms Legislation</h1>
  <p class="subtitle">{total} confirmed bills · Auto-updated via LegiScan API</p>
  <p class="updated">Last updated: {updated}</p>
  <div class="pie-row">
    <svg id="pie-svg" width="220" height="220" viewBox="0 0 220 220"></svg>
    <div class="legend" id="legend"></div>
  </div>
  <div id="filter-badge"></div>
  <div id="bill-list"></div>
  <div class="note">
    <strong>Sources &amp; Methodology: </strong>
    Bills fetched automatically from the LegiScan API and the RI Legislature's official webserver.
    Classification (restriction / expansion / mixed) is determined by keyword analysis of bill titles and descriptions.
    PDF links point to official RI Legislature bill text. Session ongoing — this page updates weekly.
    Hover or tap the pie chart or legend to filter by type.
  </div>
</div>
<script>
const BILLS = {bills_json};
const PIE_DATA = {pie_json};
const TOTAL = BILLS.length;
const TYPE_META = {{
  restriction: {{ label: "Restriction / Control", color: "#c0392b", bg: "rgba(192,57,43,0.13)" }},
  expansion:   {{ label: "Expansion of Rights",   color: "#2eab7a", bg: "rgba(46,171,122,0.13)" }},
  mixed:       {{ label: "Mixed / Regulatory",     color: "#e8a838", bg: "rgba(232,168,56,0.13)" }},
}};
let activeType = null;

function buildPie(active) {{
  const svg = document.getElementById('pie-svg');
  svg.innerHTML = '';
  const cx=110, cy=110, r=82, ir=44;
  let angle = -Math.PI/2;
  PIE_DATA.forEach(d => {{
    const frac = d.count/TOTAL, start=angle, end=angle+frac*2*Math.PI;
    angle=end;
    const mid=(start+end)/2, isAct=active===d.type;
    const outerR=isAct?r+10:r, ox=isAct?Math.cos(mid)*6:0, oy=isAct?Math.sin(mid)*6:0;
    const largeArc=frac>0.5?1:0;
    const pt=(rad,a)=>[cx+ox+rad*Math.cos(a),cy+oy+rad*Math.sin(a)];
    const [x1,y1]=pt(outerR,start),[x2,y2]=pt(outerR,end);
    const [ix1,iy1]=pt(ir,start),[ix2,iy2]=pt(ir,end);
    const pathD=`M ${{ix1}} ${{iy1}} L ${{x1}} ${{y1}} A ${{outerR}} ${{outerR}} 0 ${{largeArc}} 1 ${{x2}} ${{y2}} L ${{ix2}} ${{iy2}} A ${{ir}} ${{ir}} 0 ${{largeArc}} 0 ${{ix1}} ${{iy1}} Z`;
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',pathD); path.setAttribute('fill',d.color);
    path.setAttribute('stroke','#0d1520'); path.setAttribute('stroke-width','1.5');
    path.style.cursor='pointer'; path.style.transition='all 0.25s cubic-bezier(.34,1.56,.64,1)';
    path.style.filter=isAct?`drop-shadow(0 3px 10px ${{d.color}}99)`:'none';
    path.addEventListener('mouseenter',()=>setActive(d.type));
    path.addEventListener('mouseleave',()=>setActive(null));
    path.addEventListener('click',()=>setActive(activeType===d.type?null:d.type));
    svg.appendChild(path);
  }});
  const makeText=(txt,y,sz,fill,w)=>{{
    const t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',cx);t.setAttribute('y',y);t.setAttribute('text-anchor','middle');
    t.setAttribute('fill',fill);t.style.fontSize=sz+'px';t.style.fontWeight=w;
    t.style.fontFamily="'Playfair Display',serif";t.textContent=txt;svg.appendChild(t);
  }};
  makeText(TOTAL,cy+8,28,'#e8edf2',700);
  const sub=document.createElementNS('http://www.w3.org/2000/svg','text');
  sub.setAttribute('x',cx);sub.setAttribute('y',cy+26);sub.setAttribute('text-anchor','middle');
  sub.setAttribute('fill','#7a8fa0');sub.style.fontSize='10px';
  sub.style.fontFamily="'DM Sans',sans-serif";sub.style.letterSpacing='1.5px';
  sub.textContent='BILLS';svg.appendChild(sub);
}}

function buildLegend(active) {{
  const el=document.getElementById('legend'); el.innerHTML='';
  PIE_DATA.forEach(d=>{{
    const meta=TYPE_META[d.type], isAct=active===d.type;
    const item=document.createElement('div');
    item.className='legend-item';
    item.style.background=isAct?meta.bg:'transparent';
    item.style.borderColor=isAct?meta.color+'55':'transparent';
    item.innerHTML=`<div class="legend-dot" style="background:${{d.color}}"></div>
      <div style="flex:1"><div class="legend-label" style="color:${{isAct?'#e8edf2':'#a0b8cc'}}">${{meta.label}}</div>
      <div class="legend-sub">${{d.count}} bill${{d.count!==1?'s':''}} · ${{Math.round(d.count/TOTAL*100)}}%</div></div>
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
  const meta=TYPE_META[active], count=BILLS.filter(b=>b.type===active).length;
  el.innerHTML=`<span class="badge" style="color:${{meta.color}};background:${{meta.bg}};border-color:${{meta.color}}44">
    Showing: ${{meta.label}} &middot; ${{count}} bill${{count!==1?'s':''}}
    &nbsp;&middot;&nbsp;<span class="clear" id="clear-filter">clear filter</span></span>`;
  document.getElementById('clear-filter').addEventListener('click',()=>setActive(null));
}}

function buildCards(active) {{
  const el=document.getElementById('bill-list'); el.innerHTML='';
  BILLS.forEach(bill=>{{
    const meta=TYPE_META[bill.type], highlighted=!active||bill.type===active;
    const card=document.createElement('div');
    card.className='bill-card'+(highlighted?'':' dimmed');
    card.style.borderLeftColor=meta.color;
    card.style.borderTopColor=highlighted?meta.color+'55':'#1e3045';
    card.style.borderRightColor=highlighted?meta.color+'55':'#1e3045';
    card.style.borderBottomColor=highlighted?meta.color+'55':'#1e3045';
    card.style.background=highlighted?meta.bg:'#121e2b';
    card.innerHTML=`
      <div class="card-top">
        <div class="card-tags">
          <span class="tag" style="color:${{meta.color}};background:${{meta.bg}}">${{bill.num}}</span>
          <span class="tag-sm" style="color:#7a8fa0;background:#1a2d3e">${{bill.chamber}}</span>
          <span class="tag-sm" style="color:${{meta.color}};background:${{meta.bg}}">${{meta.label}}</span>
        </div>
        <div class="card-links">
          <a href="${{bill.legiscanUrl}}" target="_blank" rel="noopener noreferrer" class="btn-link btn-legiscan">LegiScan ↗</a>
          <a href="${{bill.pdfUrl}}" target="_blank" rel="noopener noreferrer" class="btn-link btn-pdf">PDF ↗</a>
        </div>
      </div>
      <div class="card-title">${{bill.title}}</div>
      <div class="card-desc">${{bill.desc}}</div>
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

if __name__ == "__main__":
    print("Fetching RI firearms bills from LegiScan...")
    bills, year = fetch_firearms_bills()
    print(f"\nTotal firearms bills found: {len(bills)}")
    html = generate_html(bills, year)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✓ index.html written successfully")
