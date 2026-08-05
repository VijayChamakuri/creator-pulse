"""
synthesize.py — SYNTHETIC OWNER-ONLY ANALYTICS LAYER
====================================================
Everything in this module is SYNTHETIC. These metrics (impressions, CTR,
retention, traffic sources, demographics, A/B tests) are owner-only in YouTube
Studio and cannot be pulled from public endpoints. We DO NOT have MKBHD's real
analytics and never imply that we do.

What we generate is calibrated to publicly-plausible ranges for an established
tech channel (see config.yaml + docs/DECISIONS.md for every assumption) and is
tagged `is_synthetic = True` on every row so it can never be confused with the
real public pull.

The one intentional coupling to reality: synthetic weekly impressions are
derived from the REAL public view counts (views ~= impressions x CTR), so the
made-up funnel stays internally consistent with what actually happened. That
relationship is documented, not hidden.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta

SYNTHETIC_FLAG = True  # stamped onto every record this module emits


def _iso_week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def synthesize(videos: list[dict], cfg) -> dict:
    s = cfg["synthetic"]
    rng = random.Random(s["seed"])

    # --- bucket real videos into ISO weeks -----------------------------------
    weeks = defaultdict(list)
    for v in videos:
        if not v.get("publish_date"):
            continue
        wk = _iso_week_start(date.fromisoformat(v["publish_date"]))
        weeks[wk].append(v)
    week_starts = sorted(weeks.keys())

    weekly_metrics, retention_curves, traffic, demographics, geo, ab_tests = ([] for _ in range(6))
    running_subs = rng.randint(19_600_000, 19_900_000)  # plausible mid-2026 base

    for wk in week_starts:
        vids = weeks[wk]
        week_views = sum(v.get("view_count") or 0 for v in vids)

        # CTR for the week (bounded normal draw).
        ctr = _clamp(rng.gauss(s["ctr"]["mean"], s["ctr"]["std"]),
                     s["ctr"]["floor"], s["ctr"]["ceil"])
        # Impressions implied by real views and this CTR (internally consistent).
        impressions = int(week_views / (ctr / 100.0)) if week_views else rng.randint(2_000_000, 5_000_000)

        avg_view_pct = _clamp(rng.gauss(s["avg_view_pct"]["mean"], s["avg_view_pct"]["std"]), 25, 70)
        avg_dur = [v.get("duration_sec") or 0 for v in vids]
        mean_len = sum(avg_dur) / len(avg_dur) if avg_dur else 600
        avg_view_duration = int(mean_len * avg_view_pct / 100.0)

        subs_gained = int(week_views * rng.uniform(0.004, 0.009))
        running_subs += subs_gained

        weekly_metrics.append({
            "week_start": wk.isoformat(),
            "videos_published": len(vids),
            "real_public_views": week_views,     # sourced from real pull
            "impressions": impressions,          # SYNTHETIC
            "ctr_pct": round(ctr, 2),            # SYNTHETIC
            "avg_view_duration_sec": avg_view_duration,  # SYNTHETIC
            "avg_view_pct": round(avg_view_pct, 1),      # SYNTHETIC
            "unique_viewers": int(impressions * rng.uniform(0.55, 0.72)),  # SYNTHETIC
            "subscribers_gained": subs_gained,   # SYNTHETIC
            "subscribers_total": running_subs,   # SYNTHETIC
            "is_synthetic": SYNTHETIC_FLAG,
        })

        # Retention curve per video (0..100% position -> % audience retained).
        for v in vids:
            intro = _clamp(rng.gauss(s["retention"]["intro_drop_pct"], 4), 10, 40)
            tail = _clamp(rng.gauss(s["retention"]["tail_floor_pct"], 5), 15, 55)
            for pos in range(0, 101, 5):
                if pos == 0:
                    ret = 100.0
                elif pos <= 10:
                    ret = 100 - intro * (pos / 10.0)          # steep intro drop
                else:
                    span = (pos - 10) / 90.0
                    ret = (100 - intro) - (100 - intro - tail) * (span ** 0.9)
                retention_curves.append({
                    "week_start": wk.isoformat(),
                    "video_id": v["video_id"],
                    "position_pct": pos,
                    "audience_retained_pct": round(_clamp(ret, tail - 3, 100), 1),
                    "is_synthetic": SYNTHETIC_FLAG,
                })

        # Traffic sources (drift the config baseline a little each week).
        for name, base in s["traffic_sources"].items():
            traffic.append({
                "week_start": wk.isoformat(), "source": name,
                "pct": round(_clamp(base + rng.gauss(0, 1.5), 0, 100), 1),
                "is_synthetic": SYNTHETIC_FLAG,
            })

        # Demographics (age x gender approximation) + geography.
        for bucket, pct in s["demographics"]["age_buckets"].items():
            demographics.append({
                "week_start": wk.isoformat(), "age_bucket": bucket,
                "pct": round(_clamp(pct + rng.gauss(0, 0.8), 0, 100), 1),
                "is_synthetic": SYNTHETIC_FLAG,
            })
        for country, pct in s["demographics"]["geography"].items():
            geo.append({
                "week_start": wk.isoformat(), "country": country,
                "pct": round(_clamp(pct + rng.gauss(0, 1.0), 0, 100), 1),
                "is_synthetic": SYNTHETIC_FLAG,
            })

    # Gender split is fairly stable -> emit once at channel level.
    gender_split = [{"segment": k, "pct": v, "is_synthetic": SYNTHETIC_FLAG}
                    for k, v in s["demographics"]["gender"].items()]

    # --- Synthetic A/B TEST LOG ---------------------------------------------
    ab_tests = _synth_ab_tests(videos, week_starts, weeks, cfg, rng)

    return {
        "weekly_metrics": weekly_metrics,
        "retention_curves": retention_curves,
        "traffic_sources": traffic,
        "demographics_age": demographics,
        "demographics_gender": gender_split,
        "geography": geo,
        "ab_tests": ab_tests,
    }


def _synth_ab_tests(videos, week_starts, weeks, cfg, rng) -> list[dict]:
    """Thumbnail / title / packaging experiments with control vs variant CTR."""
    s = cfg["synthetic"]
    elements = ["thumbnail", "title", "packaging"]
    variant_flavors = {
        "thumbnail": ["face + reaction", "product hero", "bold text overlay", "clean minimal"],
        "title": ["curiosity gap", "number/list framing", "bold claim", "plain descriptive"],
        "packaging": ["short intro cut", "cold-open hook", "chapter restructure"],
    }
    tests, tid = [], 1
    for wk in week_starts:
        vids = weeks[wk]
        if not vids:
            continue
        for _ in range(s["ab_tests"]["tests_per_week"]):
            v = rng.choice(vids)
            element = rng.choice(elements)
            control_ctr = _clamp(rng.gauss(s["ctr"]["mean"], 1.0), s["ctr"]["floor"], s["ctr"]["ceil"])
            # Variant effect: mostly small, occasionally a real winner or loser.
            effect = rng.choice([rng.uniform(-0.15, -0.02), rng.uniform(-0.05, 0.05),
                                 rng.uniform(0.03, 0.22)])
            variant_ctr = _clamp(control_ctr * (1 + effect), 1.0, 15.0)
            impressions_each = rng.randint(80_000, 260_000)
            tests.append({
                "test_id": f"AB-{wk.isoformat()}-{tid:02d}",
                "week_start": wk.isoformat(),
                "video_id": v["video_id"],
                "video_title": v["title"],
                "element": element,
                "control_variant": "current",
                "test_variant": rng.choice(variant_flavors[element]),
                "impressions_control": impressions_each,
                "impressions_variant": impressions_each,
                "ctr_control_pct": round(control_ctr, 2),
                "ctr_variant_pct": round(variant_ctr, 2),
                "is_synthetic": SYNTHETIC_FLAG,
            })
            tid += 1
    return tests
