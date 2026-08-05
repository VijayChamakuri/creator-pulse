"""
store.py — CLEAN + PERSIST
==========================
Loads the two data domains into a single SQLite file, but keeps them in
clearly-named, physically separate tables so the real/synthetic boundary is
obvious from the schema alone:

    public_videos        -> REAL public pull (or labeled sample fixture)
    syn_weekly_metrics   -> SYNTHETIC owner-only
    syn_retention        -> SYNTHETIC
    syn_traffic_sources  -> SYNTHETIC
    syn_demographics_age -> SYNTHETIC
    syn_demographics_gender -> SYNTHETIC
    syn_geography        -> SYNTHETIC
    syn_ab_tests         -> SYNTHETIC

Every `syn_*` table carries an is_synthetic column. A `meta` table records the
provenance of the public pull for the report to cite.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "creatorpulse.db"


@contextmanager
def _writable_sqlite(dest: Path):
    """Yield a sqlite connection on local scratch, then copy the file to `dest`.

    Some mounted filesystems (network/overlay mounts) don't support the sqlite
    rollback journal and raise 'disk I/O error'. Building on local temp storage
    and copying the finished .db file avoids that while keeping output in-repo.
    """
    tmp = Path(tempfile.gettempdir()) / f"creatorpulse_{os.getpid()}.db"
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        yield con, tmp
        con.commit()
    finally:
        con.close()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmp, dest)
    tmp.unlink(missing_ok=True)


def _clean_public(videos: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(videos)
    # De-dup, coerce types, drop rows with no title/date, fill missing counts.
    df = df.drop_duplicates(subset="video_id")
    df["publish_date"] = pd.to_datetime(df["publish_date"], errors="coerce")
    df = df.dropna(subset=["title", "publish_date"])
    for c in ["view_count", "like_count", "comment_count", "duration_sec"]:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["view_count"] = df["view_count"].fillna(0).astype(int)
    df["publish_date"] = df["publish_date"].dt.date.astype(str)
    return df.sort_values("publish_date", ascending=False).reset_index(drop=True)


def store(ingest_result: dict, synthetic: dict, cfg) -> Path:
    pub = _clean_public(ingest_result["videos"])
    with _writable_sqlite(DB_PATH) as (con, _tmp):
        pub.to_sql("public_videos", con, if_exists="replace", index=False)
        table_map = {
            "syn_weekly_metrics": synthetic["weekly_metrics"],
            "syn_retention": synthetic["retention_curves"],
            "syn_traffic_sources": synthetic["traffic_sources"],
            "syn_demographics_age": synthetic["demographics_age"],
            "syn_demographics_gender": synthetic["demographics_gender"],
            "syn_geography": synthetic["geography"],
            "syn_ab_tests": synthetic["ab_tests"],
        }
        for name, rows in table_map.items():
            pd.DataFrame(rows).to_sql(name, con, if_exists="replace", index=False)
        pd.DataFrame([{
            "channel": cfg["channel"]["display_name"],
            "public_source": ingest_result["source"],
            "is_real_public_data": int(ingest_result["is_real"]),
            "n_public_videos": len(pub),
            "n_synthetic_weeks": len(synthetic["weekly_metrics"]),
            "n_ab_tests": len(synthetic["ab_tests"]),
        }]).to_sql("meta", con, if_exists="replace", index=False)
    print(f"[store] wrote {DB_PATH.name}: {len(pub)} public videos, "
          f"{len(synthetic['weekly_metrics'])} synthetic weeks, "
          f"{len(synthetic['ab_tests'])} A/B tests")
    return DB_PATH


def load_tables() -> dict:
    # Read from a local copy for the same mount-safety reason as writes.
    tmp = Path(tempfile.gettempdir()) / f"creatorpulse_read_{os.getpid()}.db"
    shutil.copy(DB_PATH, tmp)
    con = sqlite3.connect(tmp)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        return {n: pd.read_sql(f"SELECT * FROM {n}", con) for n in names}
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
