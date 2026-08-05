# CreatorPulse — Automated Weekly YouTube Creator Report

**Turns a YouTube channel's real public data into a plain-English weekly report an account lead can hand straight to a creator — with an LLM-written narrative and a second LLM pass that fact-checks every number.**

### ▶ [**Live demo →**](https://VijayChamakuri.github.io/creator-pulse/) &nbsp;·&nbsp; [Weekly report](https://VijayChamakuri.github.io/creator-pulse/report.html) &nbsp;·&nbsp; [Interactive dashboard](https://VijayChamakuri.github.io/creator-pulse/dashboard.html)

![narrative](https://img.shields.io/badge/narrative-claude--sonnet--4.5-7c3aed) ![data](https://img.shields.io/badge/public%20data-yt--dlp%20(live)-22c55e) ![qa](https://img.shields.io/badge/automated%20QA-PASS-16a34a) ![python](https://img.shields.io/badge/python-3.9%2B-3776ab)

> Built by Vijay. MKBHD is my favorite YouTuber, so his channel is the default — the report and dashboard below are the **real, live-generated** output for `@mkbhd`.

---

## What it produces

The screenshots below are the actual generated output (channel: MKBHD, week of 2026-07-27). Click through to the [live demo](https://VijayChamakuri.github.io/creator-pulse/) to open them interactively.

### The weekly report — creator-facing, plain English

[![Weekly creator report](assets/report.png)](https://VijayChamakuri.github.io/creator-pulse/report.html)

**Real excerpt from the generated report** &nbsp; `engine: claude-sonnet-4-5` &nbsp; `QA verdict: PASS ✅`

> **“5 test winners this week; views fell 40% but modelled CTR jumped 51%.”**
>
> The latest video brought 2.96 million real views, down 40% from the prior week. Modelled impressions dropped 61% to 32.2 million, but modelled click-through rate climbed 51% to 9.18%, and modelled average view percentage rose 15% to 50.4%. Over the six-week window, five A/B tests hit winner thresholds and two were clear losers.
>
> **What worked**
> - Short-intro packaging test won with an 8.0% modelled CTR lift on the Framework laptop video.
> - Curiosity-gap title delivered an 18.4% modelled CTR lift on the Dope Tech video.
> - Bold-text thumbnail lifted 13.9% on the Xiaomi car video.

Every number in that narrative was **checked by a second Claude pass** against the source data before the report was published — that's the `QA verdict: PASS`.

### The interactive dashboard — dark mode, live charts

[![CreatorPulse dashboard (dark mode)](assets/dashboard-dark.png)](https://VijayChamakuri.github.io/creator-pulse/dashboard.html)

Dark/light toggle, KPI cards with week-over-week deltas, real views by week, modelled CTR trend, retention curve, gated A/B results, and traffic/audience breakdowns.

---

## The honest part (the differentiator)

A creator's **public** data — views, likes, comments, titles, dates — is pulled live via yt-dlp and marked <kbd>REAL</kbd> (green). Their **owner-only** analytics — impressions, CTR, retention, traffic sources, demographics, A/B tests — live inside YouTube Studio and **cannot be accessed publicly**, so CreatorPulse **generates** them, calibrated to publicly-plausible ranges, and marks them <kbd>SYNTHETIC</kbd> (amber) everywhere: in the report, the dashboard, and the code.

**The tool never implies access to private analytics.** The two layers are kept in physically separate database tables and are visibly labeled in every view. Field-level provenance is carried all the way into the LLM prompt, so the AI narrative — and the AI QA that checks it — can never confuse a real number for a modelled one. Full calibration and assumptions: [`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## How it works

```
 [yt-dlp / YouTube API / fixture]      [config.yaml calibration]
        │ REAL public                        │
        ▼                                     ▼
   ingest.py ─────────────────────►   synthesize.py   (labeled SYNTHETIC)
        │                                     │
        └───────────────┬─────────────────────┘
                        ▼
                    store.py   (SQLite: public_videos | syn_*)
                        ▼
                   analyze.py  (WoW deltas · trends · anomalies · retention · A/B significance + effect size)
                        ▼
     report.py  ── Claude structured output ──► narrative ──► Claude QA pass (verdict)
                        ▼
     render.py  ──►  report (HTML + PDF)   and   interactive dashboard
```

| Module | Role |
|---|---|
| `ingest.py` | REAL public layer: yt-dlp → YouTube API → offline fixture; records provenance |
| `synthesize.py` | SYNTHETIC owner-only layer: impressions, CTR, retention, traffic, demographics, A/B log |
| `store.py` | SQLite with `public_*` and `syn_*` tables kept physically separate |
| `analyze.py` | WoW deltas, trend + anomaly detection, retention drop-off, A/B significance **and** effect-size gating |
| `report.py` | Claude structured-output narrative + second-pass numeric QA (stdlib only, no SDK) |
| `render.py` | Creator-facing HTML/PDF report + static Chart.js dashboard |

---

## Run it yourself (one command)

```bash
pip install -r requirements.txt
python run.py
```

Outputs land in `reports/` (HTML + PDF) and `dashboard/index.html` — open in any browser, no server needed.

| Command | What it does |
|---|---|
| `python run.py` | Full pipeline; pulls **live** public data via yt-dlp |
| `python run.py --no-llm` | Skips the API; deterministic template narrative (nothing to configure) |
| `python run.py --fixture` | Forces the bundled offline sample dataset (CI / demos) |
| `python run.py --channel @handle` | Point it at any channel |

**LLM report + QA** (optional): put your key in a git-ignored `.env` —

```
ANTHROPIC_API_KEY=sk-ant-...
```

The report/QA calls use only the Python stdlib (no SDK). Without a key (or with `--no-llm`), a deterministic template produces the same report structure. **PDF export** is optional (`pip install weasyprint`); HTML is always produced.

---

*Public view/like/comment counts are real. Impressions, CTR, retention, traffic, demographics and A/B tests are synthetic modelled estimates — this project never uses a creator's private analytics.*
