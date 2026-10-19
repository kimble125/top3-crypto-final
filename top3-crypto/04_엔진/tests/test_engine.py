"""엔진 테스트 (표준 unittest). 실행: cd 04_엔진 && python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import db  # noqa: E402
import explain  # noqa: E402
import indicators as ind  # noqa: E402
import judge  # noqa: E402
import notify  # noqa: E402
import pipeline  # noqa: E402
import track  # noqa: E402


class TestIndicators(unittest.TestCase):
    def test_sma_ema(self):
        x = pd.Series([1.0, 2, 3, 4, 5])
        self.assertTrue(np.allclose(ind.sma(x, 3).dropna().values, [2, 3, 4]))
        # EMA span=3 → alpha=0.5, adjust=False: 1, 1.5, 2.25, 3.125, 4.0625 (min_periods=3 이전은 NaN)
        e = ind.ema(x, 3)
        self.assertTrue(np.isnan(e.iloc[1]))
        self.assertAlmostEqual(e.iloc[2], 2.25)
        self.assertAlmostEqual(e.iloc[4], 4.0625)

    def test_macd_definition(self):
        c = pd.Series(np.linspace(100, 130, 80) + np.sin(np.arange(80)))
        m = ind.macd(c, 12, 26, 9)
        line = ind.ema(c, 12) - ind.ema(c, 26)
        self.assertTrue(np.allclose(m["macd"].dropna(), line.dropna()))
        self.assertTrue(np.allclose((m["macd"] - m["signal"]).dropna(), m["hist"].dropna()))

    def test_stochastic_hand(self):
        high = pd.Series([10.0, 12, 11, 13, 14])
        low = pd.Series([8.0, 9, 9, 10, 12])
        close = pd.Series([9.0, 11, 10, 12, 13])
        s = ind.stochastic(high, low, close, k=3, smooth_k=1, d=2)
        # t=2: LL=8, HH=12 → (10-8)/4=50 ; t=3: LL=9, HH=13 → (12-9)/4=75 ; t=4: LL=9, HH=14 → (13-9)/5=80
        self.assertTrue(np.allclose(s["k"].iloc[2:].values, [50, 75, 80]))
        self.assertTrue(np.allclose(s["d"].iloc[3:].values, [62.5, 77.5]))

    def test_rsi_extremes(self):
        up = pd.Series(np.arange(1.0, 40))
        self.assertAlmostEqual(ind.rsi_wilder(up, 14).iloc[-1], 100.0)
        down = pd.Series(np.arange(40.0, 1, -1))
        self.assertAlmostEqual(ind.rsi_wilder(down, 14).iloc[-1], 0.0)

    def test_stochrsi_range(self):
        rng = np.random.default_rng(1)
        c = pd.Series(100 + np.cumsum(rng.normal(0, 1, 500)))
        r = ind.stoch_rsi(c).dropna()
        self.assertTrue((r["k"].between(0, 100)).all() and (r["d"].between(0, 100)).all())

    def test_vpci_hand(self):
        c = pd.Series([10.0, 11, 12, 11, 13])
        v = pd.Series([100.0, 200, 100, 300, 200])
        out = ind.vpci(c, v, short=2, long=3, signal=2)
        def vw(i, n):
            cs, vs = c.iloc[i - n + 1:i + 1], v.iloc[i - n + 1:i + 1]
            return (cs * vs).sum() / vs.sum()
        exp = {}
        for i in (2, 3, 4):
            vpc = vw(i, 3) - c.iloc[i - 2:i + 1].mean()
            vpr = vw(i, 2) / c.iloc[i - 1:i + 1].mean()
            vm = v.iloc[i - 1:i + 1].mean() / v.iloc[i - 2:i + 1].mean()
            exp[i] = vpc * vpr * vm
        for i in (2, 3, 4):
            self.assertAlmostEqual(out["vpci"].iloc[i], exp[i])
        # 신호선: 거래량 가중 2봉 평균
        s4 = (exp[3] * v.iloc[3] + exp[4] * v.iloc[4]) / (v.iloc[3] + v.iloc[4])
        self.assertAlmostEqual(out["vpcis"].iloc[4], s4)


class TestJudge(unittest.TestCase):
    def test_zone_cross_standard(self):
        idx = pd.RangeIndex(8)
        k = pd.Series([85, 90, 82, 50, 15, 12, 18, 40.0], index=idx)
        d = pd.Series([80, 85, 86, 60, 18, 14, 15, 30.0], index=idx)
        z = judge.zone_cross_state(k, d, 80, 20, "standard")
        # t=2: 하향 교차(90>85 → 82<86), z=84 ≥80 → Short ; t=6: 상향 교차(12<14 → 18>15), z=16.5 ≤20 → Long
        self.assertEqual(z["event"].tolist(), [0, 0, -1, 0, 0, 0, 1, 0])
        self.assertEqual(z["state"].tolist(), [0, 0, -1, -1, -1, -1, 1, 1])
        self.assertEqual(z["last_event"].iloc[5], 2)

    def test_zone_cross_momentum_and_age(self):
        idx = pd.RangeIndex(6)
        k = pd.Series([85, 90, 82, 70, 60, 50.0], index=idx)
        d = pd.Series([80, 85, 86, 75, 65, 55.0], index=idx)
        z = judge.zone_cross_state(k, d, 80, 20, "momentum", max_age_bars=2)
        self.assertEqual(z["event"].tolist(), [0, 0, 1, 0, 0, 0])
        self.assertEqual(z["state"].tolist(), [0, 0, 1, 1, 1, 0])  # 3봉 지나면 만료

    def test_pair_and(self):
        a = pd.Series([1, 1, -1, 0])
        b = pd.Series([1, -1, -1, 0])
        agree = (a == b) & (a != 0)
        self.assertEqual(np.where(agree, a, 0).tolist(), [1, 0, -1, 0])

    def test_score_values(self):
        w = {"macd": 4, "pair": 2, "vpci": 1}
        self.assertEqual(int(pipeline.score_from_dirs(1, 1, 1, w)), 100)
        self.assertEqual(int(pipeline.score_from_dirs(1, 1, -1, w)), 71)
        self.assertEqual(int(pipeline.score_from_dirs(1, -1, 1, w)), 43)
        self.assertEqual(int(pipeline.score_from_dirs(1, -1, -1, w)), 14)
        self.assertEqual(int(pipeline.score_from_dirs(1, 0, 0, w)), 57)
        self.assertEqual(int(pipeline.score_from_dirs(-1, -1, -1, w)), -100)
        st, sd = pipeline.strong_from_dirs([1, 1, 0], [1, -1, 0], [1, 1, 0])
        self.assertEqual(st.tolist(), [1, 0, 0])
        self.assertEqual(sd.tolist(), [1, 0, 0])
        self.assertEqual(pipeline.label(71, 0, 0), "Long 우세")
        self.assertEqual(pipeline.label(-100, 1, -1), "확실한 신호 Short")


def _synthetic_db(path: Path, n15: int = 6000, seed: int = 7):
    """15분봉 랜덤워크를 1h·4h로 묶어 바이낸스 캔들 표를 만든다."""
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE candles (source TEXT, symbol TEXT, period TEXT, ts INTEGER, open REAL, high REAL, low REAL,
      close REAL, volume REAL, quote_volume REAL, collected_at INTEGER, PRIMARY KEY (source, symbol, period, ts));
    CREATE TABLE series (source TEXT, symbol TEXT, metric TEXT, period TEXT, ts INTEGER, value REAL,
      collected_at INTEGER, PRIMARY KEY (source, symbol, metric, period, ts));
    """)
    rng = np.random.default_rng(seed)
    t0 = 1_700_006_400_000  # 2023-11-15 00:00 UTC (4시간 경계)
    ts = t0 + np.arange(n15) * 900_000
    close = 100 + np.cumsum(rng.normal(0, 0.5, n15))
    openp = np.r_[close[0], close[:-1]]
    high = np.maximum(openp, close) + rng.uniform(0, 0.3, n15)
    low = np.minimum(openp, close) - rng.uniform(0, 0.3, n15)
    vol = rng.uniform(10, 100, n15)
    df = pd.DataFrame({"ts": ts, "open": openp, "high": high, "low": low, "close": close, "volume": vol})
    rows = []
    for period, size in (("15m", 1), ("1h", 4), ("4h", 16)):
        g = df.groupby((df["ts"] - t0) // (size * 900_000))
        agg = pd.DataFrame({"ts": g["ts"].first(), "open": g["open"].first(), "high": g["high"].max(),
                            "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum(),
                            "cnt": g["ts"].count()})
        agg = agg[agg["cnt"] == size]
        rows += [("binance", "TESTUSDT", period, int(r.ts), r.open, r.high, r.low, r.close, r.volume, None, 0)
                 for r in agg.itertuples()]
    conn.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    days = sorted({int(t // 86_400_000 * 86_400_000) for t in ts})
    conn.executemany("INSERT INTO series VALUES (?,?,?,?,?,?,?)",
                     [("alternative.me", "CRYPTO", "fear_greed", "1d", d, 50 + i % 30, 0) for i, d in enumerate(days)])
    conn.commit()
    return conn


class TestNoLookahead(unittest.TestCase):
    def test_truncated_equals_full(self):
        rules = db.load_json("rules_v3.json")
        with tempfile.TemporaryDirectory() as d:
            conn = _synthetic_db(Path(d) / "t.db")
            full = pipeline.compute(conn, "TESTUSDT", rules)
            self.assertGreater(len(full), 300)
            cols = ["macd_dir", "sto_state", "srsi_state", "pair_dir", "vpci_dir", "score", "strong", "fng",
                    "macd", "vpci", "sto_k", "srsi_k"]
            for T in full.index[[200, 250, 300, -1]]:
                cut = pipeline.compute(conn, "TESTUSDT", rules, end_close_ms=int(T))
                a, b = full.loc[T, cols], cut.loc[T, cols]
                for c in cols:
                    if pd.isna(a[c]):
                        self.assertTrue(pd.isna(b[c]), c)
                    else:
                        self.assertAlmostEqual(float(a[c]), float(b[c]), places=9, msg=f"{c} @ {T}")
            ok = full[full["status"] == "ok"]
            conn.close()
            total = sum(rules["weights"].values())
            allowed = {round(100 * n / total) for n in range(-total, total + 1)}
            self.assertTrue(set(ok["score"].dropna().astype(int)) <= allowed)

    def test_missing_15m_is_data_short(self):
        rules = db.load_json("rules_v3.json")
        with tempfile.TemporaryDirectory() as d:
            conn = _synthetic_db(Path(d) / "t.db")
            full = pipeline.compute(conn, "TESTUSDT", rules)
            T = int(full.index[300])
            conn.execute("DELETE FROM candles WHERE period='15m' AND ts=?", (T - 900_000,))
            conn.commit()
            f2 = pipeline.compute(conn, "TESTUSDT", rules)
            self.assertEqual(f2.loc[T, "status"], "data_short")
            self.assertTrue(pd.isna(f2.loc[T, "score"]))
            conn.close()


class TestTrackAndExplain(unittest.TestCase):
    def test_outcome_fields(self):
        ret, call, hit, sh, bh = track.outcome_fields([100, 100, 100, 100], [101, 99, 100, 102],
                                                      [71, 71, -14, 0], [0, 1, 0, 0], [0, 1, 0, 0])
        self.assertEqual(call.tolist(), [1, 1, -1, 0])
        self.assertEqual(hit[:2].tolist(), [1, 0])
        self.assertTrue(np.isnan(hit[2]) and np.isnan(hit[3]))  # 보합, 방향 없음
        self.assertTrue(np.isnan(sh[0]) and sh[1] == 0)
        self.assertEqual(bh[0], 1)
        self.assertEqual(bh[1], 0)

    def test_validate_gpt(self):
        snap = {"rules_status": "temp", "fear_greed": {"value": 72, "classification_ko": "탐욕"},
                "items": [{"symbol": "BTCUSDT", "name": "비트코인", "score": 71, "label": "Long 우세", "strong": False,
                           "status": "ok", "macd_4h": "Long", "stoch_pair_1h": "Long", "vpci_15m": "Short",
                           "stochastic_1h": "Long", "stochrsi_1h": "Long"}]}
        conf = {**db.load_json("explain.json"), "prompt_version": "explain_v1.2", "max_chars_per_symbol": 200}   # v1 규칙 시험(운영은 10-06부터 v2)
        good = {"items": [{"symbol": "BTCUSDT", "text": "비트코인: MACD(4시간)와 1시간 조건은 Long, VPCI(15분)는 Short입니다. Long 우세지만 확실한 신호는 아닙니다."}],
                "overall": "공포탐욕지수는 탐욕 단계입니다(alternative.me). 임시 규칙으로 계산한 결과입니다."}
        self.assertIsNone(explain.validate(good, snap, conf))
        def body(t):
            return {"items": [{"symbol": "BTCUSDT", "text": t}], "overall": ""}
        self.assertIn("숫자", explain.validate(body("점수 71로 Long 우세입니다."), snap, conf))
        self.assertIn("숫자", explain.validate(body("목표는 구만 달러입니다."), snap, conf))
        self.assertIn("금지", explain.validate(body("수익보장입니다."), snap, conf))
        self.assertIn("모순", explain.validate(body("Short 우세입니다."), snap, conf))
        self.assertIn("확실한 신호", explain.validate(body("확실한 신호입니다."), snap, conf))
        self.assertIn("비어", explain.validate({"items": [], "overall": ""}, snap, conf))
        self.assertIn("종목", explain.validate({"items": [{"symbol": "ETHUSDT", "text": "x"}], "overall": ""}, snap, conf))
        self.assertIn("길이", explain.validate(body("가" * 201), snap, conf))

    def test_template_macd_only(self):
        it = {"symbol": "ETHUSDT", "name": "이더리움", "status": "ok", "score": -14, "strong": False,
              "label": pipeline.label(-14, 0, 0, -1, 1, 1), "macd_4h": "Short", "stoch_pair_1h": "Long",
              "vpci_15m": "Long", "stochastic_1h": "Long", "stochrsi_1h": "Long"}
        self.assertEqual(it["label"], "MACD만 Short")
        t = explain.template_text(it)
        self.assertIn("MACD(4시간)만 Short", t)
        self.assertIn("−14", t)
        both0 = dict(it, label="Long 우세", score=57, macd_4h="Long", stoch_pair_1h="방향 없음", vpci_15m="방향 없음",
                     stochastic_1h="방향 없음", stochrsi_1h="방향 없음")
        self.assertIn("모두 아직 기준", explain.template_text(both0))


class TestFixes(unittest.TestCase):
    """10-03 GPT-6 Astra·Claude Fable 검토에서 확인된 오류의 회귀 테스트."""

    def test_label_macd_only_needs_dominant_weight(self):
        self.assertEqual(pipeline.label(14, 0, 0, 1, -1, -1, {"macd": 4, "pair": 2, "vpci": 1}), "MACD만 Long")
        self.assertEqual(pipeline.label(0, 0, 0, 1, -1, -1, {"macd": 3, "pair": 2, "vpci": 1}), "방향 없음")

    def test_nan_indicator_outputs_no_direction(self):
        idx = pd.RangeIndex(6)
        k = pd.Series([15, 12, 18, np.nan, 25, 30.0], index=idx)
        d = pd.Series([18, 14, 15, np.nan, 20, 22.0], index=idx)
        z = judge.zone_cross_state(k, d, 80, 20, "standard")
        self.assertEqual(z["state"].tolist(), [0, 0, 1, 0, 1, 1])  # 결측 봉은 0, 다음 봉에서 기억 복구

    def test_last_cross_counts_only_real_flips(self):
        s = pd.Series([0, 1, 1, 0, 1, -1, -1], index=pd.RangeIndex(7))
        t = judge._last_change_time(s)
        self.assertTrue(np.isnan(t.iloc[2]))  # 0→1 (워밍업 끝)은 교차 아님
        self.assertTrue(np.isnan(t.iloc[4]))  # 0→1 (결측 복구)도 아님
        self.assertEqual(t.iloc[6], 5)        # 1→−1 은 교차
        t2 = judge._last_change_time(pd.Series([1, 0, -1, -1], index=pd.RangeIndex(4)))
        self.assertEqual(t2.iloc[2], 2)       # Long → 없음 → Short 도 바뀐 것

    def test_empty_subframes_and_warmup_and_gap(self):
        rules = db.load_json("rules_v3.json")
        with tempfile.TemporaryDirectory() as d:
            conn = _synthetic_db(Path(d) / "t.db")
            full = pipeline.compute(conn, "TESTUSDT", rules)
            self.assertEqual(full["status"].iloc[0], "not_ready")         # 워밍업
            self.assertTrue(pd.isna(full["score"].iloc[0]))
            T = int(full.index[300])
            conn.execute("DELETE FROM candles WHERE period='15m' AND ts=?", (T - 5 * 900_000,))  # T 직전 구간 누락
            conn.commit()
            self.assertEqual(pipeline.compute(conn, "TESTUSDT", rules).loc[T, "status"], "data_short")
            conn.execute("DELETE FROM candles WHERE period='1h'")
            conn.commit()
            f3 = pipeline.compute(conn, "TESTUSDT", rules)                 # 1h 전체가 없어도 멈추지 않음
            self.assertTrue((f3["status"] == "data_short").all())
            conn.close()


def _engine_db(path):
    conn = _synthetic_db(path)
    conn.executescript(db.SCHEMA)
    db._migrate(conn)
    conn.commit()
    return conn


class TestCycleAndNotify(unittest.TestCase):
    def test_fill_missing_and_late_rows(self):
        import run_cycle
        rules = db.load_json("rules_v3.json")
        rules = dict(rules, symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            last4 = conn.execute("SELECT MAX(ts) FROM candles WHERE period='4h'").fetchone()[0]
            T_last = last4 + run_cycle.FOUR_H
            T1 = T_last - 2 * run_cycle.FOUR_H
            for tbl in ("candles",):  # 마지막 두 4h 구간의 모든 봉을 지워 'T1 시점'으로 되돌린다
                conn.execute(f"DELETE FROM {tbl} WHERE ts + CASE period WHEN '15m' THEN 900000 WHEN '1h' THEN 3600000 "
                             f"ELSE 14400000 END > ?", (T1,))
            conn.commit()
            ins = run_cycle.fill_analyses(conn, rules, v, T1 + 60_000)
            self.assertEqual(ins, [T1])
            # 데이터 복구 없이 8시간이 지남 → 두 T 모두 4h 봉이 없어 60분 대기 뒤 data_short 로 기록
            ins2 = run_cycle.fill_analyses(conn, rules, v, T_last + 2 * 3_600_000)
            self.assertEqual(sorted(ins2), [T1 + run_cycle.FOUR_H, T_last])
            st = dict(conn.execute("SELECT t_close, status FROM analyses WHERE mode='live'").fetchall())
            self.assertEqual(st[T_last], "data_short")
            self.assertEqual(run_cycle.fill_analyses(conn, rules, v, T_last + 2 * 3_600_000), [])  # 멱등
            conn.close()

    def test_notify_claim_once_and_retry_failed(self):
        import notify
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            self.assertTrue(notify._claim(conn, 1, "v", "body"))
            self.assertFalse(notify._claim(conn, 1, "v", "body"))       # 이미 잡힘
            conn.execute("UPDATE discord_log SET status='failed'")
            self.assertTrue(notify._claim(conn, 1, "v", "body"))        # 실패는 재시도
            conn.execute("UPDATE discord_log SET status='failed', attempts=3")
            self.assertFalse(notify._claim(conn, 1, "v", "body"))       # 한도 초과
            conn.execute("UPDATE discord_log SET status='dry_run'")
            self.assertFalse(notify._claim(conn, 1, "v", "body"))
            conn.close()


class TestRound2(unittest.TestCase):
    """10-03 검토 2회차(GPT-6.1 Sol 재현·Claude Fable)에서 확인된 오류의 회귀 테스트."""

    def test_gap_resets_zone_memory(self):
        idx = pd.RangeIndex(8)
        k = pd.Series([90, 85, 50, 50, 50, 50, 50, 50.0], index=idx)
        d = pd.Series([85, 88, 55, 55, 55, 55, 55, 55.0], index=idx)   # 1번 봉: 80 이상 하향 교차 → Short
        self.assertEqual(judge.zone_cross_state(k, d, 80, 20)["state"].tolist(), [0, -1, -1, -1, -1, -1, -1, -1])
        brk = pd.Series([False, False, False, False, True, False, False, False], index=idx)
        z = judge.zone_cross_state(k, d, 80, 20, breaks=brk)
        self.assertEqual(z["state"].tolist(), [0, -1, -1, -1, 0, 0, 0, 0])   # 빠진 봉 뒤에는 기억 없음
        self.assertTrue(np.isnan(z["last_event"].iloc[5]))

    def test_bad_price_is_missing_bar(self):
        rules = db.load_json("rules_v3.json")
        with tempfile.TemporaryDirectory() as d:
            conn = _synthetic_db(Path(d) / "t.db")
            full = pipeline.compute(conn, "TESTUSDT", rules)
            T = int(full.index[-1])
            conn.execute("UPDATE candles SET close=? WHERE period='4h' AND ts=?", (float("inf"), T - 14_400_000))
            conn.commit()
            f = pipeline.compute(conn, "TESTUSDT", rules)
            self.assertNotIn(T, f.index[f["status"] == "ok"])
            conn.close()

    def test_validate_round2(self):
        snap = {"rules_status": "temp", "fear_greed": {"value": 72, "classification_ko": "탐욕"},
                "items": [{"symbol": "BTCUSDT", "name": "비트코인", "score": 71, "label": "Long 우세", "strong": False,
                           "status": "ok", "macd_4h": "Long", "stoch_pair_1h": "Long", "vpci_15m": "Short",
                           "stochastic_1h": "Long", "stochrsi_1h": "Long"}]}
        conf = {**db.load_json("explain.json"), "prompt_version": "explain_v1.2", "max_chars_per_symbol": 200}   # v1 규칙 시험(운영은 10-06부터 v2)

        def v(t, overall=""):
            return explain.validate({"items": [{"symbol": "BTCUSDT", "text": t}], "overall": overall}, snap, conf)
        self.assertIn("모순", v("Short 방향입니다."))
        self.assertIn("모순", v("MACD는 Short이고 VPCI는 Long입니다."))
        self.assertIn("숫자", v("점수는 칠십일입니다."))
        self.assertIn("숫자", v("몇 퍼센트 오를 수 있습니다."))
        self.assertIn("금지", v("확실한 신호는 아니지만 수익이 보장됩니다."))
        self.assertIn("전체 요약", v("Long 우세입니다.", "모든 종목에서 확실한 신호 Short입니다."))
        self.assertIsNone(v("MACD(4시간)와 Stochastic·StochRSI(1시간)는 Long, VPCI(15분)는 Short입니다. Long 우세지만 확실한 신호는 아닙니다."))
        self.assertIsNone(v("이만큼 엇갈리면 Long 우세라도 확실한 신호는 아닙니다."))
        # 템플릿 문장(숫자를 지운 것)은 방향 검사를 통과해야 한다
        it = dict(snap["items"][0])
        txt = explain.template_text(it)
        self.assertIsNone(explain.direction_conflict(txt, it))
        it2 = {"symbol": "XRPUSDT", "name": "리플", "status": "ok", "score": -14, "strong": False,
               "label": "MACD만 Short", "macd_4h": "Short", "stoch_pair_1h": "Long", "vpci_15m": "Long",
               "stochastic_1h": "Long", "stochrsi_1h": "Long"}
        self.assertIsNone(explain.direction_conflict(explain.template_text(it2), it2))

    def test_live_start_self_heal_and_on_time(self):
        import run_cycle
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            T = conn.execute("SELECT MAX(ts) FROM candles WHERE period='4h'").fetchone()[0] + run_cycle.FOUR_H
            orig = db.kv_set
            def boom(c, k, val):
                if k == "live_start":
                    raise RuntimeError("crash")
                return orig(c, k, val)
            db.kv_set = boom
            try:
                with self.assertRaises(RuntimeError):
                    run_cycle.fill_analyses(conn, rules, v, T + 60_000)
            finally:
                db.kv_set = orig
            self.assertIsNone(db.kv_get(conn, "live_start"))
            self.assertEqual(run_cycle.fill_analyses(conn, rules, v, T + 60_000), [])   # 행은 이미 있음
            self.assertEqual(db.kv_get(conn, "live_start"), db.utc_iso(T))               # 그래도 복구됨
            # 늦게 만든 분석은 운영 성적에서 빠진다
            conn.execute("UPDATE analyses SET created_at=? WHERE t_close=?", (T + run_cycle.FOUR_H + 1, T))
            conn.commit()
            self.assertEqual(track.summary(conn, "live", on_time_only=True), [])
            self.assertEqual(track.late_count(conn, v), 1)
            conn.close()

    def test_backfill_explanations_template_only(self):
        import run_cycle
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            db.save_rules_snapshot(conn, v, rules)
            frame = pipeline.compute(conn, "TESTUSDT", rules)
            ts = [int(t) for t in frame.index[-3:]]
            for t in ts:
                conn.executemany(pipeline.INSERT_SQL, pipeline.to_rows(frame.loc[[t]], "TESTUSDT", v, "live", t))
            conn.commit()
            n = run_cycle.backfill_explanations(conn, v, 1, ts[-1], ts[-1] + 60_000)
            self.assertEqual(n, 2)
            src = conn.execute("SELECT source, note FROM explanations ORDER BY t_close").fetchall()
            self.assertEqual([s[0] for s in src], ["template", "template"])
            self.assertIn("복구", src[0][1])
            self.assertEqual(run_cycle.backfill_explanations(conn, v, 1, ts[-1], ts[-1] + 60_000), 0)  # 멱등
            conn.close()

    def test_notify_redo_header_after_version_change(self):
        import notify
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            frame = pipeline.compute(conn, "TESTUSDT", rules)
            t = int(frame.index[-1])
            for ver in ("old", "new"):
                db.save_rules_snapshot(conn, ver, rules)
                conn.executemany(pipeline.INSERT_SQL, pipeline.to_rows(frame.loc[[t]], "TESTUSDT", ver, "live", t))
            conn.execute("INSERT INTO discord_log (t_close, rules_version, status, body, created_at, attempts) "
                         "VALUES (?, 'old', 'dry_run', 'x', 0, 1)", (t,))
            conn.commit()
            msg = notify.build_message(conn, t, "new", None)
            self.assertIn("규칙 변경으로 다시 계산", msg.splitlines()[0])
            self.assertNotIn("★", msg)
            self.assertNotIn("규칙 변경", notify.build_message(conn, t, "old", None).splitlines()[0])
            conn.close()


class TestChartExport(unittest.TestCase):
    """지표 그래프 데이터(chart_export): 판정 값과 같은지, 교차 표시가 판정 사건과 같은지, 원자적 쓰기."""

    def test_values_and_events_match_engine(self):
        import json
        import chart_export
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            full = pipeline.compute(conn, "TESTUSDT", rules)
            T = int(full.index[full["status"] == "ok"][-1])
            conn.executemany(pipeline.INSERT_SQL, pipeline.to_rows(full.loc[[T]], "TESTUSDT", v, "live", T))
            conn.commit()
            data = chart_export.build(conn, "TESTUSDT", rules, v, now_ms=T)
            self.assertIsNotNone(data)

            def at(block, key):
                return data[block][key][data[block]["t"].index(T)]
            for (block, key), col in {("macd", "macd"): "macd", ("macd", "signal"): "macd_signal",
                                      ("sto", "k"): "sto_k", ("srsi", "k"): "srsi_k",
                                      ("vpci", "v"): "vpci", ("vpci", "s"): "vpcis"}.items():
                ref = float(full.loc[T, col])
                self.assertAlmostEqual(at(block, key) / ref, 1.0, delta=1e-5, msg=col)
            self.assertEqual(data["analyses"][-1]["t"], T)
            # 교차 표시 = judge 의 사건(같은 구간)
            c1 = db.load_candles(conn, "TESTUSDT", "1h")
            pr = judge.pair_frame(c1, rules["stoch_pair"], db.PERIOD_MS["1h"])
            since = int(data["price"]["t"][0])
            want = sorted(int(t) for t, e in pr["sto_event"].items() if e != 0 and t >= since)
            got = sorted(e["t"] for e in data["events"] if e["ind"] == "sto")
            self.assertEqual(got, want)
            # 원자적 쓰기, NaN 은 null
            out = Path(d) / "charts" / "X.json"
            chart_export.write_atomic(out, {"a": chart_export._r(float("nan")), "b": chart_export._r(1.23456789)})
            self.assertEqual(json.loads(out.read_text()), {"a": None, "b": 1.23457})
            self.assertEqual([p.name for p in out.parent.iterdir()], ["X.json"])  # 임시 파일 남지 않음
            conn.close()

    def test_no_candles_returns_none(self):
        import chart_export
        rules = dict(db.load_json("rules_v3.json"), symbols=["NONEUSDT"])
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            self.assertIsNone(chart_export.build(conn, "NONEUSDT", rules, "v"))
            conn.close()


class TestRound3(unittest.TestCase):
    """10-03 GPT-6 Astra 코드 검토(사용 한도로 중단 전 재현분) 회귀 테스트."""

    def test_validate_bypasses(self):
        snap = {"rules_status": "temp", "fear_greed": {"value": 72, "classification_ko": "탐욕"},
                "items": [{"symbol": "BTCUSDT", "name": "비트코인", "score": 71, "label": "Long 우세", "strong": False,
                           "status": "ok", "macd_4h": "Long", "stoch_pair_1h": "Long", "vpci_15m": "Short",
                           "stochastic_1h": "Long", "stochrsi_1h": "Long"}]}
        conf = {**db.load_json("explain.json"), "prompt_version": "explain_v1.2", "max_chars_per_symbol": 200}   # v1 규칙 시험(운영은 10-06부터 v2)

        def v(t, s=snap):
            return explain.validate({"items": [{"symbol": "BTCUSDT", "text": t}], "overall": ""}, s, conf)
        self.assertIn("모순", v("VPCI는 long입니다."))
        self.assertIn("모순", v("VPCI는 상승 방향입니다."))
        self.assertIn("숫자", v("점수는 백입니다."))
        self.assertIn("이중 부정", v("확실한 신호는 아니지 않습니다."))
        strong = {**snap, "items": [dict(snap["items"][0], label="확실한 신호 Long", strong=True, vpci_15m="Long", score=100)]}
        self.assertIn("부정", v("네 지표가 같지만 확실한 신호는 아닙니다.", strong))
        self.assertIsNone(v("네 지표가 모두 Long이라 확실한 신호입니다.", strong))
        self.assertIsNone(v("MACD(4시간)는 Long, VPCI(15분)는 Short입니다. Long 우세지만 확실한 신호는 아닙니다."))

    def test_ohlc_out_of_range_is_missing(self):
        rules = db.load_json("rules_v3.json")
        with tempfile.TemporaryDirectory() as d:
            conn = _synthetic_db(Path(d) / "t.db")
            ts = conn.execute("SELECT MAX(ts) FROM candles WHERE period='1h'").fetchone()[0]
            conn.execute("UPDATE candles SET close = high * 2 WHERE period='1h' AND ts=?", (ts,))
            conn.commit()
            c1 = db.load_candles(conn, "TESTUSDT", "1h")
            self.assertNotIn(ts + 3_600_000, c1.index)
            conn.close()

    def test_summary_has_same_sample_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            rows = track.summary(conn, "replay")
            self.assertEqual(rows, [])  # 표가 비어도 오류 없이
            conn.close()


def _insert_live(conn, rules, version, T):
    """T(봉 마감) 시점 운영 분석 한 행을 넣는다."""
    frame = pipeline.compute(conn, "TESTUSDT", rules)
    conn.executemany(pipeline.INSERT_SQL, pipeline.to_rows(frame.loc[[T]], "TESTUSDT", version, "live", T + 60_000))
    conn.commit()


class TestRound4(unittest.TestCase):
    """10-04 GPT-6.1 Sol 코드 검토(전 단계) 회귀 테스트."""

    def test_scoring_skips_bad_next_bar(self):
        import run_cycle
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            T = conn.execute("SELECT MAX(ts) FROM candles WHERE period='4h'").fetchone()[0]  # 마지막 4h 봉의 시작 = 분석 T
            _insert_live(conn, rules, v, T)
            conn.execute("UPDATE candles SET close = high * 2 WHERE period='4h' AND ts=?", (T,))   # 다음 봉이 깨짐
            conn.commit()
            track.score_pending(conn, "live")
            self.assertIsNone(conn.execute("SELECT 1 FROM outcomes WHERE t_close=?", (T,)).fetchone())  # 보류
            conn.execute("UPDATE candles SET close = (high + low) / 2 WHERE period='4h' AND ts=?", (T,))
            conn.commit()
            track.score_pending(conn, "live")
            self.assertIsNotNone(conn.execute("SELECT 1 FROM outcomes WHERE t_close=?", (T,)).fetchone())
            conn.close()

    def test_validate_round4(self):
        snap = {"rules_status": "temp", "fear_greed": {"value": 72, "classification_ko": "탐욕"},
                "items": [{"symbol": "BTCUSDT", "name": "비트코인", "score": 71, "label": "Long 우세", "strong": False,
                           "status": "ok", "macd_4h": "Long", "stoch_pair_1h": "Long", "vpci_15m": "Short",
                           "stochastic_1h": "Long", "stochrsi_1h": "Long"}]}
        conf = {**db.load_json("explain.json"), "prompt_version": "explain_v1.2", "max_chars_per_symbol": 200}   # v1 규칙 시험(운영은 10-06부터 v2)

        def v(t, s=snap, overall=""):
            return explain.validate({"items": [{"symbol": "BTCUSDT", "text": t}], "overall": overall}, s, conf)
        self.assertIn("모순", v("vpci는 Long입니다."))
        self.assertIn("모순", v("VPCI는 상승세입니다."))
        self.assertIn("부정", v("MACD는 Long이 아닙니다."))
        self.assertIn("숫자", v("점수는 아흔입니다."))
        self.assertIn("방향", v("MACD는 Long입니다.", overall="모든 코인이 상승세입니다."))
        strong = {**snap, "items": [dict(snap["items"][0], label="확실한 신호 Long", strong=True, vpci_15m="Long", score=100)]}
        self.assertIn("부정", v("확실한 신호라고 볼 수 없습니다.", strong))
        # 정상 문장은 그대로 통과
        self.assertIsNone(v("네 지표가 모두 Long이라 확실한 신호입니다.", strong))
        self.assertIsNone(v("MACD(4시간)는 Long, VPCI(15분)는 Short입니다. Long 우세지만 확실한 신호는 아닙니다."))

    def test_chart_has_no_future_analyses(self):
        import chart_export
        import run_cycle
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            T = conn.execute("SELECT MAX(ts) FROM candles WHERE period='4h'").fetchone()[0]
            _insert_live(conn, rules, v, T)
            past = T - run_cycle.FOUR_H
            data = chart_export.build(conn, "TESTUSDT", rules, v, now_ms=past)
            self.assertTrue(all(a["t"] <= past for a in data["analyses"]))
            conn.close()


class TestRound5(unittest.TestCase):
    """10-04 Claude Fable 5.1 최종 검토: 정상 문장을 잘못 거르던 것."""

    def test_validate_no_false_rejection(self):
        snap = {"rules_status": "temp", "fear_greed": {"value": 72, "classification_ko": "탐욕"},
                "items": [{"symbol": "BTCUSDT", "name": "비트코인", "score": 57, "label": "Long 우세", "strong": False,
                           "status": "ok", "macd_4h": "Long", "stoch_pair_1h": "방향 없음", "vpci_15m": "Short",
                           "stochastic_1h": "방향 없음", "stochrsi_1h": "방향 없음"}]}
        conf = {**db.load_json("explain.json"), "prompt_version": "explain_v1.2", "max_chars_per_symbol": 200}   # v1 규칙 시험(운영은 10-06부터 v2)

        def v(t):
            return explain.validate({"items": [{"symbol": "BTCUSDT", "text": t}], "overall": ""}, snap, conf)
        self.assertIsNone(v("MACD(4시간)는 Long, Stochastic·StochRSI(1시간)는 방향 없음, VPCI(15분)는 Short입니다."))
        self.assertIsNone(v("확실한 신호라고 볼 수 없습니다."))
        self.assertIsNone(v("확실한 신호에는 못 미칩니다."))
        self.assertIsNone(v("가격이 한 방향으로 움직였습니다."))
        # 여전히 걸러야 하는 것
        self.assertIn("숫자", v("점수는 두 배입니다."))
        self.assertIn("모순", v("점수는 방향 없음입니다."))
        self.assertIn("확실한 신호", v("확실한 신호입니다."))


class TestConditionsDoc(unittest.TestCase):
    """정미님 조건서(10-03) 방식: 1시간 지표는 %K·%D 위치와 기울기, VPCI 는 0선 또는 SMA 시그널 교차."""

    def test_kd_state(self):
        idx = pd.Index(np.arange(7) * 3_600_000)
        k = pd.Series([10, 20, 30, 25, 20, 15, 18], index=idx, dtype=float)
        d = pd.Series([15, 18, 22, 24, 22, 18, 17], index=idx, dtype=float)
        r = judge.kd_state(k, d)
        # 0: 앞 봉 없음 / 1: 상향 교차 / 2: 위·오름 / 3: 위지만 내림 → 0 / 4: 하향 교차 / 5: 아래·내림 / 6: 상향 교차
        self.assertEqual(r["state"].tolist(), [0, 1, 1, 0, -1, -1, 1])
        self.assertEqual(r["event"].tolist(), [0, 1, 0, 0, -1, 0, 1])
        brk = pd.Series([False, False, False, False, False, True, False], index=idx)
        self.assertEqual(judge.kd_state(k, d, brk)["state"].tolist()[5], 0)   # 앞 봉이 빠지면 기울기를 모름

    def _vpci(self, v, s):
        idx = pd.Index(np.arange(len(v)) * 900_000)
        orig = judge.ind.vpci
        judge.ind.vpci = lambda *a, **kw: pd.DataFrame({"vpci": pd.Series(v, index=idx, dtype=float),
                                                       "vpcis": pd.Series(s, index=idx, dtype=float)})
        try:
            c15 = pd.DataFrame({"close": np.ones(len(v)), "volume": np.ones(len(v))}, index=idx)
            return judge.vpci_frame(c15, {"short": 5, "long": 20, "signal": 20, "signal_ma": "sma",
                                          "cross_target": "zero_or_signal"}, 900_000)["vpci_dir"].tolist()
        finally:
            judge.ind.vpci = orig

    def test_vpci_zero_or_signal(self):
        # 1: 0선·시그널 상향 / 2: 유지 / 3: 시그널 하향 / 4: 유지 / 5: 0선 하향 / 6: 시그널 상향
        self.assertEqual(self._vpci([-1, 1, 2, 1.5, 0.5, -0.5, -0.2], [0, 0.5, 1, 1.8, 1.0, 0.0, -0.5]),
                         [0, 1, 1, -1, -1, -1, 1])
        # 같은 봉에 0선 하향과 시그널 상향이 함께 나면 사건으로 보지 않음
        self.assertEqual(self._vpci([1, 0.2, -0.1], [2, 0.5, -0.3]), [0, 0, 0])

    def test_vpci_sma_signal(self):
        import indicators as ind
        c = pd.Series(np.linspace(100, 120, 60) + np.sin(np.arange(60)))
        vol = pd.Series(np.linspace(10, 50, 60))
        a = ind.vpci(c, vol, 5, 20, 20, "sma")
        self.assertTrue(np.allclose(a["vpcis"].dropna(), ind.sma(a["vpci"], 20).dropna()))

    def test_pipeline_runs_with_conditions_rules(self):
        rules = db.load_json("rules_v3.json")
        rules = dict(rules, symbols=["TESTUSDT"],
                     stoch_pair=dict(rules["stoch_pair"], mode="kd_state"),
                     vpci=dict(rules["vpci"], signal_ma="sma", cross_target="zero_or_signal"))
        with tempfile.TemporaryDirectory() as dd:
            conn = _synthetic_db(Path(dd) / "t.db")
            out = pipeline.compute(conn, "TESTUSDT", rules)
            ok = out[out["status"] == "ok"]
            self.assertGreater(len(ok), 10)
            self.assertTrue(set(ok["pair_dir"].unique()) <= {-1, 0, 1})
            agree = ((ok["macd_dir"] == ok["pair_dir"]) & (ok["pair_dir"] == ok["vpci_dir"]) & (ok["macd_dir"] != 0)).astype(int)
            # 10-06: 순서 조건(VPCI 가 정렬 뒤에 돌아야 함)이 켜져 있으면 확실한 신호는 '세 방향 일치'의 일부
            self.assertTrue(((ok["strong"] == 1) <= (agree == 1)).all())
            conn.close()


class TestDiagnosis1004(unittest.TestCase):
    """10-04 예측률 진단(GPT-6.1 Sol 코드 감사) 반영: RSI 첫 값, StochRSI 교차 예외, 비교 허용오차, 운영 성적 1시간."""

    def test_rsi_wilder_seed_is_sma_of_first_n(self):
        c = pd.Series([44.0, 44.3, 44.1, 44.6, 44.9, 45.3, 45.1, 45.4, 45.8, 46.1, 45.9, 46.2, 46.0, 46.5, 46.3, 46.8, 46.6])
        n = 14
        delta = c.diff()
        g, l = delta.clip(lower=0), -delta.clip(upper=0)
        ag, al = g.iloc[1:n + 1].mean(), l.iloc[1:n + 1].mean()     # 처음 14개 변화의 단순 평균
        exp = [100 - 100 / (1 + ag / al)]
        for i in range(n + 1, len(c)):
            ag, al = (ag * (n - 1) + g.iloc[i]) / n, (al * (n - 1) + l.iloc[i]) / n
            exp.append(100 - 100 / (1 + ag / al))
        got = ind.rsi_wilder(c, n)
        self.assertTrue(got.iloc[:n].isna().all())
        self.assertTrue(np.allclose(got.iloc[n:].values, exp))

    def test_rsi_matches_stockcharts_example(self):
        # 외부 기준(10-04 Fable 제안): StockCharts RSI 설명 예제의 종가 33개와 공개된 RSI 값(소수점 2자리)
        c = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826, 45.8931,
             46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521,
             45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628, 43.1314]
        pub = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
               41.87, 45.46, 37.30, 33.08, 37.77]
        got = ind.rsi_wilder(pd.Series(c), 14).dropna().round(2).tolist()
        self.assertEqual(got, pub)

    def test_rsi_short_data_is_nan(self):
        self.assertTrue(ind.rsi_wilder(pd.Series(np.arange(14.0)), 14).isna().all())     # 변화 13개 < 14
        r = ind.rsi_wilder(pd.Series(np.arange(15.0)), 14)                                # 변화 14개 → 마지막 값만
        self.assertEqual(int(r.notna().sum()), 1)
        self.assertEqual(r.iloc[-1], 100.0)                                               # 하락 없이 상승만

    def test_kd_boundaries(self):
        idx = pd.Index(np.arange(2) * 3_600_000)
        both = judge.kd_state(pd.Series([30.0, 32.0], index=idx), pd.Series([31.0, 31.0], index=idx), cross_exception=False)
        self.assertEqual(both["state"].iloc[1], 1)        # 교차와 상승이 함께면 교차 예외가 없어도 Long
        tiny = judge.kd_state(pd.Series([20.0, 30.0 + judge.KD_EPS / 2], index=idx), pd.Series([25.0, 30.0], index=idx))
        self.assertEqual(tiny["state"].iloc[1], 0)        # 허용오차 안의 차이는 같다고 봄

    def test_on_time_equals_bar_wait(self):
        import run_cycle
        self.assertEqual(run_cycle.WAIT_MS, track.ON_TIME_MS)   # 봉을 기다리는 시간 = 제때로 치는 시간(10-04 Fable 제안)

    def test_stochrsi_has_no_cross_exception(self):
        idx = pd.Index(np.arange(2) * 3_600_000)
        k = pd.Series([30.0, 28.0], index=idx)   # %K가 %D를 위로 넘었지만 %K 자체는 내려감
        d = pd.Series([31.0, 25.0], index=idx)
        self.assertEqual(judge.kd_state(k, d, cross_exception=True)["state"].iloc[1], 1)    # Stochastic: 교차면 Long
        self.assertEqual(judge.kd_state(k, d, cross_exception=False)["state"].iloc[1], 0)   # StochRSI: 오르지 않으면 없음
        self.assertEqual(judge.kd_state(k, d, cross_exception=False)["event"].iloc[1], 1)   # 그래프 교차 표시는 그대로
        rules = db.load_json("rules_v3.json")["stoch_pair"]
        self.assertTrue(rules["stoch"]["cross_exception"])
        self.assertFalse(rules["stochrsi"]["cross_exception"])

    def test_kd_float_noise_is_no_direction(self):
        idx = pd.Index(np.arange(2) * 3_600_000)
        k = pd.Series([100.0, 100.00000000000001], index=idx)
        d = pd.Series([100.0, 100.0000000000001], index=idx)
        self.assertEqual(judge.kd_state(k, d)["state"].tolist(), [0, 0])

    def test_on_time_is_one_hour_and_board_matches(self):
        import re
        import run_cycle
        board_src = (Path(__file__).resolve().parents[2] / "03_백엔드" / "app" / "board.py").read_text(encoding="utf-8")
        m = re.search(r"^ON_TIME = ([\d_]+)", board_src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1).replace("_", "")), track.ON_TIME_MS)
        self.assertEqual(track.ON_TIME_MS, 3_600_000)
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            T = conn.execute("SELECT MAX(ts) FROM candles WHERE period='4h'").fetchone()[0] + run_cycle.FOUR_H
            run_cycle.fill_analyses(conn, rules, v, T + 60_000)
            conn.execute("UPDATE analyses SET created_at=? WHERE t_close=?", (T + 30 * 60_000, T))
            conn.commit()
            self.assertEqual(len(track.summary(conn, "live", on_time_only=True)), 1)   # 30분 뒤 = 제때
            self.assertEqual(track.late_count(conn, v), 0)
            conn.execute("UPDATE analyses SET created_at=? WHERE t_close=?", (T + 2 * 3_600_000, T))
            conn.commit()
            self.assertEqual(track.summary(conn, "live", on_time_only=True), [])        # 2시간 뒤 = 늦음
            self.assertEqual(track.late_count(conn, v), 1)
            conn.close()


class TestChase(unittest.TestCase):
    """10-04 E2 추격 주의: 확실한 신호가 켜지기 전 24시간 신호 방향 움직임과 그 뒤 성적."""

    def test_chase_frame_and_buckets(self):
        import replay
        H = track.FOUR_H
        idx = pd.Index(np.arange(20) * H)
        close = pd.Series(100.0, index=idx)
        close.iloc[6] = 110.0      # T=6: 24시간 전(T=0) 100 → +10%
        close.iloc[7] = 105.0      # 4시간 뒤 내림
        close.iloc[12] = 99.0      # 24시간 뒤 99
        full = pd.DataFrame({"close": close})
        f = pd.DataFrame({"close": close, "strong": 0, "strong_dir": 0}, index=idx)
        f.loc[idx[6], ["strong", "strong_dir"]] = [1, 1]     # Long 신호, 이미 +10% 움직인 뒤
        f.loc[idx[13], ["strong", "strong_dir"]] = [1, -1]   # Short 신호, 직전 24시간(T=7 105 → 100) 신호 방향 +4.76%
        cf = replay.chase_frame(full, f)
        self.assertAlmostEqual(cf.loc[idx[6], "move"], 10.0)
        self.assertLess(cf.loc[idx[6], "r4"], 0)             # Long 이었는데 내림
        self.assertLess(cf.loc[idx[6], "r24"], 0)
        self.assertAlmostEqual(cf.loc[idx[13], "move"], 100 * (1 - 100 / 105), places=6)   # Short: 하락이 + 방향
        st = replay.chase_stats({"T": cf}, 0, 20 * H)
        big = [b for b in st if b["lo"] == 5.0][0]["by_symbol"]["T"]
        self.assertEqual((big["n"], big["hit4_pct"], big["hit24_pct"]), (1, 0.0, 0.0))
        mid = [b for b in st if b["lo"] == 2.0][0]["by_symbol"]["T"]
        self.assertEqual(mid["n"], 1)
        self.assertIsNone(mid["hit4_pct"])                   # 다음 4시간 보합(100→100)은 빼고 셈
        self.assertEqual(replay.CHASE_WARN_PCT, 5.0)

    def test_discord_chase_note(self):
        import notify
        self.assertEqual(notify.chase_note(None), "")
        self.assertEqual(notify.chase_note(1.234), " · 켜지기 전 24시간 +1.2%")
        self.assertEqual(notify.chase_note(6.0), " · 켜지기 전 24시간 +6.0% · 추격 주의")
        self.assertEqual(notify.chase_note(-2.5), " · 켜지기 전 24시간 -2.5%")


class TestCodexExplain(unittest.TestCase):
    """10-04 G1: Codex CLI(Plus 로그인)로 해설. 가짜 codex 실행 파일로 인자·출력 처리만 시험(실제 호출 없음)."""

    def test_call_codex_args_and_output(self):
        import os
        import stat
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "codex"
            log = Path(d) / "args.txt"
            fake.write_text("#!/bin/bash\n"
                            f"printf '%s\\n' \"$@\" > '{log}'\n"
                            "cat > /dev/null\n"
                            "while [ $# -gt 0 ]; do if [ \"$1\" = -o ]; then out=\"$2\"; fi; shift; done\n"
                            "printf '%s' '{\"items\":[{\"symbol\":\"BTCUSDT\",\"text\":\"t\"}],\"overall\":\"o\"}' > \"$out\"\n",
                            encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            conf = {"prompt_file": "prompts/explain_v1.md", "codex_bin": str(fake), "codex_model": "gpt-6-luna",
                    "codex_effort": "low", "codex_timeout_sec": 30}
            out = explain.call_codex(conf, {"symbols": []})
            self.assertEqual(out["overall"], "o")
            args = log.read_text(encoding="utf-8").split("\n")
            for need in ("exec", "gpt-6-luna", "read-only", "--ephemeral", "--output-schema", "--skip-git-repo-check",
                         "--ignore-user-config"):
                self.assertIn(need, args)
            self.assertIn("model_reasoning_effort=low", args)
            fake.write_text("#!/bin/bash\necho 'usage limit reached' >&2\nexit 3\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as cm:
                explain.call_codex(conf, {"symbols": []})
            self.assertIn("usage limit reached", str(cm.exception))   # 실패 원인을 남긴다

    def test_codex_env_has_no_secrets(self):
        # 10-05 01:00 운영 리허설 실패: .env의 OPENAI_API_KEY가 Codex 환경으로 들어감 → 최소 환경만 넘긴다
        import os
        old = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-not-real"
        os.environ["CODEX_API_KEY"] = "x"
        try:
            env = explain._codex_env()
        finally:
            os.environ.pop("CODEX_API_KEY", None)
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_API_KEY", env)
        self.assertIn("HOME", env)
        self.assertTrue(set(env) <= {"HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "PATH"})

    def test_pair_phrase_is_not_stochastic(self):
        # 10-04 Luna 리허설 실제 문장. 묶음("스토캐스틱 조합")을 Stochastic 으로 읽어 거부하던 오거부
        src = {"label": "Short 우세", "macd_4h": "Short", "stochastic_1h": "Short", "stochrsi_1h": "방향 없음",
               "stoch_pair_1h": "방향 없음", "vpci_15m": "Short"}
        t = ("MACD와 1시간봉 스토캐스틱, 15분봉 VPCI는 Short이고, 1시간봉 스토캐스틱 RSI와 스토캐스틱 조합은 방향 없음입니다. "
             "Short 우세지만 확실한 신호는 아닙니다.")
        self.assertIsNone(explain.direction_conflict(t, src))
        self.assertIsNone(explain.direction_conflict("1시간 조건은 방향 없음입니다.", src))
        # 진짜 모순은 여전히 잡는다
        self.assertIsNotNone(explain.direction_conflict("스토캐스틱 조합은 Short입니다.", src))
        self.assertIsNotNone(explain.direction_conflict("1시간봉 스토캐스틱은 Long입니다.", src))
        # "스토캐스틱 RSI 조합"은 StochRSI로 읽어 모순을 잡는다(Fable 반례)
        src2 = dict(src, stochrsi_1h="Long")
        self.assertIsNotNone(explain.direction_conflict("스토캐스틱 RSI 조합은 방향 없음입니다.", src2))


if __name__ == "__main__":
    unittest.main()


class TestExplainV2(unittest.TestCase):
    """10-06 v2: 입력에 있는 숫자만, 지켜볼 조건 문장 검사."""
    SNAP = {"rules_status": "temp", "fear_greed": {"value": 73, "classification_ko": "탐욕"}, "next_analysis_kst": "21:00",
            "items": [{"symbol": "XRPUSDT", "name": "리플", "score": -71, "label": "Short 우세", "strong": False, "status": "ok",
                       "macd_4h": "Short", "stoch_pair_1h": "Short", "vpci_15m": "Long", "stochastic_1h": "Short",
                       "stochrsi_1h": "Short", "side": "Short", "to_strong": ["VPCI(15분)"],
                       "past_same_score": {"period": "2018-01-01–2023-12-31", "n": 1391, "same_direction_pct": 46.6}}]}

    def setUp(self):
        self.conf = {**db.load_json("explain.json"), "prompt_version": "explain_v2.0", "max_chars_per_symbol": 240}

    def v(self, t, overall="공포탐욕지수는 탐욕(73)입니다(alternative.me). 다음 분석 시각은 21:00입니다."):
        return explain.validate({"items": [{"symbol": "XRPUSDT", "text": t}], "overall": overall}, self.SNAP, self.conf)

    def test_good(self):
        self.assertIsNone(self.v("리플은 Short 우세로, MACD(4시간)와 1시간 조건은 Short이고 VPCI(15분)는 Long입니다. "
                                 "VPCI(15분)가 Short으로 바뀌면 확실한 신호 Short가 됩니다. "
                                 "과거 기록으로는 같은 점수에서 4시간 뒤 Short 쪽으로 간 비율이 46.6%였습니다(n=1391)."))

    def test_number_not_in_input(self):
        self.assertIn("입력에 없는 숫자", self.v("리플은 Short 우세입니다. 과거 비율은 52.1%였습니다."))
        self.assertIn("입력에 없는 숫자", self.v("리플은 Short 우세입니다.", overall="다음 분석은 22:00입니다."))

    def test_korean_numeral(self):
        self.assertIn("한글 숫자", self.v("리플은 Short 우세이며 오십 퍼센트 확률입니다."))

    def test_conditional_wrong_direction_or_indicator(self):
        self.assertIn("조건 문장", self.v("리플은 Short 우세입니다. VPCI(15분)가 Long으로 바뀌면 확실한 신호 Long이 됩니다."))
        self.assertIn("조건 문장", self.v("리플은 Short 우세입니다. MACD(4시간)가 Long으로 바뀌면 확실한 신호가 됩니다."))

    def test_key_name_rejected(self):
        self.assertIn("항목 이름", self.v("리플은 Short 우세입니다.", overall="공포탐욕지수는 탐욕이며 value는 73입니다(alternative.me)."))

    def test_still_checks_direction_outside_conditional(self):
        self.assertIsNotNone(self.v("리플은 Short 우세이고 VPCI(15분)는 Short입니다."))


class TestConditions1006(unittest.TestCase):
    """10-06 호연 P3: 가짜 신호 거르기(31), 정렬 뒤 VPCI(32)."""

    def test_strong_sequence_requires_vpci_after_alignment(self):
        M15, H1 = 900_000, 3_600_000
        idx = pd.Index([i * M15 for i in range(1, 17)])          # 15분봉 마감 16개(4시간)
        macd = pd.Series([1], index=pd.Index([0]))                 # 4시간: 처음부터 Long
        pair = pd.Series([0, 1, 1, 1], index=pd.Index([0, H1, 2 * H1, 3 * H1]))   # 1시간: 1시간째부터 Long → 정렬 시작 H1
        vdir = pd.Series(1, index=idx)
        # (가) VPCI 가 정렬 전(30분)에 Long 으로 돌았으면 정렬 뒤에도 확실한 신호 아님
        last_a = pd.Series(2 * M15, index=idx)
        self.assertTrue((judge.strong_sequence(macd, pair, vdir, last_a) == 0).all())
        # (나) VPCI 가 정렬 뒤(1시간 30분)에 돌면 그때부터 확실한 신호
        last_b = pd.Series(np.where(idx >= 6 * M15, 6 * M15, 2 * M15), index=idx)
        got = judge.strong_sequence(macd, pair, vdir, last_b)
        self.assertEqual(int(got[5 * M15]), 0)
        self.assertEqual(int(got[6 * M15]), 1)
        self.assertEqual(int(got[16 * M15]), 1)

    def test_fake_filter_blocks_long_above_example_threshold(self):
        rules = db.load_json("rules_v3.json")
        p = dict(rules["stoch_pair"], mode="kd_state")
        k = pd.Series([70.0, 85.0, 83.0]); d = pd.Series([75.0, 86.0, 80.0])   # 3번째 봉: %D 위로 교차했지만 %K 는 80 이상에서 내려옴
        st = judge.kd_state(k, d, None, True)["state"]
        self.assertEqual(int(st.iloc[2]), 1)                        # 교차 예외만 보면 Long
        falling = (k.shift(1) >= 80) & (k < k.shift(1))
        self.assertTrue(bool(falling.iloc[2]))                      # 거르기 조건에 걸림
        self.assertEqual(p.get("fake_filter", {}).get("upper"), 75)  # 공개 예시 설정


class TestDiscordAlerts1006(unittest.TestCase):
    """10-06 P5: 확신도 ±100·확실한 신호 알림 대상."""

    def _db(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        return conn

    def _row(self, conn, sym, t, ver, score, strong=0, sd=0, created=1):
        conn.execute("INSERT INTO analyses (symbol, t_close, rules_version, mode, status, score, strong, strong_dir, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (sym, t, ver, "live", "ok", score, strong, sd, created))

    def test_candidates(self):
        conn, H = self._db(), notify.FOUR_H
        T = 10 * H
        self._row(conn, "BTCUSDT", T - H, "old", -71); self._row(conn, "BTCUSDT", T, "new", -100)          # 새 ±100(이전 버전과 비교)
        self._row(conn, "ETHUSDT", T - H, "new", -100); self._row(conn, "ETHUSDT", T, "new", -100)         # 이미 −100 → 없음
        self._row(conn, "XRPUSDT", T - H, "new", 100); self._row(conn, "XRPUSDT", T, "new", 100, 1, 1)     # 확실한 신호 새로 켜짐
        got = notify.alert_candidates(conn, T, "new")
        self.assertEqual(got, [("BTCUSDT", "score100"), ("XRPUSDT", "strong")])


class TestStrong15(unittest.TestCase):
    """10-07 15분 확실한 신호: 바뀐 봉만 기록(멱등), 두 가지 채점, 요약, 알림 설정, 보드·배포 서명과의 상수 일치."""

    M15 = 900_000

    def _mem(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        return conn

    def _series(self, vals, t0=0):
        idx = pd.Index([t0 + i * self.M15 for i in range(len(vals))])
        return pd.Series(vals, index=idx, dtype="int64"), pd.Series([100.0 + i for i in range(len(vals))], index=idx)

    def test_record_transitions_only_and_idempotent(self):
        import strong15
        conn = self._mem()
        s, c = self._series([0, 0, 1, 1, 0, -1, -1, 1, 1, 1])
        new = strong15.record(conn, "TESTUSDT", "v", s, c, now=1)
        self.assertEqual([(r["t_close"] // self.M15, r["kind"], r["dir"]) for r in new],
                         [(2, "on", 1), (4, "off", 0), (5, "on", -1), (7, "flip", 1)])
        again = strong15.record(conn, "TESTUSDT", "v", s, c, now=2)        # 같은 상태를 다시 넣어도 행이 늘지 않음
        self.assertEqual(again, [])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM strong15").fetchone()[0], 4)
        # 다음 실행: 마지막 기록 뒤의 봉만 본다. 구간이 뒤로 밀려도(앞 봉이 빠져도) 이어진다
        s2, c2 = self._series([1, 1, 0, 0], t0=8 * self.M15)
        new2 = strong15.record(conn, "TESTUSDT", "v", s2, c2, now=3)
        self.assertEqual([(r["t_close"] // self.M15, r["kind"]) for r in new2], [(10, "off")])
        self.assertEqual(strong15.current(conn, "TESTUSDT", "v"), {"t_close": 10 * self.M15, "dir": 0, "kind": "off", "close": 102.0})

    def test_first_record_marks_already_on_state_as_init(self):
        import strong15
        conn = self._mem()
        s, c = self._series([-1, -1, 0, 0])
        new = strong15.record(conn, "TESTUSDT", "v", s, c, now=1)
        self.assertEqual([(r["kind"], r["dir"], r["prev_dir"]) for r in new], [("init", -1, 0), ("off", 0, -1)])
        self.assertEqual(strong15.score_pending(conn, {"scoring": {}}, now=10 ** 13), 0)    # init 은 채점하지 않음
        self.assertEqual(strong15.summary(conn, "v"), [])
        s0, c0 = self._series([0, 0, 0])
        self.assertEqual(strong15.record(self._mem(), "TESTUSDT", "v", s0, c0, now=1), [])  # 꺼진 채 시작이면 행 없음

    def _episodes(self, conn):
        """BTC: 켜짐(100) → 꺼짐(110) → 반대(99) → 꺼짐(101). 15분봉 종가로 보조 채점용 봉도 넣는다."""
        H4 = db.PERIOD_MS["4h"]
        t0 = 1_700_006_400_000
        conn.executescript("""CREATE TABLE candles (source TEXT, symbol TEXT, period TEXT, ts INTEGER, open REAL, high REAL,
            low REAL, close REAL, volume REAL, quote_volume REAL, collected_at INTEGER, PRIMARY KEY (source, symbol, period, ts));""")
        rows = [(t0, 0, 1, "on", 100.0), (t0 + 4 * self.M15, 1, 0, "off", 110.0), (t0 + 8 * self.M15, 0, -1, "on", 99.0),
                (t0 + 12 * self.M15, -1, 0, "off", 101.0)]
        conn.executemany("INSERT INTO strong15 (symbol, t_close, rules_version, dir, prev_dir, kind, close, created_at) "
                         "VALUES ('BTCUSDT', ?, 'v', ?, ?, ?, ?, 0)", [(t, d, pv, k, c) for t, pv, d, k, c in rows])
        for t, close in ((t0 + H4, 90.0), (t0 + 8 * self.M15 + H4, 95.0)):      # 켜진 뒤 4시간 봉 종가
            conn.execute("INSERT INTO candles VALUES ('binance','BTCUSDT','15m',?,?,?,?,?,1,NULL,0)",
                         (t - self.M15, close, close + 1, close - 1, close))
        return t0, H4

    def test_scoring_any_change_and_aux(self):
        import strong15
        conn = self._mem()
        t0, H4 = self._episodes(conn)
        conf = {"scoring": {"episode_end": "any_change", "aux_horizon_ms": H4}}
        n = strong15.score_pending(conn, conf, now=t0 + 8 * self.M15 + H4)
        self.assertEqual(n, 4)                                   # (가) 2 + (나) 2
        r = conn.execute("SELECT end_reason, ret, hit, aux_close, aux_hit FROM strong15 WHERE kind='on' ORDER BY t_close").fetchall()
        self.assertEqual(r[0][0], "off"); self.assertAlmostEqual(r[0][1], 0.10); self.assertEqual(r[0][2], 1)   # Long, 100→110 적중
        self.assertEqual(r[0][3], 90.0); self.assertEqual(r[0][4], 0)                                              # 4시간 뒤 90 → 빗나감
        self.assertEqual(r[1][0], "off"); self.assertEqual(r[1][2], 0)                                             # Short, 99→101 빗나감
        self.assertEqual(r[1][3], 95.0); self.assertEqual(r[1][4], 1)                                              # 4시간 뒤 95 → 적중
        self.assertEqual(strong15.score_pending(conn, conf, now=t0 + 10 * H4), 0)                               # 다시 돌려도 그대로
        sm = strong15.summary(conn, "v")
        self.assertEqual((sm[0]["n"], sm[0]["called"], sm[0]["hit"], sm[0]["aux_called"], sm[0]["aux_hit"]), (2, 2, 1, 2, 1))
        self.assertEqual(sm[0]["hit_pct"], 50.0)

    def test_scoring_until_opposite_ignores_off(self):
        import strong15
        conn = self._mem()
        t0, H4 = self._episodes(conn)
        conf = {"scoring": {"episode_end": "opposite", "aux_horizon_ms": H4}}
        strong15.score_pending(conn, conf, now=t0 + 2 * self.M15)       # 보조 채점은 아직(4시간 안 지남)
        r = conn.execute("SELECT t_close, end_reason, end_close, hit, aux_t FROM strong15 WHERE kind='on' ORDER BY t_close").fetchall()
        self.assertEqual((r[0][1], r[0][2], r[0][3]), ("opposite", 99.0, 0))   # Long 100 → 반대 신호 때 99: 빗나감(사이 off 무시)
        self.assertIsNone(r[1][1])                                            # Short 는 아직 반대 신호 없음 → 미채점
        self.assertIsNone(r[0][4])

    def test_aux_waits_for_good_bar(self):
        import strong15
        conn = self._mem()
        t0, H4 = self._episodes(conn)
        conn.execute("UPDATE candles SET high=0 WHERE ts=?", (t0 + H4 - self.M15,))      # 깨진 봉 → 보류
        strong15.score_pending(conn, {"scoring": {"aux_horizon_ms": H4}}, now=t0 + 10 * H4)
        r = conn.execute("SELECT aux_t FROM strong15 WHERE kind='on' ORDER BY t_close").fetchall()
        self.assertIsNone(r[0][0]); self.assertIsNotNone(r[1][0])

    def test_run_on_synthetic_db_is_idempotent_and_matches_states(self):
        import strong15
        rules = dict(db.load_json("rules_v3.json"), symbols=["TESTUSDT"])
        v = db.rules_version(rules)
        conf = {"enabled": True, "lookback_days": 3, "scoring": {}}
        with tempfile.TemporaryDirectory() as d:
            conn = _engine_db(Path(d) / "t.db")
            now = conn.execute("SELECT MAX(ts) FROM candles WHERE period='15m'").fetchone()[0] + self.M15
            states, closes = strong15.state_series(conn, "TESTUSDT", rules, now, 3)
            self.assertEqual(len(states), 3 * 96 + 1)
            r1 = strong15.run(conn, rules, v, now, conf)
            n1 = conn.execute("SELECT COUNT(*) FROM strong15").fetchone()[0]
            r2 = strong15.run(conn, rules, v, now, conf)
            self.assertEqual(len(r1["new"]), n1); self.assertEqual(r2["new"], [])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM strong15").fetchone()[0], n1)
            cur = strong15.current(conn, "TESTUSDT", v)
            self.assertEqual(cur["dir"] if cur else 0, int(states.iloc[-1]))   # 마지막 행 = 지금 상태
            self.assertIsNotNone(db.kv_get(conn, "strong15_last_run"))
            # 15분봉이 하나 더 들어온 다음 실행: 상태가 그대로면 행이 늘지 않는다
            self.assertEqual(strong15.run(conn, rules, v, now + self.M15, conf)["new"], [])
            self.assertEqual(strong15.run(conn, rules, v, now, {"enabled": False})["enabled"], False)
            conn.close()

    def test_alerts15_off_by_default_and_once_per_row(self):
        conn = self._mem()
        conn.executescript("CREATE TABLE candles (source TEXT, symbol TEXT, period TEXT, ts INTEGER, open REAL, high REAL, "
                           "low REAL, close REAL, volume REAL, quote_volume REAL, collected_at INTEGER);")   # 시세 줄은 비어도 됨
        row = {"symbol": "BTCUSDT", "t_close": 10 * self.M15, "rules_version": "v", "dir": 1, "prev_dir": 0, "kind": "on", "close": 1.0}
        off = {"mode": "dry_run", "alerts": {"enabled": True}}
        self.assertEqual(notify.alerts15(conn, [row], off), [])
        self.assertFalse(db.load_json("discord.json")["alerts"].get("strong15"))    # 운영 설정 기본값 꺼짐(10-07)
        on = {"mode": "dry_run", "alerts": {"enabled": True, "strong15": True}}
        now = row["t_close"] + self.M15
        self.assertEqual(notify.alerts15(conn, [row, dict(row, kind="off", dir=0)], on, now=now), ["BTC:dry_run"])
        self.assertEqual(notify.alerts15(conn, [row], on, now=now), [])              # 같은 (시각, 종목)은 한 번
        # 지난 기록을 메워 넣은 행(30분 넘게 지난 봉)은 보내지 않는다(첫 실행 때 7일치 알림 폭주 방지)
        old_row = dict(row, t_close=row["t_close"] - 3 * self.M15)
        self.assertEqual(notify.alerts15(conn, [old_row], on, now=now), [])
        k, body = conn.execute("SELECT kind, body FROM discord_alerts").fetchone()
        self.assertEqual(k, "strong15"); self.assertIn("지금(15분 기준) 확실한 신호 Long", body)

    def test_alerts15_and_4h_alert_both_delivered_at_same_t(self):
        """4시간봉 마감 T 는 15분봉 마감이기도 하다. run_cycle 은 alerts15 를 4시간 alerts 보다 먼저 부르므로,
        PK 가 (t_close, 종목)뿐이면 15분 알림이 자리를 잡은 뒤 4시간 '확실한 신호' 알림이 조용히 빠진다(10-07 검토 지적)."""
        conn = self._mem()
        conn.executescript("CREATE TABLE candles (source TEXT, symbol TEXT, period TEXT, ts INTEGER, open REAL, high REAL, "
                           "low REAL, close REAL, volume REAL, quote_volume REAL, collected_at INTEGER);")
        T = 16 * self.M15                                                             # 4시간봉 마감 = 15분봉 마감
        row = {"symbol": "BTCUSDT", "t_close": T, "rules_version": "v", "dir": 1, "prev_dir": 0, "kind": "on", "close": 1.0}
        on = {"mode": "dry_run", "alerts": {"enabled": True, "strong15": True}}
        self.assertEqual(notify.alerts15(conn, [row], on, now=T + self.M15), ["BTC:dry_run"])
        self.assertEqual(notify._deliver(conn, on, T, "BTCUSDT", "v", "strong", "4시간 확실한 신호"), "dry_run")   # 빠지지 않는다
        self.assertIsNone(notify._deliver(conn, on, T, "BTCUSDT", "v", "strong", "다시"))                       # 같은 kind 는 한 번
        self.assertIsNone(notify.alerts15(conn, [row], on, now=T + self.M15) or None)
        rows = conn.execute("SELECT kind, status FROM discord_alerts WHERE t_close=? AND symbol='BTCUSDT' ORDER BY kind", (T,)).fetchall()
        self.assertEqual(rows, [("strong", "dry_run"), ("strong15", "dry_run")])

    def test_migrate_discord_alerts_pk_adds_kind(self):
        """운영 DB 의 옛 discord_alerts(PK t_close·symbol)는 connect 때 kind 포함 PK 로 옮겨지고 기존 행은 남는다."""
        conn = sqlite3.connect(":memory:")
        conn.executescript("""CREATE TABLE discord_alerts (t_close INTEGER NOT NULL, symbol TEXT NOT NULL, rules_version TEXT NOT NULL,
            kind TEXT NOT NULL, status TEXT NOT NULL, body TEXT, note TEXT, created_at INTEGER NOT NULL, PRIMARY KEY (t_close, symbol));
            INSERT INTO discord_alerts VALUES (1, 'BTCUSDT', 'v', 'strong', 'test_sent', 'b', NULL, 1);""")
        conn.executescript(db.SCHEMA); db._migrate(conn); db._migrate(conn)          # 두 번 불러도 멱등
        pk = [r[1] for r in conn.execute("PRAGMA table_info(discord_alerts)") if r[5]]
        self.assertEqual(sorted(pk), ["kind", "symbol", "t_close"])
        self.assertEqual(conn.execute("SELECT t_close, symbol, kind, status FROM discord_alerts").fetchall(), [(1, "BTCUSDT", "strong", "test_sent")])
        self.assertFalse(conn.execute("SELECT name FROM sqlite_master WHERE name='discord_alerts_pk2'").fetchone())
        conn.execute("INSERT INTO discord_alerts VALUES (1, 'BTCUSDT', 'v', 'strong15', 'dry_run', 'b', NULL, 1)")   # 같은 (T, 종목) 다른 kind

    def test_board_and_deploy_signature_follow_strong15(self):
        import re
        import strong15
        root = Path(__file__).resolve().parents[2]
        board_src = (root / "03_백엔드" / "app" / "board.py").read_text(encoding="utf-8")
        m = re.search(r"^LABEL15 = (\{.*\})", board_src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(eval(m.group(1)), strong15.LABEL)                           # 화면 글자가 엔진과 같음
        self.assertEqual(notify.LABEL15, strong15.LABEL)
        deploy = (root / "03_백엔드" / "scripts" / "deploy_vercel.sh").read_text(encoding="utf-8")
        self.assertIn('s.get("now15"', deploy)                                       # 15분 상태가 바뀌면 배포
        rules = db.load_json("rules_v3.json")
        self.assertNotIn("strong15", json.dumps(rules))                              # 15분 설정은 규칙 해시 밖(strong15.json)
