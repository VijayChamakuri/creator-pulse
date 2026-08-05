"""
report.py — LLM NARRATIVE + QA PASS
===================================
Pass 1: a STRUCTURED-OUTPUT call to Claude (tool_use with a fixed JSON schema)
        turns the analysis dict into a plain-English creator-facing report.
Pass 2: a second Claude call QAs every number in the draft against the source
        analysis and returns a pass/fail with a list of any mismatches.

Design choices that matter here:
  - Structured output (not free text) so the renderer gets predictable fields.
  - The model is instructed to write for a creator/account lead, no jargon, and
    to NEVER imply access to private analytics — owner-only figures are labeled
    synthetic in the prompt and must be described as estimates.
  - Fully degrades: if use_llm is false or the API is unreachable, a
    deterministic template produces the same schema so the pipeline never fails.

Uses only the stdlib (urllib) to call the API — no SDK dependency.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"

# JSON schema the narrative must conform to (enforced via tool_use).
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One-line summary of the week."},
        "summary": {"type": "string", "description": "2-4 plain-English sentences an account lead can read aloud."},
        "what_was_tested": {"type": "array", "items": {"type": "string"},
                            "description": "Bullets on the A/B tests run this window."},
        "what_worked": {"type": "array", "items": {"type": "string"}},
        "what_to_do_next": {"type": "array", "items": {"type": "string"}},
        "flagged_trends": {"type": "array", "items": {"type": "string"}},
        "anomalies": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "summary", "what_was_tested", "what_worked",
                 "what_to_do_next", "flagged_trends", "anomalies"],
}

SYSTEM = (
    "You are an analyst on a creator customer-success team writing the weekly "
    "creator report for a YouTube channel. Your reader is an account lead who will "
    "put this in front of the creator. Write in plain English: concise, concrete, "
    "no analyst jargon, no hedging. Never imply access to the creator's private "
    "YouTube Studio analytics. Impressions, CTR, retention, traffic sources, "
    "demographics and A/B tests in the data are SYNTHETIC estimates — describe them "
    "as modelled estimates, not measured facts. Public view/like/comment counts are "
    "real. Only state numbers that appear in the provided data. "
    "For A/B tests, a 'winner' or 'loser' is ONLY a test whose `outcome` field says "
    "so — these already require both statistical significance AND a minimum effect "
    "size. Never call a test a winner on significance alone. Use "
    "ab_tests.summary.winners as the winner count in the headline, and ensure the "
    "winners you name match that count; describe `inconclusive (small effect)` tests "
    "as too small to call, not as wins."
)


def _call_claude(model, system, messages, tools=None, tool_choice=None, max_tokens=1500):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def generate_report(analysis: dict, cfg) -> dict:
    """Returns {'report': <schema dict>, 'qa': <qa dict>, 'engine': str}."""
    if not cfg["report"].get("use_llm", True):
        rep = _template_report(analysis)
        return {"report": rep, "qa": _local_qa(rep, analysis), "engine": "template"}
    try:
        rep = _llm_narrative(analysis, cfg)
        qa = _llm_qa(rep, analysis, cfg)
        return {"report": rep, "qa": qa, "engine": "claude:" + cfg["report"]["model"]}
    except Exception as exc:  # noqa: BLE001
        print(f"[report] LLM path failed ({exc}); using deterministic template.")
        rep = _template_report(analysis)
        return {"report": rep, "qa": _local_qa(rep, analysis), "engine": "template-fallback"}


# ---------------------------------------------------------------------------
# Pass 1 — structured narrative
# ---------------------------------------------------------------------------
def _llm_narrative(analysis: dict, cfg) -> dict:
    tool = {"name": "emit_weekly_report",
            "description": "Emit the structured weekly creator report.",
            "input_schema": REPORT_SCHEMA}
    user = (
        "Here is the analysis for this week's creator report as JSON. The exact "
        "provenance of every field is in `data_provenance` and `_note` — follow it "
        "precisely. In weekly_metrics ONLY real_public_views and videos_published are "
        "real; impressions, ctr_pct, avg_view_duration_sec, avg_view_pct, "
        "unique_viewers, subscribers_gained and subscribers_total are modelled "
        "estimates. Retention, traffic, demographics, geography and A/B tests are "
        "synthetic. Write the report for the account lead, grounding every claim in "
        "these numbers and labelling modelled figures as modelled.\n\n"
        f"```json\n{json.dumps(analysis, indent=2, default=str)}\n```"
    )
    resp = _call_claude(
        cfg["report"]["model"], SYSTEM,
        [{"role": "user", "content": user}],
        tools=[tool], tool_choice={"type": "tool", "name": "emit_weekly_report"},
        max_tokens=1800,
    )
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_weekly_report":
            return block["input"]
    raise RuntimeError("model did not return the structured tool call")


# ---------------------------------------------------------------------------
# Pass 2 — numeric QA of the draft against source data
# ---------------------------------------------------------------------------
QA_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "pass_with_notes", "fail"]},
        "checked_claims": {"type": "integer"},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"}, "problem": {"type": "string"}},
            "required": ["claim", "problem"]}},
        "notes": {"type": "string"},
    },
    "required": ["verdict", "checked_claims", "issues", "notes"],
}


def _llm_qa(report: dict, analysis: dict, cfg) -> dict:
    tool = {"name": "emit_qa", "description": "Emit QA result for the draft report.",
            "input_schema": QA_SCHEMA}
    system = ("You are a meticulous fact-checker. Given a draft report and the source "
              "data it was built from, verify every numeric or factual claim in the "
              "draft appears in or follows from the source. Flag any number that is "
              "wrong, invented, or misattributes synthetic data as real. Be strict.")
    user = ("SOURCE DATA:\n```json\n" + json.dumps(analysis, indent=2, default=str)
            + "\n```\n\nDRAFT REPORT:\n```json\n" + json.dumps(report, indent=2)
            + "\n```\n\nCheck the draft against the source and emit the QA result.")
    resp = _call_claude(cfg["report"]["model"], system,
                        [{"role": "user", "content": user}],
                        tools=[tool], tool_choice={"type": "tool", "name": "emit_qa"},
                        max_tokens=1200)
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "emit_qa":
            return block["input"]
    raise RuntimeError("QA model did not return structured result")


# ---------------------------------------------------------------------------
# Deterministic fallbacks (no network) — same schema
# ---------------------------------------------------------------------------
def _template_report(a: dict) -> dict:
    wow = a.get("wow_deltas", {})
    v = wow.get("real_public_views", {})
    ab = a.get("ab_tests", {}).get("summary", {})
    tests = a.get("ab_tests", {}).get("tests", [])
    winners = [t for t in tests if t["outcome"] == "winner"]
    ret = a.get("retention", {})

    def d(m):
        x = wow.get(m, {}).get("delta_pct")
        return f"{x:+.1f}%" if isinstance(x, (int, float)) else "n/a"

    headline = (f"{a['channel']}: public views {d('real_public_views')} week-over-week, "
                f"{ab.get('winners', 0)} winning test(s) this window.")
    summary = (
        f"This week {a['channel']}'s published videos drew "
        f"{_fmt(v.get('current'))} real public views, {d('real_public_views')} versus the "
        f"prior week. Modelled CTR moved {d('ctr_pct')} and modelled average view "
        f"duration {d('avg_view_duration_sec')}. All impressions, CTR, retention and "
        f"A/B figures are synthetic estimates, not the creator's private analytics."
    )
    what_tested = [
        f"{t['element'].title()} test on “{_short(t['video_title'])}”: "
        f"variant '{t['variant']}' vs current (modelled CTR {t['ctr_control_pct']}% → "
        f"{t['ctr_variant_pct']}%, lift {t['lift_pct']:+.1f}%)."
        for t in tests[:6]
    ] or ["No A/B tests logged this window."]
    # Show winners; keep the headline count and this list consistent. If there are
    # more than the cap, show the strongest and say "showing top N of M".
    cap = 6
    winners_sorted = sorted(winners, key=lambda t: t["lift_pct"], reverse=True)
    what_worked = [
        f"'{t['variant']}' {t['element']} won on “{_short(t['video_title'])}” "
        f"({t['lift_pct']:+.1f}% CTR lift — significant and above the "
        f"{a.get('ab_tests', {}).get('summary', {}).get('min_lift_pct', 5.0):.0f}% effect floor)."
        for t in winners_sorted[:cap]
    ]
    if len(winners_sorted) > cap:
        what_worked.append(f"…showing the top {cap} of {len(winners_sorted)} winners "
                           "(full list in the dashboard).")
    if not what_worked:
        what_worked = ["No test cleared both significance and the minimum effect size "
                       "this window; treat any leads as directional."]

    bd = ret.get("biggest_drop", {})
    if bd.get("from_pct") is not None:
        retention_step = (f"Tighten the section between {bd['from_pct']}% and {bd['to_pct']}% "
                          f"of video length, where retention falls most steeply "
                          f"(−{bd['drop_points']} points).")
    else:
        retention_step = "Review mid-video pacing to limit audience drop-off."
    next_steps = [
        "Roll winning packaging patterns into upcoming uploads and re-test to confirm.",
        retention_step,
        "Rerun the inconclusive and small-effect tests with more impressions before calling them.",
    ]
    trends = [f"{m.replace('_', ' ').title()} is {t['direction']} ({t['strength']}) over "
              f"the last {a['window_weeks']} weeks."
              for m, t in a.get("trends", {}).items() if t["direction"] != "flat"][:5] \
        or ["No strong trends over the window."]
    anomalies = [f"{an['metric'].replace('_', ' ')} {an['direction']} on {an['week_start']} "
                 f"(z={an['z_score']})" + ("" if an["metric"] == "real_public_views" else ", synthetic")
                 for an in a.get("anomalies", [])][:5] or ["No statistical anomalies flagged."]
    return {"headline": headline, "summary": summary, "what_was_tested": what_tested,
            "what_worked": what_worked, "what_to_do_next": next_steps,
            "flagged_trends": trends, "anomalies": anomalies}


def _local_qa(report: dict, analysis: dict) -> dict:
    """Deterministic sanity QA: confirm headline delta matches source."""
    issues = []
    src = analysis.get("wow_deltas", {}).get("real_public_views", {}).get("delta_pct")
    if src is not None and f"{src:+.1f}%" not in report["headline"] + report["summary"]:
        issues.append({"claim": "week-over-week view delta",
                       "problem": "headline/summary delta not found verbatim in source"})
    return {"verdict": "pass" if not issues else "pass_with_notes",
            "checked_claims": 1, "issues": issues,
            "notes": "Local deterministic QA (LLM QA unavailable)."}


def _fmt(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "n/a"


def _short(s, n=42):
    return s if len(s) <= n else s[: n - 1] + "…"
