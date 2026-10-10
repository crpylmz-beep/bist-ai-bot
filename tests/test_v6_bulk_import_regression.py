"""Tests for continuing V6 bulk import after one malformed source."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from v6_storage.bulk_import import main


class DummyPaths:
    def __init__(self, root):
        self.root = Path(root)
        self.runtime = self.root / "runtime"
        self.archives = self.root / "archives"
        self.runtime.mkdir()
        self.archives.mkdir()


class DummyStore:
    def __init__(self, *args, **kwargs): self.closed = False
    def ready(self): pass
    def close(self): self.closed = True


class V6BulkImportRegression(unittest.TestCase):
    def test_one_source_failure_does_not_skip_remaining(self):
        with tempfile.TemporaryDirectory() as folder:
            location = DummyPaths(folder)
            files = [location.archives / f"2026-10-0{i}.json" for i in (7, 8, 9)]
            for path in files: path.write_text(json.dumps({"top10": [{"sembol": "AAA"}]}))
            attempted = []

            def migrate(_self, path, _shape, apply=False):
                attempted.append(path.name)
                if path.name == "2026-10-08.json":
                    raise AttributeError("test failure")
                return {"status": "VERIFIED", "records": 1}

            with patch("v6_storage.bulk_import.paths", return_value=location), \
                 patch("v6_storage.bulk_import.Path", side_effect=lambda value: location.root if value == "/data" else Path(value)), \
                 patch("v6_storage.postgres.PostgresStore", DummyStore), \
                 patch("v6_storage.bulk_import.Migrator.run", migrate), \
                 patch("builtins.print") as printer:
                status = main(["--apply"])
            self.assertEqual(status, 2)
            self.assertEqual(attempted, [p.name for p in files])
            lines = [json.loads(call.args[0]) for call in printer.call_args_list]
            self.assertEqual(lines[-1]["status"], "PARTIAL")
            self.assertEqual(lines[-1]["verified_sources"], 2)
            self.assertEqual(lines[-1]["unresolved_sources"], 1)
            self.assertEqual(lines[1]["error"], "UNEXPECTED_AttributeError")
            self.assertTrue(lines[-1]["source_deleted"] is False)
            self.assertTrue(lines[-1]["backend_switched"] is False)


if __name__ == "__main__":
    unittest.main()
