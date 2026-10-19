"""보드 API 시험(10-06 호연 P3, 막힌 작업 33).

- 경로 점검: 각 /api 경로가 의도한 함수에 붙어 있고, 경로 변수 말고는 꼭 줘야 하는 인자가 없는지.
  10-06 14:05 board.py 수정 때 데코레이터 아래에 다른 함수를 끼워 넣어 /api/board 가 422를 낸 일을 막는다.
- 응답 점검: 실제 DB를 읽기 전용으로 열어 화면이 쓰는 키가 있는지(DB가 없으면 건너뜀).
실행: cd 03_백엔드 && .venv/bin/python -m unittest discover -s tests
API 코드를 고친 뒤, 보드 API를 다시 띄우기 전과 커밋 전에 돌린다.
"""
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main, board  # noqa: E402

EXPECTED = {
    "/api/board": "board", "/api/analyses": "analyses", "/api/replay": "replay", "/api/engine": "engine_status",
    "/api/study": "study_index", "/api/study/{name}": "study_doc", "/api/chart/{symbol}": "chart",
}


class RouteTest(unittest.TestCase):
    def test_routes_bound_to_expected_functions(self):
        got = {r.path: r.endpoint.__name__ for r in board.router.routes if getattr(r, "path", "") in EXPECTED}
        self.assertEqual(got, EXPECTED)

    def test_no_required_query_params(self):
        for r in board.router.routes:
            if getattr(r, "path", "") not in EXPECTED:
                continue
            path_vars = {p.strip("{}") for p in r.path.split("/") if p.startswith("{")}
            for name, prm in inspect.signature(r.endpoint).parameters.items():
                if prm.default is inspect.Parameter.empty:
                    self.assertIn(name, path_vars, f"{r.path}: 꼭 줘야 하는 인자 {name}")


@unittest.skipUnless(main.DB_PATH.exists(), "DB 없음")
class ResponseTest(unittest.TestCase):
    def test_board_shape(self):
        b = board.board()
        for k in ("t_close_kst", "next_t_close_kst", "rules", "symbols", "track", "news", "explain"):
            self.assertIn(k, b)
        self.assertEqual([s["symbol"] for s in b["symbols"]], ["BTCUSDT", "ETHUSDT", "XRPUSDT"])
        for s in b["symbols"]:
            self.assertIn("market", s)
            if s["market"]:
                m = s["market"]
                self.assertLessEqual(m["low_24h"], m["price"])
                self.assertLessEqual(m["price"], m["high_24h"])
        self.assertIsInstance(b["track"]["recent_strong"], list)
        self.assertIn("all", b["track"])                     # 10-06 P4: 운영 전체 성적
        self.assertIn("ai_report", b)                        # 10-06 P4: AI 심층 리포트(없으면 None)

    def test_chart_and_analyses(self):
        c = board.chart("BTCUSDT", 1)
        self.assertIn("range", c)
        a = board.analyses(symbol=None, limit=5, all_versions=False)
        self.assertTrue(isinstance(a, (list, dict)))

    def test_engine_and_study(self):
        self.assertIsInstance(board.engine_status(), dict)
        self.assertTrue(board.study_index())


if __name__ == "__main__":
    unittest.main()



class IncludedTest(unittest.TestCase):
    def test_router_is_included_in_app(self):
        # 앱에서 경로 이름으로 주소를 찾을 수 있으면 board 라우터가 앱에 붙어 있는 것
        self.assertEqual(main.app.url_path_for("board"), "/api/board")
        self.assertEqual(main.app.url_path_for("chart", symbol="BTCUSDT"), "/api/chart/BTCUSDT")


class Strong15Test(unittest.TestCase):
    """15분 확실한 신호(10-07): 카드의 now15·보드 strong15 블록을 작은 임시 DB로 확인하고, 배포 서명이 15분 상태를 보는지 확인."""
    M15 = 900_000

    def _conn(self, with_table=True):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER NOT NULL);")
        if with_table:
            conn.executescript("""CREATE TABLE strong15 (symbol TEXT, t_close INTEGER, rules_version TEXT, dir INTEGER,
                prev_dir INTEGER, kind TEXT, close REAL, created_at INTEGER, end_t INTEGER, end_close REAL, end_reason TEXT,
                ret REAL, hit INTEGER, aux_t INTEGER, aux_close REAL, aux_ret REAL, aux_hit INTEGER, scored_at INTEGER,
                PRIMARY KEY (symbol, t_close, rules_version));""")
        return conn

    def test_now15_and_block(self):
        conn = self._conn()
        t = 1_759_800_600_000      # 2026-10-07 10:30 KST
        conn.execute("INSERT INTO strong15 (symbol, t_close, rules_version, dir, prev_dir, kind, close, created_at, end_t, end_close, "
                     "end_reason, ret, hit) VALUES ('BTCUSDT', ?, 'v', 1, 0, 'on', 100, 0, ?, 101, 'off', 0.01, 1)", (t - 4 * self.M15, t))
        conn.execute("INSERT INTO strong15 (symbol, t_close, rules_version, dir, prev_dir, kind, close, created_at) "
                     "VALUES ('BTCUSDT', ?, 'v', 0, 1, 'off', 101, 0)", (t,))
        conn.execute("INSERT INTO kv VALUES ('strong15_last_run', ?, 0)", (str(t + 60_000),))
        n = board._now15(conn, "BTCUSDT", "v", now=t + 60_000)
        self.assertEqual((n["dir"], n["label"], n["kind"], n["since_hm"], n["since_today"]), (0, "없음", "off", "10:30", True))
        self.assertEqual(board._now15(conn, "BTCUSDT", "v", now=t + 86_400_000)["since_today"], False)
        self.assertEqual(board._now15(conn, "ETHUSDT", "v")["label"], "없음")           # 행 없음 → 없음, since 없음
        self.assertIsNone(board._now15(conn, "ETHUSDT", "v")["since_hm"])
        self.assertIsNone(board._now15(self._conn(with_table=False), "BTCUSDT", "v"))   # 표 없음(옛 DB) → None
        blk = board._strong15_block(conn, "v")
        self.assertEqual(blk["last_run_kst"], "10-07 10:31")
        self.assertEqual([(r["short"], r["n"], r["called"], r["hit"], r["hit_pct"]) for r in blk["rows"]], [("BTC", 1, 1, 1, 100.0)])
        self.assertEqual([(r["kind"], r["label"]) for r in blk["recent"]], [("off", "없음"), ("on", "롱 확실")])
        self.assertEqual(blk["recent"][1]["ret_pct"], 1.0)
        self.assertIsNone(board._strong15_block(self._conn(with_table=False), "v"))

    def test_deploy_signature_changes_with_now15(self):
        import hashlib, json, re
        src = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_vercel.sh").read_text(encoding="utf-8")
        m = re.search(r"h = hashlib\.sha256\((json\.dumps\(.*?\)\.encode\(\))\)", src, re.S)
        self.assertIsNotNone(m, "deploy_vercel.sh 서명 식을 찾지 못함")
        sig = lambda b: hashlib.sha256(eval(m.group(1), {"json": json, "b": b})).hexdigest()    # noqa: E731 — 스크립트의 식 그대로
        base = {"t_close": "x", "rules": {"version": "v"},
                "symbols": [{"symbol": "BTCUSDT", "strong": False, "strong_dir": 0, "now15": {"dir": 0, "t_close": "a"}}]}
        on = json.loads(json.dumps(base)); on["symbols"][0]["now15"] = {"dir": 1, "t_close": "b"}
        self.assertNotEqual(sig(base), sig(on))                                                  # 15분 상태가 바뀌면 배포
        self.assertEqual(sig(base), sig(json.loads(json.dumps(base))))
        old = json.loads(json.dumps(base)); del old["symbols"][0]["now15"]
        sig(old)                                                                                 # now15 없는 옛 응답도 오류 없음
        # 10-12: 공식 트리거·AI 분석·Core Condition 이 바뀌어도 배포, _at(계산 시각)만 바뀌면 배포하지 않음
        v = json.loads(json.dumps(base)); v["v4"] = {"recent": {"official": []}, "ai": {"BTCUSDT": {"latest": None}}, "core": {"BTCUSDT": {"state": 0}, "_at": 1}}
        t = json.loads(json.dumps(v)); t["v4"]["recent"]["official"] = [{"symbol": "BTCUSDT", "t_bar": 9, "result": "open"}]
        a = json.loads(json.dumps(v)); a["v4"]["ai"]["BTCUSDT"] = {"latest": {"created_at": 5}}
        c = json.loads(json.dumps(v)); c["v4"]["core"]["BTCUSDT"]["state"] = 1
        at = json.loads(json.dumps(v)); at["v4"]["core"]["_at"] = 2
        self.assertTrue(sig(v) != sig(t) and sig(v) != sig(a) and sig(v) != sig(c))
        self.assertEqual(sig(v), sig(at))


class TriggerBoardTest(unittest.TestCase):
    """10-12 리팩토링: 보드는 엔진이 쓴 trigger_board.json 을 그대로 내려준다(규칙 버전이 같을 때만)."""

    def test_trigger_board_version_gate(self):
        import json
        import tempfile
        orig = board.ENGINE
        try:
            with tempfile.TemporaryDirectory() as d:
                board.ENGINE = Path(d)
                (Path(d) / "reports").mkdir()
                self.assertIsNone(board._trigger_board("v1"))                 # 파일 없음
                (Path(d) / "reports" / "trigger_board.json").write_text(
                    json.dumps({"rules_version": "v1", "stats": {}, "recent": {}, "ai": {}, "core": {}}), encoding="utf-8")
                self.assertEqual(board._trigger_board("v1")["rules_version"], "v1")
                self.assertIsNone(board._trigger_board("v2"))                 # 다른 규칙 버전
        finally:
            board.ENGINE = orig

    @unittest.skipUnless(main.DB_PATH.exists(), "DB 없음")
    def test_board_has_v4_key(self):
        self.assertIn("v4", board.board())
