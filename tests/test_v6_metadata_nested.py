"""Regression tests for V6 streaming metadata and archive migration."""
import json
from pathlib import Path
import tempfile
import unittest

from v6_storage.migration import Migrator, metadata
from v6_storage.records import Shape


class V6NestedMetadataRegression(unittest.TestCase):
    def test_nested_archive_metadata_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "2026-10-07.json"
            document = {
                "tarih": "2026-10-07",
                "top10": [{"sembol": "AAA"}],
                "ham_top10": [{"sembol": "BBB"}],
                "pozitif_havuz": {
                    "adaylar": [{"sembol": "CCC"}],
                    "istatistik": {"kaynak": "live", "sayac": 3},
                    "ayrintilar": [{"durum": {"neden": "test"}}],
                },
                "ozet": {"piyasa": {"yon": "pozitif", "risk": {"puan": 7}}},
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            before = path.read_bytes()
            shape = Shape("archives/yarin_top10_arsiv/2026-10-07.json", {
                "top10": "list",
                "ham_top10": "list",
                "pozitif_havuz.adaylar": "list",
            }, "tomorrow_snapshot")
            actual, meta = metadata(path, shape)
            self.assertEqual(actual.fields, shape.fields)
            self.assertEqual(meta, {
                "tarih": "2026-10-07",
                "pozitif_havuz": {
                    "istatistik": {"kaynak": "live", "sayac": 3},
                    "ayrintilar": [{"durum": {"neden": "test"}}],
                },
                "ozet": {"piyasa": {"yon": "pozitif", "risk": {"puan": 7}}},
            })
            report = Migrator().run(path, shape)
            self.assertEqual(report["status"], "VERIFIED")
            self.assertEqual(report["records"], 3)
            self.assertEqual(path.read_bytes(), before)

    def test_nested_metadata_duplicate_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.json"
            path.write_text('{"rows":[],"meta":{"a":1,"a":2}}', encoding="utf-8")
            report = Migrator().run(path, Shape("test", {"rows": "list"}))
            self.assertEqual(report["status"], "UNRESOLVED")
            self.assertEqual(report["error"], "SOURCE_DUPLICATE_FIELD")


if __name__ == "__main__":
    unittest.main()
