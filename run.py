#!/usr/bin/env python3
"""
run.py - one command to build the weekly creator report end to end.

    python run.py                      # full pipeline, live pull if possible
    python run.py --no-llm             # deterministic narrative, no API needed
    python run.py --fixture            # force the offline sample dataset
    python run.py --channel @mkbhd     # override channel handle

Stages: ingest (real public) -> synthesize (labeled synthetic) -> store (sqlite)
-> analyze -> LLM report + QA -> render (HTML/PDF report + static dashboard).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import ingest as ingest_mod
from src import publish as publish_mod
from src import synthesize as syn_mod
from src import store as store_mod
from src import analyze as analyze_mod
from src import report as report_mod
from src import render as render_mod
from src import themes as themes_mod


def _load_env():
    """Load KEY=VALUE lines from a local .env so os.getenv works (no dep)."""
    for p in (ROOT / ".env", ROOT.parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--channel", help="override channel handle, e.g. @mkbhd")
    ap.add_argument("--no-llm", action="store_true", help="skip API, deterministic narrative")
    ap.add_argument("--fixture", action="store_true", help="force offline sample dataset")
    ap.add_argument(
        "--publish-pages",
        action="store_true",
        help="copy this run's report and dashboard to the GitHub Pages docs directory",
    )
    args = ap.parse_args()

    _load_env()
    cfg = yaml.safe_load(Path(args.config).read_text())
    if args.channel:
        cfg["channel"]["handle"] = args.channel
    if args.no_llm:
        cfg["report"]["use_llm"] = False
    if args.fixture:
        cfg["ingest"]["prefer"] = ["fixture"]

    print("== CreatorPulse weekly creator report ==")
    print(f"channel: {cfg['channel']['display_name']}  |  LLM: {cfg['report']['use_llm']}")

    # 1) REAL public data
    ing = ingest_mod.ingest(cfg)
    # 2) SYNTHETIC owner-only layer
    syn = syn_mod.synthesize(ing["videos"], cfg)
    # 3) store
    store_mod.store(ing, syn, cfg)
    tables = store_mod.load_tables()
    # 4) analyze
    analysis = analyze_mod.analyze(tables, cfg)
    # optional theme clustering (real titles only)
    themes = themes_mod.cluster_themes(ing["videos"])
    # 5) LLM report + QA
    result = report_mod.generate_report(analysis, cfg)
    result["report"]["_engine"] = result["engine"]
    # 6) render
    paths = render_mod.render_report(result["report"], result["qa"], analysis, cfg, themes)
    dash = render_mod.render_dashboard(analysis, themes)
    published = None
    if args.publish_pages:
        published = publish_mod.publish_pages(paths["html"], dash, ROOT / "docs")

    print("\n== done ==")
    print(f"report engine : {result['engine']}")
    print(f"QA verdict    : {result['qa'].get('verdict')}")
    print(f"report (HTML) : {paths['html']}")
    if paths["pdf"]:
        print(f"report (PDF)  : {paths['pdf']}")
    print(f"dashboard     : {dash}")
    if published:
        print(f"pages report  : {published['report']}")
        print(f"pages dashboard: {published['dashboard']}")
    if not ing["is_real"]:
        print("\nNOTE: public layer is the SAMPLE fixture (no network / yt-dlp). "
              "Run on a connected machine to pull real MKBHD data.")


if __name__ == "__main__":
    main()
