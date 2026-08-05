"""
render.py — PRESENTATION
========================
Two outputs:
  1. A polished weekly report as self-contained HTML (and PDF if weasyprint is
     installed). Dark-mode aware, with staggered fade-in sections.
  2. A modern static dashboard (dashboard/index.html): Chart.js from CDN, data
     embedded at build time, a dark/light theme toggle (remembers your choice and
     follows the OS by default), Apple-style scroll-reveal animations, and KPI
     count-ups. Open it in a browser — no server required.

Both make the REAL vs SYNTHETIC boundary explicit: real public data is tagged
green; every synthetic panel carries an amber "SYNTHETIC — modelled estimate" tag.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
DASH = ROOT / "dashboard"

BRAND = "CreatorPulse"
LOGO = (
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" '
    'style="vertical-align:-5px;margin-right:8px">'
    '<rect x="1" y="1" width="22" height="22" rx="6" fill="url(#g)"/>'
    '<path d="M4 12h3l2-5 3 10 2-6 1.5 2H20" stroke="#fff" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="24" y2="24">'
    '<stop stop-color="#7c3aed"/><stop offset="1" stop-color="#ec4899"/>'
    '</linearGradient></defs></svg>'
)

_SYN = '<span class="tag syn">SYNTHETIC · modelled estimate</span>'
_REAL = '<span class="tag real">REAL public data</span>'


def _ul(items):
    return "<ul>" + "".join(f"<li>{html.escape(str(i))}</li>" for i in items) + "</ul>"


# ===========================================================================
# REPORT (HTML + PDF)
# ===========================================================================
def render_report(report, qa, analysis, cfg, themes=None) -> dict:
    REPORTS.mkdir(parents=True, exist_ok=True)
    ch = analysis["channel"]
    week = analysis.get("latest_week", "")
    real_tag = _REAL if analysis["is_real_public_data"] else (
        '<span class="tag sample">SAMPLE FIXTURE · illustrative, not real metrics</span>')

    verdict = qa.get("verdict", "n/a")
    vcolor = {"pass": "#16a34a", "pass_with_notes": "#d97706", "fail": "#dc2626"}.get(verdict, "#6b7280")
    issues_html = ""
    if qa.get("issues"):
        issues_html = "<ul>" + "".join(
            f"<li><b>{html.escape(i.get('claim',''))}</b>: {html.escape(i.get('problem',''))}</li>"
            for i in qa["issues"]) + "</ul>"

    themes_html = ""
    if themes and themes.get("themes"):
        rows = "".join(
            f"<tr><td>{html.escape(', '.join(t['theme_terms']))}</td>"
            f"<td>{t['n_videos']}</td><td>{t['avg_views']:,}</td>"
            f"<td>{html.escape(t['example_title'])}</td></tr>"
            for t in themes["themes"])
        themes_html = f"""
        <section class="reveal"><h2>Title themes vs performance {_REAL}</h2>
        <p class="muted">{html.escape(themes['note'])}</p>
        <table><thead><tr><th>Theme terms</th><th>Videos</th><th>Avg views</th>
        <th>Example</th></tr></thead><tbody>{rows}</tbody></table></section>"""

    top = "".join(
        f"<tr><td>{html.escape(v['title'])}</td><td>{v['views']:,}</td>"
        f"<td>{v['publish_date']}</td></tr>" for v in analysis.get("top_public_videos", []))

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{BRAND} — Weekly Report · {html.escape(ch)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{{--brand1:#7c3aed;--brand2:#ec4899;--bg:#f4f4f7;--sheet:#fff;--ink:#1f2937;
   --muted:#6b7280;--line:#eef0f4;--lede:#faf5ff;--ledeb:#efe4ff;--th:#fafafc;--hover:#fcfaff}}
 @media (prefers-color-scheme: dark){{
  :root{{--bg:#0b0b0f;--sheet:#15151c;--ink:#e7e7ea;--muted:#9aa0aa;--line:#26262f;
    --lede:#1b1430;--ledeb:#2a2050;--th:#1b1b22;--hover:#1c1c24}}
 }}
 *{{box-sizing:border-box}}
 body{{font:16px/1.65 'Inter',-apple-system,Segoe UI,Roboto,Arial,sans-serif;
   color:var(--ink);margin:0;background:var(--bg);transition:background .4s,color .4s}}
 .sheet{{max-width:840px;margin:28px auto;background:var(--sheet);border-radius:16px;
   box-shadow:0 8px 30px rgba(0,0,0,.10);overflow:hidden}}
 .hero{{background:linear-gradient(120deg,var(--brand1),var(--brand2));
   background-size:180% 180%;animation:drift 14s ease infinite;color:#fff;padding:26px 34px}}
 @keyframes drift{{0%{{background-position:0% 50%}}50%{{background-position:100% 50%}}100%{{background-position:0% 50%}}}}
 .hero .brand{{font-weight:800;letter-spacing:.02em;font-size:15px;opacity:.95}}
 .hero h1{{margin:6px 0 2px;font-size:27px;font-weight:800}}
 .hero .meta{{opacity:.9;font-size:13px}}
 .body{{padding:8px 34px 30px}}
 section{{}}
 h2{{font-size:18px;font-weight:700;margin:26px 0 8px;display:flex;align-items:center;gap:10px}}
 h2::before{{content:"";width:9px;height:9px;border-radius:3px;
   background:linear-gradient(120deg,var(--brand1),var(--brand2))}}
 .muted{{color:var(--muted);font-size:14px}}
 .tags{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 6px}}
 .tag{{border-radius:999px;padding:3px 11px;font-size:11px;font-weight:700;letter-spacing:.02em}}
 .tag.real{{background:#dcfce7;color:#166534;border:1px solid #86efac}}
 .tag.syn{{background:#fef3c7;color:#92400e;border:1px solid #fcd34d}}
 .tag.sample{{background:#fee2e2;color:#991b1b;border:1px solid #fca5a5}}
 .headline{{font-size:19px;font-weight:700;margin:14px 0 4px}}
 .lede{{background:var(--lede);border:1px solid var(--ledeb);border-left:4px solid var(--brand1);
   border-radius:10px;padding:14px 18px;margin:10px 0}}
 ul{{margin:6px 0;padding-left:20px}} li{{margin:5px 0}}
 table{{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}}
 th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left}}
 th{{background:var(--th);font-weight:600}}
 tr:hover td{{background:var(--hover)}}
 .qa{{border:1px solid var(--line);border-left:4px solid {vcolor};border-radius:10px;
   padding:12px 16px;background:var(--th);margin:10px 0}}
 .disclose{{font-size:13px;color:var(--muted);background:var(--th);border:1px dashed var(--line);
   border-radius:10px;padding:10px 14px;margin:14px 0}}
 .foot{{color:var(--muted);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}}
 /* staggered entrance */
 .reveal{{opacity:0;transform:translateY(22px);
   animation:rise .7s cubic-bezier(.16,1,.3,1) forwards}}
 @keyframes rise{{to{{opacity:1;transform:none}}}}
 .body section:nth-of-type(1){{animation-delay:.05s}}
 .body section:nth-of-type(2){{animation-delay:.12s}}
 .body section:nth-of-type(3){{animation-delay:.19s}}
 .body section:nth-of-type(4){{animation-delay:.26s}}
 .body section:nth-of-type(5){{animation-delay:.33s}}
 .body section:nth-of-type(6){{animation-delay:.40s}}
 .body section:nth-of-type(7){{animation-delay:.47s}}
 .body section:nth-of-type(8){{animation-delay:.54s}}
 .body section:nth-of-type(9){{animation-delay:.61s}}
 @media (prefers-reduced-motion: reduce){{.reveal{{animation:none;opacity:1;transform:none}}.hero{{animation:none}}}}
</style></head><body>
<div class="sheet">
 <div class="hero">
   <div class="brand">{LOGO}{BRAND}</div>
   <h1>Weekly Creator Report — {html.escape(ch)}</h1>
   <div class="meta">Week of {week} · generated {datetime.now(timezone.utc):%Y-%m-%d} · engine: {html.escape(report.get('_engine','n/a'))}</div>
 </div>
 <div class="body">
   <section class="reveal">
     <div class="tags">{real_tag}{_SYN}</div>
     <div class="disclose">Public view / like / comment counts are <b>real</b>.
     Impressions, CTR, retention, traffic, demographics and A/B tests are
     <b>synthetic modelled estimates</b> — this report never uses the creator's
     private analytics.</div>
     <p class="headline">{html.escape(report['headline'])}</p>
     <div class="lede">{html.escape(report['summary'])}</div>
   </section>
   <section class="reveal"><h2>What we tested {_SYN}</h2>{_ul(report['what_was_tested'])}</section>
   <section class="reveal"><h2>What worked {_SYN}</h2>{_ul(report['what_worked'])}</section>
   <section class="reveal"><h2>What to do next</h2>{_ul(report['what_to_do_next'])}</section>
   <section class="reveal"><h2>Flagged trends</h2>{_ul(report['flagged_trends'])}</section>
   <section class="reveal"><h2>Anomalies</h2>{_ul(report['anomalies'])}</section>
   <section class="reveal"><h2>Top videos this window {_REAL}</h2>
   <table><thead><tr><th>Title</th><th>Views</th><th>Published</th></tr></thead>
   <tbody>{top}</tbody></table></section>
   {themes_html}
   <section class="reveal"><h2>Automated QA of the numbers</h2>
   <div class="qa"><b style="color:{vcolor}">Verdict: {verdict.upper()}</b>
    — {qa.get('checked_claims','?')} claims checked. {html.escape(qa.get('notes',''))}
    {issues_html}</div></section>

   <div class="foot">{BRAND} · automated weekly creator pipeline. Synthetic layer
   calibrated to publicly-plausible ranges (see DECISIONS.md). Public data source:
   {html.escape(analysis['public_source'])}. · Built by Vijay — MKBHD is my
   favorite YouTuber, so he's the default channel. 💜</div>
 </div>
</div>
</body></html>"""

    stub = ch.replace(" ", "_")
    html_path = REPORTS / f"weekly_report_{stub}_{week}.html"
    html_path.write_text(doc)

    pdf_path = None
    try:
        from weasyprint import HTML  # optional
        pdf_path = REPORTS / f"weekly_report_{stub}_{week}.pdf"
        HTML(string=doc).write_pdf(str(pdf_path))
    except Exception as exc:  # noqa: BLE001
        print(f"[render] PDF skipped ({type(exc).__name__}); HTML report written. "
              "Install weasyprint for PDF.")
    print(f"[render] report -> {html_path.name}" + (f" + {pdf_path.name}" if pdf_path else ""))
    return {"html": str(html_path), "pdf": str(pdf_path) if pdf_path else None}


# ===========================================================================
# DASHBOARD (interactive, dark mode + animations)
# ===========================================================================
def render_dashboard(analysis, themes=None) -> str:
    DASH.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"analysis": analysis, "themes": themes or {}}, default=str)
    doc = _DASH_TEMPLATE
    doc = (doc.replace("__PAYLOAD__", payload)
              .replace("__BRAND__", BRAND)
              .replace("__CH__", html.escape(analysis["channel"])))
    out = DASH / "index.html"
    out.write_text(doc)
    print(f"[render] dashboard -> {out.relative_to(ROOT)}")
    return str(out)


_DASH_TEMPLATE = r"""<!doctype html><html lang="en" data-theme="auto"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__BRAND__ Dashboard — __CH__</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
 :root{--brand1:#7c3aed;--brand2:#ec4899;
   --bg:#f4f4f7;--card:#ffffff;--ink:#111827;--muted:#6b7280;--line:#eef0f4;
   --grid:rgba(0,0,0,.06);--shadow:0 6px 20px rgba(17,24,39,.06)}
 html[data-theme="dark"]{--bg:#0b0b0f;--card:#15151c;--ink:#e7e7ea;--muted:#9aa0aa;
   --line:#26262f;--grid:rgba(255,255,255,.08);--shadow:0 8px 26px rgba(0,0,0,.5)}
 *{box-sizing:border-box}
 body{font:15px/1.5 'Inter',-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;
   background:var(--bg);color:var(--ink);transition:background .45s ease,color .45s ease}
 header{position:sticky;top:0;z-index:20;
   background:linear-gradient(120deg,var(--brand1),var(--brand2));
   background-size:200% 200%;animation:drift 16s ease infinite;color:#fff;
   padding:18px 26px;display:flex;align-items:center;justify-content:space-between;
   box-shadow:0 4px 20px rgba(124,58,237,.25)}
 @keyframes drift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
 header .brand{font-weight:800;font-size:14px;letter-spacing:.04em;opacity:.95}
 header h1{margin:4px 0 2px;font-size:22px;font-weight:800}
 header .sub{color:rgba(255,255,255,.85);font-size:13px}
 .toggle{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.35);
   color:#fff;border-radius:999px;padding:8px 14px;font:600 13px Inter,sans-serif;
   cursor:pointer;display:flex;gap:7px;align-items:center;transition:transform .2s,background .2s}
 .toggle:hover{background:rgba(255,255,255,.3);transform:translateY(-1px)}
 .wrap{max-width:1120px;margin:22px auto;padding:0 18px}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}
 .kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;
   box-shadow:var(--shadow);position:relative;overflow:hidden;transition:transform .3s cubic-bezier(.16,1,.3,1),box-shadow .3s}
 .kpi:hover{transform:translateY(-4px);box-shadow:0 14px 30px rgba(124,58,237,.18)}
 .kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;
   background:linear-gradient(var(--brand1),var(--brand2))}
 .kpi .v{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}
 .kpi .l{color:var(--muted);font-size:12px;font-weight:600}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;
   box-shadow:var(--shadow);transition:transform .3s cubic-bezier(.16,1,.3,1),box-shadow .3s}
 .panel:hover{transform:translateY(-3px);box-shadow:0 14px 30px rgba(0,0,0,.12)}
 .panel h3{margin:0 0 12px;font-size:15px;font-weight:700;display:flex;align-items:center}
 .tag{border-radius:999px;padding:2px 9px;font-size:10px;font-weight:800;margin-left:8px}
 .syn{background:#fef3c7;color:#92400e;border:1px solid #fcd34d}
 .real{background:#dcfce7;color:#166534;border:1px solid #86efac}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
 th{color:var(--muted);font-weight:600}
 .note{color:var(--muted);font-size:12px;margin-top:16px}
 /* scroll reveal */
 .reveal{opacity:0;transform:translateY(28px);
   transition:opacity .7s cubic-bezier(.16,1,.3,1),transform .7s cubic-bezier(.16,1,.3,1)}
 .reveal.in{opacity:1;transform:none}
 @media (prefers-reduced-motion: reduce){
   .reveal{opacity:1;transform:none;transition:none} header{animation:none}}
 @media(max-width:820px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header>
 <div>
   <div class="brand">◆ __BRAND__</div>
   <h1>Weekly Creator Dashboard</h1>
   <div class="sub" id="sub"></div>
 </div>
 <button class="toggle" id="themeToggle" aria-label="Toggle theme"><span id="ticon">🌙</span><span id="tlabel">Dark</span></button>
</header>
<div class="wrap">
 <div class="kpis reveal" id="kpis"></div>
 <div class="grid">
  <div class="panel reveal"><h3>Real public views by week <span class="tag real">REAL</span></h3><canvas id="views"></canvas></div>
  <div class="panel reveal"><h3>Modelled CTR by week <span class="tag syn">SYNTHETIC</span></h3><canvas id="ctr"></canvas></div>
  <div class="panel reveal"><h3>Retention curve, latest week <span class="tag syn">SYNTHETIC</span></h3><canvas id="ret"></canvas></div>
  <div class="panel reveal"><h3>A/B tests <span class="tag syn">SYNTHETIC</span></h3><div id="ab"></div></div>
  <div class="panel reveal"><h3>Traffic sources, latest week <span class="tag syn">SYNTHETIC</span></h3><canvas id="traffic"></canvas></div>
  <div class="panel reveal"><h3>Audience geography <span class="tag syn">SYNTHETIC</span></h3><canvas id="geo"></canvas></div>
 </div>
 <p class="note reveal">Public view/like/comment counts are real. All amber-tagged
 panels are synthetic modelled estimates — not the creator's private analytics.
 Built by Vijay · MKBHD is my favorite YouTuber. 💜</p>
</div>
<script>
const DATA = __PAYLOAD__;
const a = DATA.analysis, wm = a.weekly_metrics || [];
const $ = id => document.getElementById(id);
$('sub').textContent = a.channel + " · window " + a.window_weeks + " weeks · public source: " + a.public_source;
const fmt = n => (n==null?'n/a':Number(n).toLocaleString());
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ---- theme ---- */
const html = document.documentElement;
function systemDark(){return matchMedia('(prefers-color-scheme: dark)').matches;}
function applyTheme(t){
  const dark = t==='dark' || (t==='auto' && systemDark());
  html.setAttribute('data-theme', dark?'dark':'light');
  $('ticon').textContent = dark?'☀️':'🌙';
  $('tlabel').textContent = dark?'Light':'Dark';
  buildCharts(dark);
}
let theme = localStorage.getItem('cp-theme') || 'auto';
$('themeToggle').onclick = ()=>{
  const darkNow = html.getAttribute('data-theme')==='dark';
  theme = darkNow?'light':'dark';
  localStorage.setItem('cp-theme', theme);
  applyTheme(theme);
};

/* ---- KPI cards with count-up ---- */
const wow = a.wow_deltas || {};
const kpi = [
  ['Latest week views', wow.real_public_views?.current, wow.real_public_views?.delta_pct, 'REAL', 0],
  ['Modelled CTR %', wow.ctr_pct?.current, wow.ctr_pct?.delta_pct, 'SYN', 1],
  ['Modelled avg view (s)', wow.avg_view_duration_sec?.current, wow.avg_view_duration_sec?.delta_pct, 'SYN', 0],
  ['Subs gained (modelled)', wow.subscribers_gained?.current, wow.subscribers_gained?.delta_pct, 'SYN', 0],
];
$('kpis').innerHTML = kpi.map((k,i)=>{
  const d = (k[2]==null)?'':(k[2]>=0?'▲ +':'▼ ')+k[2]+'%';
  const tag = k[3]==='REAL'?'<span class="tag real">REAL</span>':'<span class="tag syn">SYN</span>';
  return `<div class=kpi><div class=l>${k[0]} ${tag}</div>
    <div class=v id="kpi${i}">${k[1]==null?'n/a':(k[4]?Number(k[1]).toFixed(1):'0')}</div>
    <div class=l style="color:${k[2]>=0?'#16a34a':'#dc2626'}">${d}</div></div>`;
}).join('');
function countUp(el, to, dec){
  if(to==null){el.textContent='n/a';return;}
  if(reduce){el.textContent = dec?Number(to).toFixed(1):fmt(Math.round(to));return;}
  const dur=1000, t0=performance.now();
  (function step(t){
    const p=Math.min(1,(t-t0)/dur), e=1-Math.pow(1-p,3), val=to*e;
    el.textContent = dec?val.toFixed(1):fmt(Math.round(val));
    if(p<1) requestAnimationFrame(step);
  })(t0);
}
kpi.forEach((k,i)=>countUp($('kpi'+i), k[1], k[4]));

/* ---- charts (rebuilt on theme change so colors match) ---- */
let charts=[];
function buildCharts(dark){
  charts.forEach(c=>c.destroy()); charts=[];
  const ink = dark?'#c9cdd6':'#374151', grid = dark?'rgba(255,255,255,.08)':'rgba(0,0,0,.06)';
  Chart.defaults.color = ink; Chart.defaults.font.family="Inter, sans-serif";
  const anim = reduce?false:{duration:900,easing:'easeOutQuart'};
  const axes = {x:{grid:{color:grid},ticks:{color:ink}},y:{grid:{color:grid},ticks:{color:ink}}};
  const weeks = wm.map(w=>w.week_start);
  charts.push(new Chart(views,{type:'bar',data:{labels:weeks,datasets:[{data:wm.map(w=>w.real_public_views),
    backgroundColor:'#22c55e',borderRadius:6}]},options:{animation:anim,plugins:{legend:{display:false}},scales:axes}}));
  charts.push(new Chart(ctr,{type:'line',data:{labels:weeks,datasets:[{data:wm.map(w=>w.ctr_pct),
    borderColor:'#ec4899',backgroundColor:'rgba(236,72,153,.15)',fill:true,tension:.35,pointRadius:2}]},
    options:{animation:anim,plugins:{legend:{display:false}},scales:axes}}));
  const rc=(a.retention?.curve)||[];
  charts.push(new Chart(ret,{type:'line',data:{labels:rc.map(p=>p.position_pct+'%'),datasets:[{data:rc.map(p=>p.retained_pct),
    borderColor:'#7c3aed',backgroundColor:'rgba(124,58,237,.18)',fill:true,tension:.25,pointRadius:0}]},
    options:{animation:anim,plugins:{legend:{display:false}},scales:{x:axes.x,y:{...axes.y,min:0,max:100}}}}));
  const pieOpt={animation:anim,plugins:{legend:{position:'right',labels:{color:ink,font:{size:11}}}}};
  if(a.traffic_latest) charts.push(new Chart(traffic,{type:'doughnut',
    data:{labels:Object.keys(a.traffic_latest),datasets:[{data:Object.values(a.traffic_latest),
    backgroundColor:['#7c3aed','#ec4899','#f59e0b','#22c55e','#3b82f6','#14b8a6','#94a3b8'],
    borderWidth:2,borderColor:dark?'#15151c':'#fff'}]},options:pieOpt}));
  if(a.geo_latest) charts.push(new Chart(geo,{type:'doughnut',
    data:{labels:Object.keys(a.geo_latest),datasets:[{data:Object.values(a.geo_latest),
    backgroundColor:['#ec4899','#7c3aed','#0ea5e9','#f97316','#84cc16','#a855f7','#94a3b8'],
    borderWidth:2,borderColor:dark?'#15151c':'#fff'}]},options:pieOpt}));
}
const tests=(a.ab_tests?.tests)||[];
$('ab').innerHTML = tests.length? (
 '<table><thead><tr><th>Video</th><th>Element</th><th>Variant</th><th>Lift</th><th>Outcome</th></tr></thead><tbody>'
 + tests.map(t=>`<tr><td>${(t.video_title||'').slice(0,24)}</td><td>${t.element}</td>
   <td>${t.variant}</td><td style="color:${t.lift_pct>=0?'#16a34a':'#dc2626'}">${t.lift_pct>0?'+':''}${t.lift_pct}%</td>
   <td><b>${t.outcome}</b></td></tr>`).join('') + '</tbody></table>') : 'No tests.';

/* ---- scroll reveal ---- */
const io = new IntersectionObserver((es)=>es.forEach((e,i)=>{
  if(e.isIntersecting){ setTimeout(()=>e.target.classList.add('in'), i*60); io.unobserve(e.target);}
}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>io.observe(el));

/* follow OS theme changes when in auto */
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{if(theme==='auto')applyTheme('auto');});
applyTheme(theme);
</script></body></html>"""
