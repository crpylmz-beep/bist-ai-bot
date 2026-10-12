"""Isolated motor schedule tests; no market data or network calls."""
import ast
import datetime as dt
import pathlib
import unittest
from unittest.mock import Mock

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "canli_motor.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
names = {"piyasa_dakikasi", "gun_ici_acik", "gun_sonu_zamani"}
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {n.name for n in nodes} == names
namespace = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
market = namespace["gun_ici_acik"]
close = namespace["gun_sonu_zamani"]


class ScheduleTests(unittest.TestCase):
    def check(self, weekday, hour, minute, intraday, eod):
        day = dt.datetime(2026, 10, 12 + weekday, hour, minute)
        self.assertEqual(market(day), intraday)
        self.assertEqual(close(day), eod)

    def test_boundaries(self):
        for hour, minute, trading, eod in [
            (9, 44, False, False),
            (9, 45, True, False),
            (17, 59, True, False),
            (18, 0, False, False),
            (18, 19, False, False),
            (18, 20, False, True),
            (18, 29, False, True),
            (18, 30, False, False),
        ]:
            with self.subTest(hour=hour, minute=minute):
                self.check(0, hour, minute, trading, eod)

    def test_weekend(self):
        self.check(5, 12, 0, False, False)
        self.check(6, 18, 20, False, False)

    def test_worker_has_close_guard(self):
        worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "tek_hisse_guncelle")
        self.assertIn("gun_ici_acik", ast.unparse(worker.body[0]))

    def test_post_scan_has_close_guard(self):
        motor = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "motoru_calistir")
        code = ast.unparse(motor)
        self.assertIn("if not gun_ici_acik(datetime.now(ISTANBUL)):", code)
        self.assertIn("gun_sonu_deneme_sayisi < 2", code)


if __name__ == "__main__":
    unittest.main()
