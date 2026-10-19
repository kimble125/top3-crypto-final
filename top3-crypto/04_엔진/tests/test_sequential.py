"""E3 순차 진입 재현(sequential_entry.py) 시험. 실행: cd 04_엔진 && python3 -m unittest discover -s tests -v

운영 DB 를 쓰지 않는다(손으로 만든 시계열과 합성 캔들만).
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import db  # noqa: E402
import judge  # noqa: E402
import sequential_entry as se  # noqa: E402

P15, P1, P4 = se.P15, se.P1, se.P4


def keyed(trades):
    return [(x["dir"], x["t_in"], x["t_out"], round(x["gross"], 12), x["forced"]) for x in trades]


def synth(n15: int = 3000, seed: int = 0, drop15: tuple = ()):
    """15분봉 무작위 걸음과 그것을 묶은 1시간·4시간봉(완전한 봉만). index = 봉 마감(UTC ms)."""
    rng = np.random.default_rng(seed)
    t0 = se.ms("2021-01-01")
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n15)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n15))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n15))
    vol = rng.uniform(50, 150, n15)
    idx = t0 + P15 * np.arange(1, n15 + 1)
    c15 = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

    def agg(per):
        g = (idx - t0 - 1) // per
        df = c15.groupby(g).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                close=("close", "last"), volume=("volume", "sum"))
        df = df[c15.groupby(g).size() == per // P15]
        df.index = t0 + (df.index.values + 1) * per
        return df

    c1, c4 = agg(P1), agg(P4)
    if drop15:
        c15 = c15.drop(index=idx[list(drop15)])
    return c4, c1, c15


class TestAsof(unittest.TestCase):
    def test_only_closed_bars_and_stale(self):
        s = pd.Series([1, -1], index=[P4, 2 * P4])          # 4h 봉 마감 04:00 → +1, 08:00 → −1
        t = np.array([P4 - P15, 2 * P4 - P15, 2 * P4, 3 * P4 - P15, 3 * P4 + P15])
        # 03:45: 아직 닫힌 봉 없음 → 0 / 07:45: 08:00 봉은 미래 → 04:00 봉 값 +1 / 08:00: 그 시각 마감 봉 −1
        # 11:45: 08:00 봉이 최신 → −1 / 12:15: 12:00 봉이 빠짐(최신 봉이 오래됨) → 0
        self.assertEqual(se.asof(s, t, P4).tolist(), [0, 1, -1, -1, 0])


class TestEntry(unittest.TestCase):
    def setUp(self):
        self.U = np.array([0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0])
        self.Up = np.r_[0, self.U[:-1]]
        self.ev = np.array([0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0])
        self.t = P15 * np.arange(12)
        self.c = 100.0 + np.arange(12)

    def test_entry_requires_upper_condition(self):
        a = se.entry_dirs(self.ev, self.U, self.Up, "A")
        b = se.entry_dirs(self.ev, self.U, self.Up, "B")
        self.assertEqual(a[2], 0)          # U 가 갖춰지기 전 사건(2)은 진입 아님
        self.assertEqual(a[3], 1)          # A: U 가 갖춰진 봉의 사건(3)은 진입
        self.assertEqual(b[3], 0)          # B: 직전 봉 U 가 0 이라 진입 아님
        self.assertEqual(b[6], 1)          # B: 조건이 먼저 갖춰진 뒤의 사건(6)은 진입

    def test_same_direction_reentry_ignored_and_X2_exit(self):
        a = se.entry_dirs(self.ev, self.U, self.Up, "A")
        tr = se.simulate(self.t, self.c, a, np.ones(12), self.U, "X2")
        self.assertEqual(len(tr), 1)                       # 6의 같은 방향 사건은 무시
        self.assertEqual((tr[0]["t_in"], tr[0]["t_out"]), (self.t[3], self.t[9]))   # U 가 깨진 9에서 청산
        self.assertFalse(tr[0]["forced"])
        self.assertAlmostEqual(tr[0]["gross"], 109 / 103 - 1)
        b = se.entry_dirs(self.ev, self.U, self.Up, "B")
        tb = se.simulate(self.t, self.c, b, np.ones(12), self.U, "X2")
        self.assertEqual([(x["t_in"], x["t_out"]) for x in tb], [(self.t[6], self.t[9])])

    def test_X1_exit_on_macd(self):
        macd = np.array([1] * 8 + [-1] * 4)
        a = se.entry_dirs(self.ev, self.U, self.Up, "A")
        tr = se.simulate(self.t, self.c, a, macd, self.U, "X1")
        self.assertEqual([(x["t_in"], x["t_out"]) for x in tr], [(self.t[3], self.t[8])])

    def test_X3_stop_and_reverse_and_forced_end(self):
        U = np.array([0, 0, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1])
        ev = np.array([0, 0, 1, 0, 0, -1, 0, 0, 1, -1, 0, 0, 0, 0])
        t = P15 * np.arange(14)
        c = np.array([100, 100, 100, 101, 102, 103, 104, 105, 106, 110, 108, 107, 106, 99.0])
        e = se.entry_dirs(ev, U, np.r_[0, U[:-1]], "A")
        self.assertEqual(np.flatnonzero(e).tolist(), [2, 9])   # 5(U 반대)·8(U 반대) 사건은 진입 사건 아님
        tr = se.simulate(t, c, e, np.sign(U), U, "X3")
        self.assertEqual(keyed(tr), [(1, t[2], t[9], round(110 / 100 - 1, 12), False),
                                     (-1, t[9], t[13], round(-(99 / 110 - 1), 12), True)])
        # X2: U 가 반대가 된 7에서 청산, 9의 Short 진입은 끝까지 열려 마지막 종가로 닫힘
        tr2 = se.simulate(t, c, e, np.sign(U), U, "X2")
        self.assertEqual([(x["dir"], x["t_in"], x["t_out"], x["forced"]) for x in tr2],
                         [(1, t[2], t[7], False), (-1, t[9], t[13], True)])

    def test_fixed_hold_X4_X5_with_missing_bar(self):
        n = 120
        t = np.delete(P15 * np.arange(n), 19)               # 진입(3) + 4시간 = 19번 봉이 빠짐
        c = 100.0 + np.arange(len(t))
        U = np.where(np.arange(len(t)) < 10, 1, -1)
        ev = np.zeros(len(t), dtype=int)
        ev[3], ev[10] = 1, -1                                # 10의 반대 사건은 보유 중이라 무시
        e = se.entry_dirs(ev, U, np.r_[0, U[:-1]], "A")
        tr4 = se.simulate(t, c, e, U, U, "X4")
        self.assertEqual([(x["t_in"], x["t_out"]) for x in tr4], [(P15 * 3, P15 * 20)])   # 빠진 봉 다음 봉
        tr5 = se.simulate(t, c, e, U, U, "X5")
        self.assertEqual([(x["t_in"], x["t_out"]) for x in tr5], [(P15 * 3, P15 * 99)])   # 3 + 96봉

    def test_no_entry_on_last_bar(self):
        ev = np.zeros(5, dtype=int)
        ev[-1] = 1
        U = np.ones(5, dtype=int)
        tr = se.simulate(P15 * np.arange(5), np.ones(5), se.entry_dirs(ev, U, U, "A"), U, U, "X1")
        self.assertEqual(tr, [])

    def test_board_trades(self):
        idx = P4 * np.arange(1, 9)
        bf = pd.DataFrame({"close": [100, 101, 102, 103, 104, 105, 106, 107.0],
                           "strong_dir": [0, 1, 1, 0, 1, -1, 0, 0],
                           "macd_dir": [1, 1, 1, 1, 1, -1, -1, -1]}, index=idx)
        c1 = se.board_trades(bf, "c1")
        self.assertEqual([(x["dir"], x["t_in"], x["t_out"], x["forced"]) for x in c1],
                         [(1, idx[1], idx[3], False), (1, idx[4], idx[5], False), (-1, idx[5], idx[6], False)])
        c2 = se.board_trades(bf, "c2")   # 꺼졌다 켜져도(3·4) MACD 가 그대로면 계속 보유, MACD 반전(5)에서 청산·반대 진입
        self.assertEqual([(x["dir"], x["t_in"], x["t_out"], x["forced"]) for x in c2],
                         [(1, idx[1], idx[5], False), (-1, idx[5], idx[7], True)])


class TestMetrics(unittest.TestCase):
    def test_hand_numbers(self):
        tr = [{"dir": 1, "t_in": 0, "t_out": 2 * se.HOUR, "gross": g, "forced": False} for g in (0.01, -0.02, 0.03)]
        m = se.metrics(tr)
        self.assertEqual(m["n"], 3)
        self.assertAlmostEqual(m["win"], 2 / 3)
        self.assertAlmostEqual(m["avg_win"], 0.02)
        self.assertAlmostEqual(m["avg_loss"], -0.02)
        self.assertAlmostEqual(m["payoff"], 1.0)
        self.assertAlmostEqual(m["exp"], 0.02 / 3)
        self.assertAlmostEqual(m["exp_net"], 0.02 / 3 - 0.002)
        self.assertAlmostEqual(m["cum_net"], 1.008 * 0.978 * 1.028 - 1)
        self.assertAlmostEqual(m["mdd"], 1 - 0.978)
        self.assertAlmostEqual(m["hold_h"], 2.0)

    def test_random_baseline_deterministic(self):
        t = P15 * np.arange(2000)
        c = 100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.003, 2000)))
        tr = [{"dir": d, "t_in": t[i], "t_out": t[i + 16], "gross": d * (c[i + 16] / c[i] - 1), "forced": False}
              for d, i in ((1, 100), (-1, 500), (1, 900))]
        a = se.random_baseline(tr, t, c, np.random.default_rng(se.SEED), 50)
        b = se.random_baseline(tr, t, c, np.random.default_rng(se.SEED), 50)
        self.assertEqual(a, b)
        self.assertTrue(0 <= a["pct"] <= 100)


class TestAgainstEngine(unittest.TestCase):
    def test_vpci_events_match_judge(self):
        """vpci_events 의 사건을 judge._hold_events 로 유지하면 judge.vpci_frame 의 방향·교차 시각과 같다
        (봉 누락, 같은 봉의 반대 사건 포함)."""
        import indicators as ind
        # 305·332 를 빼면 그 다음 봉에서 (누락을 무시할 경우) 교차가 난다 → 누락 처리를 실제로 시험함
        _, _, c15 = synth(20000, seed=1, drop15=(305, 332, 400, 401, 900))
        brk = judge.bar_breaks(c15.index, P15).values
        rules = db.load_json("rules_v3.json")
        for target in ("zero_or_signal",):
            for sig in ("sma", "vwma"):
                p = dict(rules["vpci"], cross_target=target, signal_ma=sig)
                if sig == "sma":   # 이 데이터에 같은 봉 반대 사건(0선 위로 + 신호선 아래로 등)이 실제로 있어야 시험이 뜻이 있음
                    v = ind.vpci(c15["close"], c15["volume"], p["short"], p["long"], p["signal"], sig)
                    vp, vs = v["vpci"], v["vpcis"]
                    v1, s1 = vp.shift(1), vs.shift(1)
                    up = ((v1 <= 0) & (vp > 0)) | ((v1 <= s1) & (vp > vs))
                    dn = ((v1 >= 0) & (vp < 0)) | ((v1 >= s1) & (vp < vs))
                    self.assertGreater(int((up & dn).sum()), 0)
                raw = se.vpci_events(c15, p, None)["event"]          # 누락을 모르는 경우
                self.assertGreater(int((raw[brk] != 0).sum()), 0)   # 누락 바로 뒤 봉에 교차가 있어야 뜻이 있음
                e = se.vpci_events(c15, p, P15)
                state, last = judge._hold_events(e["event"], e["hold_invalid"], e["brk"])
                vf = judge.vpci_frame(c15, p, P15)
                self.assertTrue((e["event"] != 0).sum() > 20)
                pd.testing.assert_series_equal(state, vf["vpci_dir"], check_names=False)
                pd.testing.assert_series_equal(last, vf["vpci_last_cross"], check_names=False, check_exact=True)
                # 봉 누락 바로 뒤 봉에서는 사건 없음
                after_gap = c15.index[judge.bar_breaks(c15.index, P15).values]
                self.assertTrue((e["event"].loc[after_gap] == 0).all())

    def test_no_future_bars(self):
        """T 이후 데이터를 지워도 T까지의 신호 시계열과 T까지 끝난 거래가 같다."""
        rules = db.load_json("rules_v3.json")
        c4, c1, c15 = synth(3000, seed=11)
        full = se.build_frame(c4, c1, c15, rules)
        self.assertTrue((full["U"] != 0).sum() > 100)
        lo = int(c15.index[700])
        hi = int(c15.index[-1])
        total = 0
        # 자르는 시점 여러 개: 4시간 경계(2207), 1시간 경계(2203), 경계 아님(1900·2001·2402·2650·2814)
        for k in (1900, 2001, 2203, 2207, 2402, 2650, 2814):
            T = int(c15.index[k])
            cut = lambda df: df[df.index <= T]  # noqa: E731
            part = se.build_frame(cut(c4), cut(c1), cut(c15), rules)
            pd.testing.assert_frame_equal(part, full[full.index <= T], check_exact=True)
            for v in se.VARIANTS:
                for x in se.EXITS:
                    tf = se.seq_trades(se.window(full, lo, hi), v, x)
                    tp = se.seq_trades(se.window(part, lo, T), v, x)
                    closed = [z for z in tp if not z["forced"]]
                    self.assertEqual(keyed(closed), keyed([z for z in tf if z["t_out"] <= T]), (k, v, x))
                    open_full = [(z["dir"], z["t_in"]) for z in tf if z["t_in"] < T < z["t_out"]]
                    self.assertEqual([(z["dir"], z["t_in"]) for z in tp if z["forced"]], open_full, (k, v, x))
                    total += len(closed)
        self.assertGreater(total, 100)

    def test_upper_condition_matches_engine_frames(self):
        """U(t) 는 그 시각에 닫힌 마지막 4h MACD 방향·1h 두 지표 방향이 같을 때만 그 방향(직접 계산과 대조)."""
        rules = db.load_json("rules_v3.json")
        c4, c1, c15 = synth(3000, seed=2)
        fr = se.build_frame(c4, c1, c15, rules)
        m = judge.macd_frame(c4, rules["macd"])["macd_dir"]
        pr = judge.pair_frame(c1, rules["stoch_pair"], P1)["pair_dir"]
        mi, pi = list(m.index), list(pr.index)
        import bisect
        flips = 0
        for t in fr.index[600:]:          # 모든 15분봉(표본 추출 없이)
            mm = int(m.iloc[bisect.bisect_right(mi, t) - 1])      # 마감 ≤ t 인 마지막 봉
            pp = int(pr.iloc[bisect.bisect_right(pi, t) - 1])
            want = mm if (mm == pp and mm != 0) else 0
            self.assertEqual(fr.at[t, "U"], want, t)
            self.assertEqual(fr.at[t, "macd"], mm, t)
            flips += int(t in m.index and m.index.get_loc(t) > 0 and m.loc[t] != m.iloc[m.index.get_loc(t) - 1])
        self.assertGreater(flips, 3)      # 그 사이 MACD 방향이 실제로 바뀐 봉이 있어야 미래 봉 사용을 가려낼 수 있음


if __name__ == "__main__":
    unittest.main()
