"""Publish the exact generated report and dashboard used by GitHub Pages."""

from __future__ import annotations

import shutil
from pathlib import Path


def publish_pages(report_html: str | Path, dashboard_html: str | Path, docs_dir: str | Path) -> dict[str, Path]:
    report_source = Path(report_html)
    dashboard_source = Path(dashboard_html)
    destination = Path(docs_dir)
    destination.mkdir(parents=True, exist_ok=True)

    if not report_source.is_file() or not dashboard_source.is_file():
        raise FileNotFoundError("Generated report and dashboard must exist before publishing")

    report_target = destination / "report.html"
    dashboard_target = destination / "dashboard.html"
    shutil.copy2(report_source, report_target)
    shutil.copy2(dashboard_source, dashboard_target)
    return {"report": report_target, "dashboard": dashboard_target}
