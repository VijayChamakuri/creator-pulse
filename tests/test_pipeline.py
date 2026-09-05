from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from src import analyze, ingest, publish, render, report, store, synthesize, themes


ROOT = Path(__file__).resolve().parents[1]


def load_fixture_config() -> dict:
    config = yaml.safe_load((ROOT / "config.yaml").read_text())
    config["ingest"]["prefer"] = ["fixture"]
    config["report"]["use_llm"] = False
    return config


class CreatorPulsePipelineTests(unittest.TestCase):
    def test_fixture_and_synthetic_layer_are_deterministic_and_labeled(self) -> None:
        config = load_fixture_config()
        first = ingest._build_fixture(config)
        second = ingest._build_fixture(config)
        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(row["source"] == "sample-fixture" for row in first))

        first_synthetic = synthesize.synthesize(first, config)
        second_synthetic = synthesize.synthesize(second, config)
        self.assertEqual(first_synthetic, second_synthetic)
        for table in first_synthetic.values():
            self.assertTrue(table)
            self.assertTrue(all(row["is_synthetic"] is True for row in table))

    def test_offline_pipeline_preserves_provenance_and_renders_disclosure(self) -> None:
        config = load_fixture_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with (
                mock.patch.object(ingest, "RAW_DIR", temp / "raw"),
                mock.patch.object(store, "DB_PATH", temp / "creatorpulse.db"),
                mock.patch.object(render, "ROOT", temp),
                mock.patch.object(render, "REPORTS", temp / "reports"),
                mock.patch.object(render, "DASH", temp / "dashboard"),
            ):
                ingested = ingest.ingest(config)
                synthetic = synthesize.synthesize(ingested["videos"], config)
                store.store(ingested, synthetic, config)
                analysis_result = analyze.analyze(store.load_tables(), config)
                theme_result = themes.cluster_themes(ingested["videos"])
                report_result = report.generate_report(analysis_result, config)
                report_result["report"]["_engine"] = report_result["engine"]
                paths = render.render_report(
                    report_result["report"],
                    report_result["qa"],
                    analysis_result,
                    config,
                    theme_result,
                )
                dashboard = render.render_dashboard(analysis_result, theme_result)

                self.assertFalse(analysis_result["is_real_public_data"])
                self.assertEqual(analysis_result["public_source"], "sample-fixture")
                provenance = analysis_result["data_provenance"]
                real_fields = set(provenance["real_public_data"]["weekly_metrics_fields"])
                synthetic_fields = set(
                    provenance["synthetic_modelled"]["weekly_metrics_fields"]
                )
                self.assertEqual(real_fields, {"real_public_views", "videos_published"})
                self.assertIn("ctr_pct", synthetic_fields)
                self.assertTrue(real_fields.isdisjoint(synthetic_fields))
                self.assertIn("SAMPLE FIXTURE", Path(paths["html"]).read_text())
                self.assertIn("SYNTHETIC", Path(dashboard).read_text())

    def test_publish_pages_copies_the_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            report_file = temp / "weekly.html"
            dashboard_file = temp / "dashboard-source.html"
            report_file.write_text("current report")
            dashboard_file.write_text("current dashboard")

            published = publish.publish_pages(report_file, dashboard_file, temp / "docs")

            self.assertEqual(published["report"].read_text(), "current report")
            self.assertEqual(published["dashboard"].read_text(), "current dashboard")


if __name__ == "__main__":
    unittest.main()
