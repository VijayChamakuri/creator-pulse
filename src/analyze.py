"""
analyze.py — ANALYSIS ENGINE
============================
Turns the stored tables into a compact, machine-readable `analysis` dict that
the report layer narrates. Pure pandas/numpy, no heavy stats deps.

Covers:
  - week-over-week deltas (views, impressions, CTR, avg view duration, subs)
  - trend detection (linear slope over the window, direction + strength)
  - statistical anomaly flagging (rolling z-score on weekly metrics)
  - retention drop-off (intro drop, plateau, biggest single drop)
  - A/B results (lift + two-proportion z-test significance)

Every A/B and owner-only figure it reports is derived from the SYNTHETIC layer
and is labeled as such in the output dict.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _pct_delta(cur, prev):
    if prev in (0, None) or pd.isna(prev):
        return None
    return round((cur - prev) / prev * 100, 1)


def _slope_direction(y: list[float]):
    """OLS slope over evenly-spaced weeks -> direction + normalized strength."""
    y = [v for v in y if v is not None and not pd.isna(v)]
    if len(y) < 3:
        return {"direction": "flat", "slope_per_week": 0.0, "strength": "insufficient-data"}
    x = np.arange(len(y))
    slope, _ = np.polyfit(x, y, 1)
    mean = np.mean(y) or 1
    norm = slope / mean  # fractional change per week
    direction = "rising" if norm > 0.01 else "falling" if norm < -0.01 else "flat"
    strength = ("strong" if abs(norm) > 0.08 else "moderate" if abs(norm) > 0.03 else "mild")
    return {"direction": direction, "slope_per_week": round(float(slope), 2),
            "strength": strength if direction != "flat" else "flat"}


def _two_prop_ztest(c_succ, c_n, v_succ, v_n, alpha):
    """Two-proportion z-test on CTR (clicks vs impressions)."""
    if min(c_n, v_n) == 0:
        return {"z": None, "p_value": None, "significant": False}
    p1, p2 = c_succ / c_n, v_succ / v_n
    pool = (c_succ + v_succ) / (c_n + v_n)
    se = math.sqrt(pool * (1 - pool) * (1 / c_n + 1 / v_n))
    if se == 0:
        return {"z": None, "p_value": None, "significant": False}
    z = (p2 - p1) / se
    p = 2 * (1 - _norm_cdf(abs(z)))
    return {"z": round(z, 2), "p_value": round(p, 4), "significant": p < alpha}


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def analyze(tables: dict, cfg) -> dict:
    wm = tables["syn_weekly_metrics"].sort_values("week_start").reset_index(drop=True)
    pub = tables["public_videos"]
    meta = tables["meta"].iloc[0].to_dict()
    window = cfg["report"]["weeks"]
    wm = wm.tail(window).reset_index(drop=True)

    # --- week-over-week deltas (latest vs prior) ----------------------------
    metrics = ["real_public_views", "impressions", "ctr_pct",
               "avg_view_duration_sec", "avg_view_pct", "subscribers_gained"]
    wow = {}
    if len(wm) >= 2:
        cur, prev = wm.iloc[-1], wm.iloc[-2]
        for m in metrics:
            wow[m] = {"current": _num(cur[m]), "previous": _num(prev[m]),
                      "delta_pct": _pct_delta(cur[m], prev[m])}

    # --- trend detection over the window ------------------------------------
    trends = {m: _slope_direction(list(wm[m])) for m in metrics}

    # --- anomaly flagging (z-score per metric) ------------------------------
    anomalies = []
    for m in metrics:
        series = wm[m].astype(float)
        mu, sd = series.mean(), series.std(ddof=0)
        if sd == 0 or pd.isna(sd):
            continue
        for _, row in wm.iterrows():
            z = (row[m] - mu) / sd
            if abs(z) >= cfg["analysis"]["anomaly_z"]:
                anomalies.append({
                    "week_start": row["week_start"], "metric": m,
                    "value": _num(row[m]), "z_score": round(float(z), 2),
                    "direction": "spike" if z > 0 else "dip",
                    "is_synthetic": m != "real_public_views",
                })

    # --- retention drop-off (latest week's videos) --------------------------
    retention = _retention_summary(tables["syn_retention"], wm)

    # --- A/B test results ---------------------------------------------------
    ab = _ab_summary(tables["syn_ab_tests"], cfg)

    # --- latest-week traffic + geography aggregates (for dashboard pies) -----
    latest_week = wm.iloc[-1]["week_start"] if len(wm) else None
    traffic_latest = _latest_pie(tables.get("syn_traffic_sources"), latest_week, "source")
    geo_latest = _latest_pie(tables.get("syn_geography"), latest_week, "country")

    # --- top public videos in window (real data) ----------------------------
    pub2 = pub.copy()
    pub2["publish_date"] = pd.to_datetime(pub2["publish_date"])
    recent = pub2.sort_values("view_count", ascending=False).head(5)
    top_videos = [{
        "title": r["title"], "publish_date": str(r["publish_date"].date()),
        "views": int(r["view_count"]),
        "likes": _num(r.get("like_count")), "comments": _num(r.get("comment_count")),
        "source": r["source"],
    } for _, r in recent.iterrows()]

    # weekly_metrics is a MIXED table: real_public_views + videos_published are
    # real (from the public pull); every other column is a modelled estimate.
    # Drop the row-level is_synthetic flag here so it never contradicts the
    # field-level provenance below (a blanket is_synthetic=1 on a row that also
    # holds real views is exactly the ambiguity the QA pass flags).
    wm_out = wm.drop(columns=[c for c in ["is_synthetic"] if c in wm.columns])

    real_weekly = ["real_public_views", "videos_published"]
    modelled_weekly = ["impressions", "ctr_pct", "avg_view_duration_sec",
                       "avg_view_pct", "unique_viewers", "subscribers_gained",
                       "subscribers_total"]

    return {
        "channel": meta["channel"],
        "public_source": meta["public_source"],
        "is_real_public_data": bool(meta["is_real_public_data"]),
        "window_weeks": int(len(wm)),
        "latest_week": wm.iloc[-1]["week_start"] if len(wm) else None,
        "weekly_metrics": wm_out.to_dict(orient="records"),
        "wow_deltas": wow,
        "trends": trends,
        "anomalies": anomalies,
        "retention": retention,
        "ab_tests": ab,
        "top_public_videos": top_videos,
        "traffic_latest": traffic_latest,
        "geo_latest": geo_latest,
        # Field-level provenance so real vs modelled is never ambiguous.
        "data_provenance": {
            "real_public_data": {
                "source": meta["public_source"],
                "weekly_metrics_fields": real_weekly,
                "also_real": ["top_public_videos (title, views, likes, comments, publish_date)"],
                "note": "Pulled from public YouTube; safe to state as fact.",
            },
            "synthetic_modelled": {
                "weekly_metrics_fields": modelled_weekly,
                "also_synthetic": ["retention", "traffic_latest", "geo_latest",
                                   "ab_tests", "anomalies flagged on modelled metrics"],
                "note": "Owner-only metrics not accessible publicly; calibrated "
                        "estimates. Describe as modelled, never as measured.",
            },
        },
        "_note": "In weekly_metrics ONLY real_public_views and videos_published are "
                 "REAL (from the public pull). impressions, ctr_pct, "
                 "avg_view_duration_sec, avg_view_pct, unique_viewers, "
                 "subscribers_gained and subscribers_total are SYNTHETIC modelled "
                 "estimates. Retention, traffic, demographics, geography and A/B "
                 "tests are entirely synthetic. See data_provenance.",
    }


def _latest_pie(df, week, key):
    if df is None or df.empty or week is None:
        return {}
    cur = df[df["week_start"] == week]
    if cur.empty:
        cur = df
    return {str(r[key]): round(float(r["pct"]), 1) for _, r in cur.iterrows()}


def _retention_summary(ret: pd.DataFrame, wm: pd.DataFrame) -> dict:
    if ret.empty:
        return {}
    latest_week = wm.iloc[-1]["week_start"] if len(wm) else ret["week_start"].max()
    cur = ret[ret["week_start"] == latest_week]
    if cur.empty:
        cur = ret
    curve = (cur.groupby("position_pct")["audience_retained_pct"].mean().round(1))
    positions = curve.index.tolist()
    vals = curve.values.tolist()
    intro = round(100 - curve.get(10, vals[2] if len(vals) > 2 else 100), 1)
    diffs = np.diff(vals)  # diffs[i] = retained[i+1] - retained[i] (negative = drop)
    biggest_drop = {}
    if len(diffs):
        # The steep intro fall (0->~10%) is expected and separately reported as
        # intro_drop_pct. For the actionable "tighten this section" note we want the
        # biggest drop-off in the INTERIOR of the video, so we look only at segments
        # starting at >=10% of length. Fall back to the global worst if none exist.
        interior = [i for i in range(len(diffs)) if positions[i] >= 10]
        worst_idx = min(interior, key=lambda i: diffs[i]) if interior else int(np.argmin(diffs))
        biggest_drop = {
            "from_pct": positions[worst_idx], "to_pct": positions[worst_idx + 1],
            "drop_points": round(float(-diffs[worst_idx]), 1),
        }
    return {
        "week_start": latest_week,
        "curve": [{"position_pct": p, "retained_pct": v} for p, v in zip(positions, vals)],
        "intro_drop_pct": intro,
        "avg_retention_pct": round(float(np.mean(vals)), 1),
        "biggest_drop": biggest_drop,
        "is_synthetic": True,
    }


def _ab_summary(ab: pd.DataFrame, cfg) -> dict:
    if ab.empty:
        return {"tests": [], "summary": {}}
    alpha = cfg["analysis"]["significance_alpha"]
    min_lift = float(cfg["analysis"].get("min_lift_pct", 5.0))
    out = []
    for _, t in ab.iterrows():
        c_n, v_n = int(t["impressions_control"]), int(t["impressions_variant"])
        c_clicks = int(round(c_n * t["ctr_control_pct"] / 100))
        v_clicks = int(round(v_n * t["ctr_variant_pct"] / 100))
        lift = round((t["ctr_variant_pct"] - t["ctr_control_pct"]) / t["ctr_control_pct"] * 100, 1)
        test = _two_prop_ztest(c_clicks, c_n, v_clicks, v_n, alpha)
        # A result must be BOTH significant AND clear the minimum effect size.
        # At large impression counts significance alone is nearly automatic, so it
        # cannot stand in for a decision-worthy effect.
        if test["significant"] and abs(lift) >= min_lift:
            outcome = "winner" if lift > 0 else "loser"
        elif test["significant"]:
            outcome = "inconclusive (small effect)"
        else:
            outcome = "inconclusive"
        out.append({
            "test_id": t["test_id"], "week_start": t["week_start"],
            "video_title": t["video_title"], "element": t["element"],
            "variant": t["test_variant"],
            "ctr_control_pct": t["ctr_control_pct"], "ctr_variant_pct": t["ctr_variant_pct"],
            "lift_pct": lift, "p_value": test["p_value"],
            "significant": test["significant"],
            "meets_min_effect": bool(abs(lift) >= min_lift),
            "outcome": outcome,
            "is_synthetic": True,
        })
    n_win = sum(1 for t in out if t["outcome"] == "winner")
    n_lose = sum(1 for t in out if t["outcome"] == "loser")
    n_small = sum(1 for t in out if t["outcome"] == "inconclusive (small effect)")
    return {
        "tests": out,
        "summary": {"total": len(out), "winners": n_win, "losers": n_lose,
                    "small_effect": n_small,
                    "inconclusive": len(out) - n_win - n_lose - n_small,
                    "alpha": alpha, "min_lift_pct": min_lift, "is_synthetic": True},
    }


def _num(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        f = float(x)
        return int(f) if f.is_integer() else round(f, 2)
    except (TypeError, ValueError):
        return x
