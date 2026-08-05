# Key decisions & calibration (1 page)

## Why split real public data from a synthetic analytics layer

The single hardest constraint on this role is honesty about data provenance. The
metrics that make a creator report useful — impressions, CTR, average view
duration, retention curves, traffic sources, demographics, A/B outcomes — are
**owner-only** and live inside YouTube Studio. We don't have MKBHD's Studio, and
a tool that quietly implied we did would be both wrong and a liability the first
time someone asked "where did this number come from?"

So the pipeline is built around a hard wall:

- **Real public layer** (`ingest.py`): titles, publish dates, views, likes,
  comments, durations, thumbnails — genuinely pullable by anyone via yt-dlp or
  the YouTube Data API. Carries a `source` tag on every row.
- **Synthetic owner-only layer** (`synthesize.py`): everything private, generated
  and flagged `is_synthetic=True` on every row, and rendered with an amber
  "SYNTHETIC · modelled estimate" tag in the report and dashboard.

This keeps the report **useful** (it still talks about CTR, retention, and A/B
lift, which is what account leads actually need) while being **unambiguous** about
what's measured vs modelled. An account lead can hand the report to a creator and
defend every number: the green ones are real, the amber ones are clearly labeled
estimates.

The one deliberate coupling: synthetic **impressions are back-derived from real
views** (`impressions ≈ views ÷ CTR`). This keeps the modelled funnel internally
consistent with what actually happened that week, rather than floating free. It's
documented here and in code, not hidden.

## How the synthetic layer is calibrated

All knobs live in `config.yaml` so assumptions are inspectable and tunable, and
the run is deterministic (`seed: 42`) so a given week always reproduces. Ranges
were chosen to be **publicly plausible for an established tech channel**, not
precise:

| Metric | Range used | Rationale |
|---|---|---|
| CTR | ~6.5% mean (3–11% bounded) | YouTube's own guidance puts most channels' impressions CTR at ~2–10%; a strong, packaging-savvy tech channel sits in the upper half. |
| Avg view % | ~46% mean | Mid-length reviews (8–17 min) commonly retain ~40–55% on average. |
| Intro drop | ~22% lost by 30s | The first 30 seconds are where most audience loss happens; a well-edited channel limits it. |
| Gender split | 86% M / 12% F / 2% | Consumer-tech audiences skew heavily male; widely reported for the category. |
| Age | peak 18–34 (~69% combined) | Tech-review audiences concentrate in 18–34. |
| Geography | US ~34%, India ~11%, UK ~8%… | Typical English-language tech distribution; US-led with a large India tail. |
| Traffic | Browse 31% / Suggested 28% / Search 19%… | Browse + Suggested dominate discovery for established channels. |

These are stated as ranges with noise, not point claims about MKBHD. They exist
to make the report **shaped like reality** so the workflow, thresholds, and
narrative are exercised end to end — swap in real Studio exports and nothing else
changes.

## Analysis choices

- **WoW deltas** compare the latest completed publish-week to the prior one.
- **Trend detection** is an OLS slope over the window, normalized to a
  per-week fractional change and bucketed (mild/moderate/strong).
- **Anomalies** are flagged at |z| ≥ 2.0 on each weekly metric (configurable).
- **A/B significance requires both a p-value AND an effect size.** A test is only
  a `winner`/`loser` when it is statistically significant (two-proportion z-test,
  α = 0.05) **and** its relative CTR lift clears `min_lift_pct` (default 5%).
  Significance alone is not enough here: at the synthetic impression volumes
  (~80k–260k per arm), the z-test flags almost any difference as "significant" —
  a 0.1-point CTR wobble on 200k impressions is statistically real but
  operationally meaningless. Gating on effect size stops the report from
  over-claiming wins. Significant-but-below-threshold tests are labeled
  `inconclusive (small effect)` and counted separately, and the headline winner
  count uses this gated number so it stays honest. Tune the floor in
  `config.yaml → analysis.min_lift_pct`.
- **Retention drop-off** reports the intro drop, average retention, and the
  single biggest position-to-position fall, which is the actionable edit note.

## LLM usage

- **Report generation** is a **structured-output** call (Claude tool_use with a
  fixed JSON schema) so the renderer always gets predictable fields and the prose
  stays plain-English and jargon-free.
- **A second Claude pass QAs the numbers** in the draft against the source
  analysis and returns a verdict + issue list, which is printed on the report.
  This catches the classic failure mode of LLM narratives inventing or
  transposing figures.
- The system prompt forbids implying access to private analytics and instructs
  the model to describe synthetic metrics as estimates.
- Everything **degrades gracefully**: no key or `--no-llm` → a deterministic
  template produces the same schema, so the pipeline is always runnable.

## Deliberate scope limits (keeping it lightweight)

- **SQLite over a warehouse** — one file, zero setup, easy to inspect.
- **Static HTML dashboard over Streamlit** — opens in a browser with no server or
  process to babysit; more portable for a demo. (A Streamlit version would be a
  thin wrapper over the same `analyze.py` output if desired.)
- **stdlib `urllib` over the Anthropic SDK** — one fewer dependency for a tool
  whose whole selling point is "clone and run."
- **TF-IDF theme clustering over an embeddings API** — keeps the demo dependency-
  free; `themes.py` is written so a real embeddings call can drop in unchanged.
