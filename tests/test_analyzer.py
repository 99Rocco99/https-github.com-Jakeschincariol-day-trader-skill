import contextlib
import datetime as dt
import importlib.util
import io
import json
import math
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "futures-analyzer")
SKILL = os.path.join(ROOT, "futures-analyzer")

_spec = importlib.util.spec_from_file_location("analyze", os.path.join(SKILL, "analyze.py"))
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

FRI = "2026-11-06 11:30"


def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = A.main(list(argv) + ["--offline", FIX, "--cache", os.path.join(FIX, "no-cache")])
    return code, buf.getvalue()


def bar(ts, o, h, l, c, v=100):
    return (ts, o, h, l, c, v)


class Time(unittest.TestCase):
    def test_new_york_offset_follows_daylight_saving(self):
        # 2026: DST from Sun Mar 8 to Sun Nov 1
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 7, 1, 12)), -4)
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 11, 6, 12)), -5)
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 3, 8, 6, 59)), -5)
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 3, 8, 7, 0)), -4)
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 11, 1, 5, 59)), -4)
        self.assertEqual(A.et_offset_hours(dt.datetime(2026, 11, 1, 6, 0)), -5)

    def test_round_trip(self):
        for s in ("2026-11-06 09:30", "2026-07-15 16:00", "2026-03-09 08:20"):
            local = dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
            self.assertEqual(A.to_et(A.et_to_ts(local)), local)

    def test_globex_evening_belongs_to_the_next_day(self):
        self.assertEqual(A.trading_date(dt.datetime(2026, 11, 5, 18, 0)), dt.date(2026, 11, 6))
        self.assertEqual(A.trading_date(dt.datetime(2026, 11, 6, 16, 55)), dt.date(2026, 11, 6))


class Contracts(unittest.TestCase):
    def setUp(self):
        self.contracts = A.load_contracts()

    def test_specs_are_complete_and_unique(self):
        syms = [c["symbol"] for c in self.contracts]
        self.assertEqual(len(syms), len(set(syms)))
        self.assertGreaterEqual(len(syms), 40)
        for c in self.contracts:
            for k in ("name", "group", "point_value", "tick", "margin_pct", "rth", "micro"):
                self.assertIn(k, c, c["symbol"])
            self.assertGreater(c["point_value"], 0)
            self.assertGreater(c["tick"], 0)
            self.assertTrue(0 < c["margin_pct"] < 1)
            self.assertLess(A.hm(c["rth"][0]), A.hm(c["rth"][1]), c["symbol"])

    def test_tick_values_match_the_exchange_specs(self):
        by = {c["symbol"]: c for c in self.contracts}
        for sym, usd in {"MES": 1.25, "ES": 12.5, "MNQ": 0.5, "MCL": 1.0, "CL": 10.0, "MGC": 1.0, "ZC": 12.5,
                         "ZN": 15.625, "6E": 6.25, "M6E": 1.25, "6J": 6.25, "MBT": 0.5, "SB": 11.2, "LE": 10.0}.items():
            self.assertAlmostEqual(by[sym]["tick"] * by[sym]["point_value"], usd, places=4, msg=sym)

    def test_a_real_margin_beats_the_estimate(self):
        mes = next(c for c in self.contracts if c["symbol"] == "MES")
        self.assertEqual(A.margin_for(mes, 7404.0, {}), (2406, "est"))
        self.assertEqual(A.margin_for(mes, 7404.0, {"MES": 1500.0}), (1500.0, "set"))
        self.assertEqual(A.margin_for(mes, None, {}), (None, "est"))

    def test_margins_file_skips_notes(self):
        m = A.load_margins(os.path.join(SKILL, "margins.example.json"))
        self.assertEqual(m["MES"], 2400)
        self.assertNotIn("_ABOUT", m)


class Bars(unittest.TestCase):
    def test_drops_nulls_the_live_tick_and_unfinished_bars(self):
        data = {"chart": {"result": [{"timestamp": [600, 900, 1200, 1259, 1500],
                                      "indicators": {"quote": [{"open": [1, None, 1, 1, 1], "high": [2, 2, 2, 2, 2],
                                                                "low": [0, 0, 0, 0, 0], "close": [1, 1, 1, 1, 1],
                                                                "volume": [5, 5, None, 5, 5]}]}}]}}
        bars = A.parse_bars(data, now=1600)
        self.assertEqual([b[0] for b in bars], [600, 1200])  # 900 null, 1259 off grid, 1500 not finished
        self.assertEqual(bars[1][5], 0)

    def test_day_stats(self):
        # open 100, up to 104 in a straight line: efficiency 1, a trend day
        bars = [bar(i * 300, 100 + i, 101 + i, 100 + i, 101 + i) for i in range(4)]
        s = A.day_stats(bars)
        self.assertEqual(s["range"], 4)
        self.assertEqual(s["net"], 4)
        self.assertAlmostEqual(s["efficiency"], 1.0)
        self.assertAlmostEqual(s["clean"], 2.0)  # 1.0 x sqrt(4 bars)
        self.assertTrue(s["trend_day"])
        # up 2, down 2: no net move
        chop = [bar(0, 100, 102, 100, 102), bar(300, 102, 102, 100, 100)]
        s = A.day_stats(chop)
        self.assertEqual(s["efficiency"], 0.0)
        self.assertFalse(s["trend_day"])

    def test_random_walk_scores_about_one(self):
        import random
        rnd = random.Random(7)
        vals = []
        for _ in range(400):
            p, bars = 100.0, []
            for i in range(78):
                q = p + rnd.gauss(0, 0.1)
                bars.append(bar(i * 300, p, max(p, q), min(p, q), q))
                p = q
            vals.append(A.day_stats(bars)["clean"])
        self.assertAlmostEqual(sum(vals) / len(vals), 1.0, delta=0.1)


class Offline(unittest.TestCase):
    """Real Yahoo charts saved on 2026-11-07: MES, MCL, ZS, M6E, 60 days of 5-minute bars."""

    def test_rank_orders_by_score_and_marks_estimates(self):
        code, out = run("rank", "--now", FRI)
        self.assertEqual(code, 0)
        order = re.findall(r"^(MES|MCL|ZS|M6E) ", out, re.M)
        self.assertEqual(order, ["ZS", "MCL", "M6E", "MES"])
        self.assertIn("full sessions 2026-08-28 to 2026-11-05", out)
        self.assertIn("$813*", out)
        self.assertIn("not forecasts of direction", out)

    def test_rank_json_numbers(self):
        code, out = run("rank", "--now", FRI, "--json")
        rows = {r["symbol"]: r for r in json.loads(out)}
        mcl = rows["MCL"]
        self.assertEqual(mcl["sessions"], 49)
        self.assertEqual(mcl["margin"], 813)
        self.assertAlmostEqual(mcl["avg_range_usd"], 273, delta=1)
        self.assertAlmostEqual(mcl["avg_range_ticks"], 273, delta=1)
        self.assertFalse(mcl["continuation_clear"])
        for r in rows.values():
            self.assertTrue(0 <= r["score"] <= 100)
            self.assertNotIn("_days", r)

    def test_margin_cap_filters(self):
        code, out = run("rank", "--now", FRI, "--max-margin", "1000", "--json")
        self.assertEqual(sorted(r["symbol"] for r in json.loads(out)), ["M6E", "MCL"])

    def test_today_live_compares_with_the_same_time(self):
        code, out = run("today", "--now", FRI, "--json")
        self.assertEqual(code, 0)
        rows = {r["symbol"]: r for r in json.loads(out)}
        mes = rows["MES"]
        self.assertTrue(mes["live"])
        self.assertEqual(mes["date"], "2026-11-06")
        self.assertEqual(mes["as_of"], "2026-11-06 11:30")
        self.assertEqual(mes["bars"], 24)  # 9:30 to 11:30
        self.assertTrue(mes["in_play"])
        self.assertEqual(rows["ZS"]["direction"], "down")
        self.assertEqual(rows["M6E"]["where"], "below the prior session's low")

    def test_today_on_a_weekend_shows_the_last_session(self):
        code, out = run("today", "--now", "2026-11-07 10:00")
        self.assertEqual(code, 0)
        self.assertIn("closed 11-06", out)
        self.assertIn("last completed session, not today", out)

    def test_globex_session(self):
        code, out = run("today", "--now", FRI, "--session", "globex", "--json")
        mes = {r["symbol"]: r for r in json.loads(out)}["MES"]
        self.assertEqual(mes["session"], "globex")
        self.assertGreater(mes["bars"], 150)  # since 6 PM Thursday

    def test_profile(self):
        code, out = run("profile", "MCL", "--now", FRI)
        self.assertEqual(code, 0)
        self.assertIn("49 full sessions", out)
        self.assertIn("one tick = $1.00", out)
        self.assertIn("9:00 AM", out)
        self.assertIn("Last 10 full sessions", out)
        code, out = run("profile", "MCL", "--now", FRI, "--json")
        p = json.loads(out)
        self.assertEqual(len(p["hours"]), 6)
        self.assertAlmostEqual(sum(h["share_of_hourly_movement"] for h in p["hours"]), 1.0, places=6)
        self.assertEqual(len(p["recent"]), 10)

    def test_unknown_symbol(self):
        code, out = run("profile", "XYZ", "--now", FRI)
        self.assertEqual(code, 1)
        self.assertIn("not in contracts.json", out)


class Repo(unittest.TestCase):
    def test_only_the_analyzer_skill(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, ["futures-analyzer"])

    def test_skill_frontmatter(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        fm = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
        self.assertIn("name: futures-analyzer", fm)
        self.assertIn("description:", fm)
        self.assertIn("not financial advice", " ".join(text.lower().split()))

    def test_no_trading_code_left(self):
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "tests")]
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(base, f), encoding="utf-8") as fh:
                        src = fh.read().lower()
                    for word in ("place_stock_order", "alpaca", "orders.json", "bracket"):
                        self.assertNotIn(word, src, f)

    def test_plugin_manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "futures-analyzer")
        self.assertEqual(plugin["skills"], "./")
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["plugins"][0]["name"], "futures-analyzer")


if __name__ == "__main__":
    unittest.main()
