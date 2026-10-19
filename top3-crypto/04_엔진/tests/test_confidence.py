"""확신도(confidence.py) 시험. 신호 읽기 규칙은 v1(10-13) 그대로, 계산은 conf_v2(10-14 기획안 v5 1절 5)."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import confidence as cf  # noqa: E402


def make(**kw):
    """09:47 BTC 입력과 같은 모양의 기본값(모두 Short 쪽)."""
    inp = {
        "current_price": 81384.4, "ref_kst": "2026-10-13 09:45", "_ref_t": 1,
        "price_context": {"ema20_4h": 83108.7, "bb_mid_4h": 83059.1},
        "technical": {"macd_4h": {"macd": -152.16, "signal": -89.54, "histogram": -62.63, "histogram_recent": [148.7, 72.17, 29.54, -62.63]},
                      "stoch_1h": {"k": 8.21, "d": 18.19}, "stochrsi_1h": {"k": 16.91, "k_recent": [44.71, 36.73, 16.91]}},
        "open_interest": {"oi_change_pct": -1.18, "price_change_pct": -2.3},
        "coinbase_premium": {"value_pct": -0.131, "trend": "하락"},
        "fear_greed": {"now": 57, "now_class": "탐욕", "yesterday": 69},
    }
    for k, v in kw.items():
        inp[k] = v
    return inp


class ReadRules(unittest.TestCase):
    def test_price_both_sides(self):
        self.assertEqual(cf.read_price(make())[0], -1)
        up = make(current_price=84000)
        self.assertEqual(cf.read_price(up)[0], 1)
        mid = make(current_price=83080)      # EMA 아래, 중심선 위 → 엇갈림
        self.assertEqual(cf.read_price(mid)[0], 0)

    def test_macd_weakening_is_half(self):
        self.assertEqual(cf.read_macd(make())[0], -1.0)          # 음수 폭 커짐
        t = make()["technical"]
        t["macd_4h"] = {"macd": -11.81, "signal": -12.94, "histogram": 1.13, "histogram_recent": [9.83, 7.57, 1.13]}
        self.assertEqual(cf.read_macd(make(technical=t))[0], 0.5)  # 시그널 위지만 히스토그램 축소

    def test_stoch_oversold_half(self):
        self.assertEqual(cf.read_stoch(make())[0], -0.5)
        t = make()["technical"]
        t["stoch_1h"] = {"k": 40, "d": 50}
        self.assertEqual(cf.read_stoch(make(technical=t))[0], -1.0)
        t["stoch_1h"] = {"k": 85, "d": 70}
        self.assertEqual(cf.read_stoch(make(technical=t))[0], 0.5)

    def test_stochrsi_flat_and_extremes(self):
        self.assertEqual(cf.read_stochrsi(make())[0], -0.5)
        t = make()["technical"]
        t["stochrsi_1h"] = {"k": 100.0, "k_recent": [100.0, 100.0]}
        self.assertEqual(cf.read_stochrsi(make(technical=t))[0], 0)

    def test_oi_and_premium_and_fng(self):
        self.assertEqual(cf.read_oi(make())[0], -0.5)            # 가격↓ OI↓ = Long 청산
        self.assertEqual(cf.read_oi(make(open_interest={"oi_change_pct": 2.0, "price_change_pct": 1.0}))[0], 1.0)
        self.assertIsNone(cf.read_oi(make(open_interest={"oi_change_pct": None, "price_change_pct": None})))
        self.assertEqual(cf.read_premium(make())[0], -1.0)
        self.assertEqual(cf.read_premium(make(coinbase_premium={"value_pct": -0.12, "trend": "상승"}))[0], -0.5)
        self.assertEqual(cf.read_fng(make())[0], -1.0)
        self.assertEqual(cf.read_fng(make(fear_greed={"now": 80, "yesterday": 70}))[0], 0.5)
        self.assertEqual(cf.read_fng(make(fear_greed={"now": 57, "yesterday": 56}))[0], 0)


# 10-14 12:30 KST 실제 입력(시험 DB 에서 ai_analysis.build_input 으로 뽑아 확신도에 쓰는 칸만 남김). 기획안 v5 4절 5) 표와 같아야 한다
REAL = {
    "BTC": {"current_price": 83780.0, "ref_kst": "2026-10-14 12:30", "price_context": {"ema20_4h": 83235.5, "bb_mid_4h": 83267.1}, "technical": {"macd_4h": {"macd": -12.15, "signal": -42.13, "histogram": 29.97, "histogram_recent": [45.24, 51.41, 44.5, 29.97]}, "stoch_1h": {"k": 56.13, "d": 46.45}, "stochrsi_1h": {"k_recent": [36.59, 68.63]}}, "open_interest": {"oi_change_pct": 0.6, "price_change_pct": 1.61}, "coinbase_premium": {"value_pct": -0.081, "trend": "상승"}, "fear_greed": {"now": 62, "yesterday": 57}},
    "ETH": {"current_price": 2514.7, "ref_kst": "2026-10-14 12:30", "price_context": {"ema20_4h": 2516.4, "bb_mid_4h": 2517.7}, "technical": {"macd_4h": {"macd": -9.9, "signal": -10.67, "histogram": 0.7703, "histogram_recent": [1.42, 1.83, 1.58, 0.7703]}, "stoch_1h": {"k": 47.65, "d": 41.9}, "stochrsi_1h": {"k_recent": [37.81, 71.15]}}, "open_interest": {"oi_change_pct": 1.78, "price_change_pct": 2.08}, "coinbase_premium": {"value_pct": -0.085, "trend": "상승"}, "fear_greed": {"now": 62, "yesterday": 57}},
    "XRP": {"current_price": 1.3732, "ref_kst": "2026-10-14 12:30", "price_context": {"ema20_4h": 1.3833, "bb_mid_4h": 1.3873}, "technical": {"macd_4h": {"macd": -0.01371, "signal": -0.01321, "histogram": -0.0005018, "histogram_recent": [-0.002351, -0.00157, -0.0007723, -0.0005018]}, "stoch_1h": {"k": 65.01, "d": 64.16}, "stochrsi_1h": {"k_recent": [70.84, 88.11]}}, "open_interest": {"oi_change_pct": 0.81, "price_change_pct": 1.78}, "coinbase_premium": {"value_pct": -0.081, "trend": "상승"}, "fear_greed": {"now": 62, "yesterday": 57}},
}


def grouped(tech: dict | None = None, market: dict | None = None, news: dict | None = None) -> dict:
    """신호 값을 직접 정한 입력. tech·market 은 {key: x}(x 가 None 이면 자료 없음). 읽기 함수를 바꿔 끼우지 않고
    각 신호가 원하는 x 를 내는 입력값을 만든다."""
    t = {"price": 1, "macd": 1, "stoch": 1, "stochrsi": 1} if tech is None else tech
    m = {"oi": 1, "premium": 1, "fng": 1} if market is None else market
    inp = {"current_price": 100.0, "ref_kst": "2026-10-14 12:30", "_ref_t": 1, "technical": {}}
    px = {1: (110, 100, 100), -1: (90, 100, 100), 0: (100, 105, 95)}
    if t.get("price") is not None:
        p, e, mid = px[t["price"]]
        inp.update(current_price=p, price_context={"ema20_4h": e, "bb_mid_4h": mid})
    macd = {1: (2, 1, [1, 2]), 0.5: (2, 1, [3, 1]), -1: (1, 2, [-1, -2]), -0.5: (1, 2, [-3, -1]), 0: (1, 1, [0, 0])}
    if t.get("macd") is not None:
        a, b, h = macd[t["macd"]]
        inp["technical"]["macd_4h"] = {"macd": a, "signal": b, "histogram": h[-1], "histogram_recent": h}
    sto = {1: (50, 40), 0.5: (85, 70), -1: (40, 50), -0.5: (10, 18), 0: (50, 50)}
    if t.get("stoch") is not None:
        k, d = sto[t["stoch"]]
        inp["technical"]["stoch_1h"] = {"k": k, "d": d}
    srsi = {1: [30, 40], 0.5: [70, 90], -1: [40, 30], -0.5: [30, 10], 0: [50, 50]}
    if t.get("stochrsi") is not None:
        inp["technical"]["stochrsi_1h"] = {"k_recent": srsi[t["stochrsi"]]}
    oi = {1: (2, 1), 0.5: (-2, 1), -1: (2, -1), -0.5: (-2, -1), 0: (2, 0)}
    if m.get("oi") is not None:
        a, b = oi[m["oi"]]
        inp["open_interest"] = {"oi_change_pct": a, "price_change_pct": b}
    prem = {1: (0.1, "상승"), 0.5: (0.1, "하락"), -1: (-0.1, "하락"), -0.5: (-0.1, "상승"), 0: (0.0, "보합")}
    if m.get("premium") is not None:
        v, tr = prem[m["premium"]]
        inp["coinbase_premium"] = {"value_pct": v, "trend": tr}
    fng = {1: (60, 50), 0.5: (80, 70), -1: (50, 60), -0.5: (20, 30), 0: (50, 50)}
    if m.get("fng") is not None:
        a, b = fng[m["fng"]]
        inp["fear_greed"] = {"now": a, "yesterday": b}
    if news is not None:
        inp["_news"] = news
    return inp


class ScoreV2(unittest.TestCase):
    def test_real_examples_1014(self):                       # A: 기획안 v5 4절 5) 표
        want = {"BTC": (86.5, 50.0, 68, 77, "Long 우세"), "ETH": (25.0, 50.0, 38, 65, "약한 Long"),
                "XRP": (-11.5, 50.0, 19, 58, "약한 Long")}
        for coin, (t, q, d, p, lab) in want.items():
            r = cf.compute(copy.deepcopy(REAL[coin]))
            got = (r["groups"]["tech"]["score"], r["groups"]["market"]["score"], r["score"], r["p_long"], r["label"])
            self.assertEqual(got, (t, q, d, p, lab), coin)
            self.assertEqual((r["side"], r["side_pct"], r["note"]), ("Long", p, "뉴스 방향 없음"), coin)
        r = cf.compute(copy.deepcopy(REAL["BTC"]))
        self.assertEqual(r["formula"],
                         "기술 지표 (8×(+1) + 7×(+0.5) + 6×(+1) + 5×(+1)) ÷ 26 × 100 = +86.5 · "
                         "시장 자료 (8×(+1) + 7×(−0.5) + 6×(+1)) ÷ 21 × 100 = +50.0 · "
                         "D = (86.5 + 50.0) ÷ 2 = 68.25 → 68 · 확신도 = 50 + 0.4 × 68 = 77.2 → 77%")   # F
        self.assertEqual(r["coverage_pct"], cf._round(100 * 47 / 52))
        self.assertEqual(r["level"], "medium")
        # 지지 비중: 묶음마다 Long 쪽 무게 몫(기술 22.5/26, 시장 자료 14/21)을 반반
        self.assertEqual(r["support_pct"], cf._round(100 * (22.5 / 26 + 14 / 21) / 2))
        self.assertEqual([s["group"] for s in r["signals"]], ["tech"] * 4 + ["market"] * 4)
        self.assertEqual([s["w"] for s in r["signals"]], [8, 7, 6, 5, 8, 7, 6, 5])

    def test_market_short_falls_back_to_tech(self):          # B
        r = cf.compute(grouped(market={"fng": 1}, news={"x": 1, "n": 3, "created_kst": "10-14 09:04"}))   # 공포탐욕 6 + 뉴스 5 = 11/26
        self.assertEqual(r["groups"]["market"]["coverage_pct"], 42)
        self.assertFalse(r["groups"]["market"]["used"])
        self.assertEqual(r["note"], "시장 자료 부족: OI·코인베이스 프리미엄 없음 → 기술 지표만")
        self.assertEqual((r["score"], r["p_long"], r["label"]), (100, 90, "강한 Long"))
        self.assertIn("충족률 42%, 50% 미만이라 뺌", r["formula"])
        self.assertTrue(r["formula"].endswith("· D = 100.0 · 확신도 = 50 + 0.4 × 100 = 90%"))
        r = cf.compute(grouped(market={"fng": 1}))
        self.assertEqual(r["note"], "시장 자료 부족: OI·코인베이스 프리미엄·뉴스 방향 없음 → 기술 지표만")
        r = cf.compute(grouped(tech={"price": 1, "macd": 1, "stoch": 1}, market={"fng": 1}))      # 남은 묶음의 결측도 적음(Fable 지적 7)
        self.assertEqual(r["note"], "시장 자료 부족: OI·코인베이스 프리미엄·뉴스 방향 없음 → 기술 지표만 · StochRSI 없음")

    def test_tech_missing_and_both_missing(self):            # C
        r = cf.compute(grouped(tech={"stochrsi": 1}, market={"oi": -1, "premium": -1, "fng": -1}))   # 기술 5/26
        self.assertEqual(r["note"], "기술 지표 부족: 가격 위치·MACD·Stochastic 없음 → 시장 자료만 · 뉴스 방향 없음")
        self.assertEqual((r["score"], r["p_long"], r["side"], r["side_pct"], r["label"]), (-100, 10, "Short", 90, "강한 Short"))
        r = cf.compute(grouped(tech={"stochrsi": 1}, market={"fng": 1}))
        for k in ("p_long", "side", "side_pct", "level", "score", "support_pct"):
            self.assertIsNone(r[k], k)
        self.assertEqual(r["label"], "자료 부족")
        self.assertEqual(r["coverage_pct"], cf._round(100 * 11 / 52))
        self.assertIn("보류", r["formula"])
        self.assertIsNone(cf.compute(grouped(tech={}, market={})))   # 쓸 신호가 하나도 없음

    def test_levels_and_labels(self):                         # D
        for p, lv, lab in ((54, "neutral", "중립"), (55, "low", "약한 Long"), (65, "low", "약한 Long"), (66, "medium", "Long 우세"),
                           (77, "medium", "Long 우세"), (78, "high", "강한 Long"), (46, "neutral", "중립"), (45, "low", "약한 Short"),
                           (35, "low", "약한 Short"), (34, "medium", "Short 우세"), (23, "medium", "Short 우세"),
                           (22, "high", "강한 Short"), (50, "neutral", "중립"), (90, "high", "강한 Long"), (10, "high", "강한 Short")):
            self.assertEqual((cf.level_of(p), cf.label_of(p)), (lv, lab), p)
        self.assertEqual(cf.label_of(None), "자료 부족")

    def test_short_side_and_rounding(self):                  # F·G: p < 50, D_raw ±0.5
        r = cf.compute(grouped(tech={"price": -1, "macd": 1, "stoch": -0.5, "stochrsi": -0.5},    # −6.5/26 = −25.0
                               market={"oi": -1, "premium": -1, "fng": -1}, news={"x": 0, "n": 2}))   # −21/26 = −80.8
        self.assertEqual((r["groups"]["tech"]["score"], r["groups"]["market"]["score"]), (-25.0, -80.8))
        self.assertEqual(r["score"], -53)                                                         # −52.9 → −53
        self.assertEqual((r["p_long"], r["side"], r["side_pct"], r["label"]), (29, "Short", 71, "Short 우세"))   # 28.8 → 29
        self.assertIn("D = (−25.0 + (−80.8)) ÷ 2 = −52.9 → −53 · 확신도 = 50 + 0.4 × (−53) = 28.8 → 29%", r["formula"])
        r = cf.compute(grouped(tech={"price": -1, "macd": 1, "stoch": -0.5, "stochrsi": -0.5},    # −25.0
                               market={"oi": -1, "premium": -0.5, "fng": 0.5}))                   # −8.5/21 = −40.5
        self.assertEqual((r["groups"]["market"]["score"], r["score"]), (-40.5, -33))              # −32.75 → −33(0에서 먼 쪽)
        self.assertEqual(cf._round(-30.35), -30)
        self.assertEqual(cf._round(37.5), 38)
        self.assertEqual(cf._round(-37.5), -38)
        self.assertEqual(cf._round1(86.538), 86.5)
        self.assertEqual(cf._round1(-0.05), -0.1)
        self.assertEqual(cf._round1(0.25), 0.3)

    def test_exact_half_rounding(self):                       # Fable 검토 10-14 지적 1: 부동소수점 꼬리로 −17.5 → −17 이 되던 것
        r = cf.compute(grouped(tech={"price": -1, "macd": 0, "stoch": -1, "stochrsi": -1},       # −19/26 → −73.1
                               market={"oi": 0.5, "premium": 1, "fng": -0.5}))                  # 8/21 → +38.1
        self.assertEqual((r["groups"]["tech"]["score"], r["groups"]["market"]["score"]), (-73.1, 38.1))
        self.assertEqual(r["score"], -18)                                                        # (−73.1 + 38.1) ÷ 2 = −17.5 → −18
        self.assertIn("D = (−73.1 + 38.1) ÷ 2 = −17.5 → −18", r["formula"])
        self.assertEqual(cf.combine({"tech": -986, "market": 496}, cf.GROUP_SHARE)[1], -25)    # 검토 예: −24.5 → −25
        d_raw, d, p_raw, p = cf.combine({"tech": 865, "market": 500}, cf.GROUP_SHARE)                # 기획안 예시: 68.25 → 68 → 77.2 → 77
        self.assertEqual((float(d_raw), d, float(p_raw), p), (68.25, 68, 77.2, 77))

    def test_group_boundary_and_neutral(self):                # G
        r = cf.compute(grouped(market={"premium": 1, "fng": 1}))                                   # 7 + 6 = 13/26 = 50% → 남음
        self.assertEqual((r["groups"]["market"]["coverage_pct"], r["groups"]["market"]["used"]), (50, True))
        self.assertEqual(r["note"], "OI·뉴스 방향 없음")
        r = cf.compute(grouped(tech={"price": 0, "macd": 0, "stoch": 0, "stochrsi": 0}, market={"oi": 0, "premium": 0, "fng": 0}))
        self.assertEqual((r["p_long"], r["side"], r["side_pct"], r["level"], r["label"]), (50, "Long", 50, "neutral", "중립"))
        self.assertIsNone(r["support_pct"])

    def test_zero_share_group_is_dropped(self):               # G: 남은 묶음 몫 0(미래 0:100 설정)
        r = cf.compute(grouped(tech={"price": 1, "macd": 1, "stoch": 1, "stochrsi": 1}, market={"oi": -1, "premium": -1, "fng": -1}),
                       share={"tech": 0, "market": 1})
        self.assertFalse(r["groups"]["tech"]["used"])
        self.assertEqual((r["score"], r["p_long"]), (-100, 10))
        self.assertEqual(r["note"], "시장 자료만으로 계산(설정) · 뉴스 방향 없음")
        r = cf.compute(grouped(tech={"price": 1, "macd": 1, "stoch": 1, "stochrsi": 1}, market={"oi": -1, "premium": -1, "fng": -1}),
                       share={"tech": 0.3, "market": 0.7})
        self.assertEqual(r["score"], cf._round(0.3 * 100 + 0.7 * -100))
        self.assertIn("D = 0.3 × 100.0 + 0.7 × (−100.0) = −40", r["formula"])

    def test_news_reading(self):                              # H·E(읽기)
        self.assertIsNone(cf.read_news({}))
        self.assertIsNone(cf.read_news({"_news": {"x": 1, "n": 0}}))                              # 관련 기사 없음 = 자료 없음
        self.assertIsNone(cf.read_news({"_news": {"x": None, "n": 0}}))
        x, val, _ = cf.read_news({"_news": {"x": -1, "n": 4, "created_kst": "10-14 21:03"}})
        self.assertEqual((x, val), (-1.0, "부정 −1 · 기사 4건 · 10-14 21:03 분석"))
        r = cf.compute(grouped(news={"x": 1, "n": 0}))
        self.assertEqual(r["groups"]["market"]["coverage_pct"], cf._round(100 * 21 / 26))          # 뉴스 무게가 빠짐
        r = cf.compute(grouped(news={"x": -1, "n": 5}))
        self.assertEqual(r["groups"]["market"]["score"], cf._round1(100 * (21 - 5) / 26))
        self.assertIsNone(r["note"])


class Edges(unittest.TestCase):
    """GPT 검토(10-13) C2–C6: 결측·범위·경계(신호 읽기는 v1 그대로)."""

    def tech(self, **kw):
        t = make()["technical"]
        t.update(kw)
        return make(technical=t)

    def test_stochrsi_needs_last_two(self):               # C2: 결측을 건너뛰어 옛 값과 비교하지 않음
        self.assertIsNone(cf.read_stochrsi(self.tech(stochrsi_1h={"k_recent": [30, 40, None]})))
        self.assertIsNone(cf.read_stochrsi(self.tech(stochrsi_1h={"k_recent": [30, None, 40]})))
        self.assertEqual(cf.read_stochrsi(self.tech(stochrsi_1h={"k_recent": [None, 30, 40]}))[0], 1.0)

    def test_nan_inf_and_range(self):                     # C3·C5
        nan, inf = float("nan"), float("inf")
        self.assertIsNone(cf.read_stochrsi(self.tech(stochrsi_1h={"k_recent": [40, nan]})))
        self.assertIsNone(cf.read_price(make(current_price=0)))
        self.assertIsNone(cf.read_price(make(current_price=-1)))
        self.assertIsNone(cf.read_price(make(current_price=inf)))
        self.assertIsNone(cf.read_stoch(self.tech(stoch_1h={"k": -5, "d": -10})))
        self.assertIsNone(cf.read_fng(make(fear_greed={"now": 120, "yesterday": 50})))
        self.assertEqual(cf.read_premium(make(coinbase_premium={"value_pct": -0.2, "trend": "하락"}))[0], -1.0)  # 음수는 정상값

    def test_oi_flat_is_not_liquidation(self):            # C4
        x, _, note = cf.read_oi(make(open_interest={"oi_change_pct": 0.0, "price_change_pct": 2.0}))
        self.assertEqual(x, 0.5)
        self.assertNotIn("청산", note)

    def test_macd_notes(self):                            # C6
        _, _, note = cf.read_macd(self.tech(macd_4h={"macd": 2, "signal": 1, "histogram": 1, "histogram_recent": [1, 1]}))
        self.assertIn("보합", note)
        x, _, note = cf.read_macd(self.tech(macd_4h={"macd": 2, "signal": 1, "histogram": 1}))
        self.assertEqual(x, 1.0)
        self.assertNotIn("확대", note)
        x, _, _ = cf.read_macd(self.tech(macd_4h={"macd": 2, "signal": 1, "histogram": 1, "histogram_recent": [-3, 1]}))
        self.assertEqual(x, 1.0)                          # 0을 막 넘은 교차는 약화가 아님

    def test_boundaries(self):                            # C7: 경계 포함 여부
        self.assertEqual(cf.read_stochrsi(self.tech(stochrsi_1h={"k_recent": [40, 41]}))[0], 0)     # 1 이하 보합
        self.assertEqual(cf.read_oi(make(open_interest={"oi_change_pct": 2, "price_change_pct": 0.1}))[0], 0)
        self.assertEqual(cf.read_fng(make(fear_greed={"now": 52, "yesterday": 50}))[0], 0)          # 2 이하 보합
        self.assertEqual(cf.read_fng(make(fear_greed={"now": 53, "yesterday": 50}))[0], 1.0)

    def test_btc_0947_v2(self):                           # 10-13 09:47 입력(모두 Short 쪽)
        r = cf.compute(make())
        # 기술 (8·−1 + 7·−1 + 6·−0.5 + 5·−0.5) ÷ 26 = −78.8, 시장 자료 (8·−0.5 + 7·−1 + 6·−1) ÷ 21 = −81.0
        self.assertEqual((r["groups"]["tech"]["score"], r["groups"]["market"]["score"]), (-78.8, -81.0))
        self.assertEqual((r["score"], r["p_long"], r["side"], r["side_pct"], r["label"]), (-80, 18, "Short", 82, "강한 Short"))


class Board(unittest.TestCase):
    def _fake_ai(self, build_input, latest=None):
        import types
        fake = types.ModuleType("ai_analysis")
        fake.build_input = build_input
        fake.latest = latest or (lambda conn, s, since=None, until=None: None)
        return fake

    def _with(self, fake, fn):
        saved = sys.modules.get("ai_analysis")
        sys.modules["ai_analysis"] = fake
        try:
            return fn()
        finally:
            if saved is not None:
                sys.modules["ai_analysis"] = saved
            else:
                del sys.modules["ai_analysis"]

    def test_board_records_errors(self):
        def build_input(conn, s, now):
            if s == "BAD":
                raise RuntimeError("x")
            return None if s == "EMPTY" else make()
        out = self._with(self._fake_ai(build_input), lambda: cf.board(None, ["GOOD", "BAD", "EMPTY"], 0))
        self.assertEqual(out["GOOD"]["p_long"], 18)
        self.assertEqual([s["note"] for s in out["GOOD"]["signals"] if s["key"] == "news"], ["AI 분석 없음(점수 제외)"])
        self.assertIsNone(out["BAD"])
        self.assertEqual(out["_errors"], {"BAD": "계산 실패(RuntimeError)", "EMPTY": "자료 없음"})

    def test_board_news_from_latest_analysis(self):          # E: 12시간 안 성공한 분석의 news_bias 만
        import sqlite3
        import ai_analysis
        import db
        conn = sqlite3.connect(":memory:")
        conn.executescript(db.SCHEMA)
        H = 3_600_000
        now = 1_800_000_000_000

        def put(created, source, nb):
            body = None if source == "none" else json.dumps({"trend_direction": "Long", "news_bias": nb})
            conn.execute("INSERT INTO ai_analyses (symbol, created_at, kind, ref_t, source, model, trend_dir, body_json) "
                         "VALUES ('BTCUSDT',?,?,?,?,?,?,?)", (created, "scheduled", created, source, "m", 1 if body else None, body))
        put(now - 11 * H, "claude", {"x": -1, "score": -0.5, "n": 4})
        put(now - 1 * H, "none", None)                                                                  # 실패는 무시
        news = lambda: self._with(self._fake_ai(lambda c, s, n: make(), ai_analysis.latest), lambda: cf.board(conn, ["BTCUSDT"], now))  # noqa: E731
        sig = lambda out: [s for s in out["BTCUSDT"]["signals"] if s["key"] == "news"][0]  # noqa: E731
        got = sig(news())
        self.assertEqual((got["used"], got["x"]), (True, -1.0))
        self.assertIn("기사 4건", got["value"])
        put(now - 30 * 60_000, "gpt", {"x": 1, "score": 0.4, "n": 0})                                 # 가장 최근 분석의 n = 0
        got = sig(news())
        self.assertEqual((got["used"], got["note"]), (False, "관련 기사 없음(점수 제외)"))
        conn.execute("DELETE FROM ai_analyses WHERE created_at >= ?", (now - 2 * H,))
        conn.execute("UPDATE ai_analyses SET created_at=? WHERE source='claude'", (now - 13 * H,))       # 12시간 넘음
        got = sig(news())
        self.assertEqual((got["used"], got["note"]), (False, "12시간 안 AI 분석 없음(점수 제외)"))
        put(now - 2 * H, "gpt", {"x": 1, "score": 0.4})                                               # n 없음(V5 전 꼴) → 자료 없음
        self.assertFalse(sig(news())["used"])
        conn.execute("DELETE FROM ai_analyses")
        put(now - 2 * H, "gpt", None)
        conn.execute("UPDATE ai_analyses SET body_json=? WHERE source='gpt'", (json.dumps({"trend_direction": "Long"}),))
        self.assertEqual(sig(news())["note"], "기사 표지 없음(V5 전 분석)(점수 제외)")
        conn.close()


if __name__ == "__main__":
    unittest.main()
