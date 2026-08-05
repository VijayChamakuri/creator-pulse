"""
ingest.py — REAL PUBLIC DATA LAYER
==================================
Pulls MKBHD's public YouTube metadata: title, publish date, duration, view /
like / comment counts, thumbnail URL. Nothing here is owner-only or private.

Provenance is recorded on every row via the `source` column so downstream code
and the report can always tell where a number came from:

    yt-dlp        -> live public scrape, no API key required   (preferred)
    youtube-api   -> YouTube Data API v3, needs YOUTUBE_API_KEY
    sample-fixture-> bundled offline snapshot (CI / sandbox / no network)

IMPORTANT: the sample fixture's engagement counts are ILLUSTRATIVE, not real
MKBHD metrics. They exist only so the pipeline runs end-to-end with no network.
On any connected machine, `prefer: [yt-dlp, ...]` replaces them with live data.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


# ---------------------------------------------------------------------------
# 1. Preferred path: yt-dlp (live, public, no key)
# ---------------------------------------------------------------------------
def _from_ytdlp(cfg) -> list[dict] | None:
    handle = cfg["channel"]["handle"].lstrip("@")
    n = cfg["ingest"]["max_videos"]
    url = f"https://www.youtube.com/@{handle}/videos"
    try:
        # --flat-playlist is fast but omits counts; we do a two-step pull:
        # 1) list recent video ids, 2) fetch full metadata per id.
        listing = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--playlist-end", str(n),
             "--dump-single-json", url],
            capture_output=True, text=True, timeout=120,
        )
        if listing.returncode != 0:
            print(f"[ingest] yt-dlp listing failed: {listing.stderr[:200]}", file=sys.stderr)
            return None
        entries = json.loads(listing.stdout).get("entries", [])[:n]
        rows = []
        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            meta = subprocess.run(
                ["yt-dlp", "--dump-single-json", "--skip-download",
                 f"https://www.youtube.com/watch?v={vid}"],
                capture_output=True, text=True, timeout=90,
            )
            if meta.returncode != 0:
                continue
            m = json.loads(meta.stdout)
            up = m.get("upload_date")  # YYYYMMDD
            rows.append({
                "video_id": vid,
                "title": m.get("title"),
                "publish_date": (datetime.strptime(up, "%Y%m%d").date().isoformat()
                                 if up else None),
                "duration_sec": m.get("duration"),
                "view_count": m.get("view_count"),
                "like_count": m.get("like_count"),
                "comment_count": m.get("comment_count"),
                "thumbnail_url": m.get("thumbnail"),
                "source": "yt-dlp",
            })
        return rows or None
    except FileNotFoundError:
        print("[ingest] yt-dlp not installed; skipping live scrape.", file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[ingest] yt-dlp path errored: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 2. YouTube Data API v3 (needs YOUTUBE_API_KEY)
# ---------------------------------------------------------------------------
def _from_youtube_api(cfg) -> list[dict] | None:
    import urllib.parse
    import urllib.request

    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        return None
    cid = cfg["channel"]["channel_id"]
    n = cfg["ingest"]["max_videos"]

    def _get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())

    try:
        ch = _get("https://www.googleapis.com/youtube/v3/channels?"
                  + urllib.parse.urlencode({"part": "contentDetails", "id": cid, "key": key}))
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids, token = [], ""
        while len(ids) < n:
            pl = _get("https://www.googleapis.com/youtube/v3/playlistItems?"
                      + urllib.parse.urlencode({"part": "contentDetails", "playlistId": uploads,
                                                "maxResults": 50, "pageToken": token, "key": key}))
            ids += [it["contentDetails"]["videoId"] for it in pl["items"]]
            token = pl.get("nextPageToken", "")
            if not token:
                break
        ids = ids[:n]
        rows = []
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            vs = _get("https://www.googleapis.com/youtube/v3/videos?"
                      + urllib.parse.urlencode({"part": "snippet,statistics,contentDetails",
                                                "id": ",".join(batch), "key": key}))
            for v in vs["items"]:
                sn, st = v["snippet"], v.get("statistics", {})
                rows.append({
                    "video_id": v["id"],
                    "title": sn["title"],
                    "publish_date": sn["publishedAt"][:10],
                    "duration_sec": _iso8601_to_sec(v["contentDetails"]["duration"]),
                    "view_count": int(st.get("viewCount", 0)),
                    "like_count": int(st.get("likeCount", 0)) if "likeCount" in st else None,
                    "comment_count": int(st.get("commentCount", 0)) if "commentCount" in st else None,
                    "thumbnail_url": sn["thumbnails"].get("high", {}).get("url"),
                    "source": "youtube-api",
                })
        return rows or None
    except Exception as exc:  # noqa: BLE001
        print(f"[ingest] YouTube API path errored: {exc}", file=sys.stderr)
        return None


def _iso8601_to_sec(dur: str) -> int:
    import re
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0
    h, mm, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mm * 60 + s


# ---------------------------------------------------------------------------
# 3. Offline sample fixture (ILLUSTRATIVE public counts, clearly labeled)
# ---------------------------------------------------------------------------
# Titles reflect MKBHD's real, public content cadence (flagship reviews, "best
# of" roundups, studio/tech commentary). Engagement numbers are deterministic
# placeholders so the demo runs without network — NOT real MKBHD figures.
_FIXTURE_TITLES = [
    ("The Best Smartphones of 2026!", 736, 12),
    ("iPhone 17 Pro Review: The Titanium Era Continues!", 812, 24),
    ("This Foldable Changes Everything.", 604, 16),
    ("Samsung Galaxy S26 Ultra Review: Peak Android!", 903, 40),
    ("Why Everyone's Talking About This Camera.", 548, 8),
    ("The Cheapest Electric Car You Can Buy!", 690, 20),
    ("Google Pixel 10 Review: Software Wins Again?", 771, 30),
    ("I Tried the $2000 Smart Glasses.", 512, 6),
    ("Ranking Every Phone I Reviewed This Year!", 968, 18),
    ("The Truth About 'AI Phones'.", 634, 10),
    ("Tesla's New Roadster: Is It Real Now?", 725, 26),
    ("Laptop Buyer's Guide 2026!", 843, 22),
    ("This Tech Was a Huge Letdown.", 470, 5),
    ("Nothing Phone 3 Review: Still Different!", 688, 14),
    ("The Most Requested Review of the Year!", 799, 28),
    ("Explaining the USB-C Chaos (Again).", 556, 9),
    ("My Entire Studio Setup Tour 2026!", 1024, 35),
    ("The Underdog Phone Nobody Bought.", 601, 7),
    ("Are $500 Phones Finally Good Enough?", 712, 15),
    ("What Happened to VR?", 659, 11),
    ("The Wildest Concept Tech at CES 2026!", 887, 19),
    ("Reviewing the Internet's Favorite Gadget.", 623, 13),
    ("Fastest Charging Phone Ever Tested!", 498, 6),
    ("The State of Smartphones: Mid-2026.", 934, 21),
]


def _build_fixture(cfg) -> list[dict]:
    """Deterministic, clearly-labeled illustrative snapshot."""
    import random
    rng = random.Random(20260731)
    n = min(cfg["ingest"]["max_videos"], len(_FIXTURE_TITLES))
    # Anchor the newest upload to a fixed recent date so weekly bucketing is stable.
    newest = datetime(2026, 7, 30, tzinfo=timezone.utc).date()
    rows = []
    day_cursor = newest
    for i in range(n):
        title, dur, base_k = _FIXTURE_TITLES[i]
        # Realistic-ish shape: bigger flagship reviews get more views; add noise.
        views = int(base_k * 100_000 * rng.uniform(0.75, 1.25)) + rng.randint(0, 90_000)
        likes = int(views * rng.uniform(0.028, 0.05))
        comments = int(views * rng.uniform(0.0015, 0.004))
        vid_guess = f"FIXT{i:04d}"
        rows.append({
            "video_id": vid_guess,
            "title": title,
            "publish_date": day_cursor.isoformat(),
            "duration_sec": dur,
            "view_count": views,
            "like_count": likes,
            "comment_count": comments,
            # Real public thumbnail URL pattern (works once video_id is real):
            "thumbnail_url": f"https://i.ytimg.com/vi/{vid_guess}/hqdefault.jpg",
            "source": "sample-fixture",
        })
        # Step back 2-4 days between uploads (MKBHD-like cadence).
        day_cursor = day_cursor - timedelta(days=rng.choice([2, 3, 3, 4]))
    return rows


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def ingest(cfg) -> dict:
    """Return {'videos': [...], 'source': str, 'is_real': bool}."""
    dispatch = {
        "yt-dlp": _from_ytdlp,
        "youtube-api": _from_youtube_api,
        "fixture": _build_fixture,
    }
    rows, used = None, None
    for name in cfg["ingest"]["prefer"]:
        fn = dispatch.get(name)
        if not fn:
            continue
        rows = fn(cfg)
        if rows:
            used = name
            break
    if not rows:  # last-resort guarantee the pipeline never dies
        rows, used = _build_fixture(cfg), "fixture"

    is_real = used in ("yt-dlp", "youtube-api")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / "public_videos.json"
    payload = {
        "channel": cfg["channel"]["display_name"],
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "source": rows[0]["source"],
        "is_real_public_data": is_real,
        "videos": rows,
    }
    out.write_text(json.dumps(payload, indent=2))
    label = "REAL public data" if is_real else "SAMPLE fixture (illustrative, not real metrics)"
    print(f"[ingest] {len(rows)} videos via '{used}' -> {label}")
    return {"videos": rows, "source": rows[0]["source"], "is_real": is_real}
