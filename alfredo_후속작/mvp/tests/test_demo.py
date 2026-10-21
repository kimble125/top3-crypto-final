"""데모 시험 (2026-10-13): 공개 범위 화이트리스트 · 개인 값 0건 · 바깥 호출 0건 · 고지 · 경계값.

실행(저장소 루트에서): python3 -I -m unittest discover -s mvp/tests -v
dist 시험은 `python3 -I mvp/build_demo.py`로 만든 첨부 파일을 읽는다(먼저 빌드).
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import sys
import unittest

MVP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(MVP)
sys.path.insert(0, MVP)
sys.path.insert(0, ROOT)

import build_demo as B  # noqa: E402  (불러오는 순간 개인 경로·바깥 호출 지킴이가 켜진다)
from alfredo.principles import judge_trades, load_rules  # noqa: E402

DIST = os.path.join(MVP, "dist", "alfredo_mvp_demo.html")


def _strip_volatile(d: dict) -> dict:
    d = json.loads(json.dumps(d))
    d["meta"].pop("built_at", None)
    return d


def _dist_text() -> str:
    with open(DIST, encoding="utf-8") as f:
        return f.read()


def _dist_payload(html: str) -> dict:
    m = re.search(r"window\.ALFREDO_DEMO = (\{.*?\});\n</script>", html, re.S)
    if not m:
        raise AssertionError("첨부 파일에서 데이터를 찾지 못했다")
    return json.loads(m.group(1).replace("<\\/", "</"))


class PublicScope(unittest.TestCase):
    """2-6 공개 응답 화이트리스트: 적지 않은 키는 나가지 않고, 나오면 빌드가 멈춘다."""

    def test_unknown_key_stops(self):
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"meta": {"title": "x", "account_no": "1"}})
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"balances": {}})

    def test_map_keys_are_limited(self):
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"meta": {"template": {"주식": 0.4, "부동산": 0.6}}})

    def test_bad_values_stop(self):
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"portfolio": {"return": float("nan")}})
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"meta": {"scenario": "/Users/x/01_Projects/Alfredo_private/docs"}})
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"portfolio": {"costs": {"fees": object()}}})

    def test_build_output_passes_and_is_deterministic(self):
        a, b = B.build(), B.build()
        self.assertEqual(B.public_view(a), a)
        self.assertEqual(_strip_volatile(a), _strip_volatile(b), "같은 시드면 같은 결과여야 한다")


class NoPersonalData(unittest.TestCase):
    """2-6 '개인 값 0건': 빌드가 개인 경로를 열지 않고, 첨부 파일에 개인 표식·실제 금액이 없다."""

    def test_guard_blocks_personal_paths_and_network(self):
        for p in ("data/alfredo/personal/x.json", "/Users/x/01_Projects/Alfredo_private/.env",
                  "alfredo_link/state.json", "/Users/x/02_HQ/05_no-vault/a.txt"):
            with self.assertRaises(B.GuardError, msg=p):
                open(os.path.join(ROOT, p))
        with self.assertRaises(B.GuardError):
            socket.create_connection(("127.0.0.1", 9), timeout=1)

    def test_build_opens_only_allowed_files(self):
        B.OPENED.clear()
        B.build()
        bad = [p for p in B.OPENED if any(m in p for m in B.PERSONAL_MARKERS)]
        self.assertEqual(bad, [])

    def test_dist_values_come_from_synthetic_build(self):
        """첨부 안의 숫자는 모두 시드 고정 합성 빌드에서 나온 것(새로 빌드한 값과 같다)."""
        self.assertEqual(_strip_volatile(_dist_payload(_dist_text())), _strip_volatile(B.build()))

    def test_dist_has_no_personal_markers(self):
        html = re.sub(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+", "data:", _dist_text())
        markers = ["alfredo_private", "data/alfredo/personal", "alfredo_link", "banksalad", "뱅크샐러드",
                   "토스증권", "tossinvest", "upbit", "업비트", "05_no-vault", "/users/"]
        low = html.lower()
        self.assertEqual([m for m in markers if m in low], [])
        accounts = [x for x in re.findall(r"\b\d{3,6}-\d{2,6}-\d{2,8}\b", html) if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)]
        self.assertEqual(accounts, [], "계좌번호 꼴")
        self.assertEqual(re.findall(r"\b01[016789]-?\d{3,4}-?\d{4}\b", html), [], "전화번호 꼴")
        self.assertEqual(re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", html), [], "전자우편 꼴")
        no_urls = re.sub(r"https?://[^\s\"'<>)\\]+", "", html)  # 링크 주소는 따로 시험(test_only_listed_links)
        self.assertEqual(re.findall(r"\b[A-Za-z0-9_\-]{32,}\b", no_urls), [], "키·토큰 꼴")


class NoExternalCalls(unittest.TestCase):
    """12장 6번 '바깥 호출 0건': 자동으로 나가는 요청 코드가 없고, 바깥 주소는 누를 때만 열리는 링크뿐."""

    def test_no_request_code(self):
        html = _dist_text()
        for pat in (r"""(?:src|href)\s*=\s*["']https?://""", r"@import", r"url\(\s*['\"]?https?://", r"\bfetch\(",
                    r"XMLHttpRequest", r"sendBeacon", r"new WebSocket", r"<link\b", r"<iframe\b", r"<img\b"):
            self.assertIsNone(re.search(pat, html), pat)

    def test_only_listed_links(self):
        html = _dist_text()
        meta = _dist_payload(html)["meta"]
        allowed = {meta["top3_url"]} | {b["url"] for b in meta["template_basis"]}
        found = set(re.findall(r"https?://[^\s\"'<>)\\]+", html))
        self.assertTrue(found <= allowed, found - allowed)


class Notice(unittest.TestCase):
    """AI 고지·투자 권유 아님·모의(위치는 D-1013-4 답 전: 머리 띠 그대로)."""

    def test_band(self):
        html = _dist_text()
        band = re.search(r'<div class="band" id="band"[^>]*>(.*?)</div>', html).group(1)
        for w in ("AI", "투자 권유가 아닙니다", "모의투자"):
            self.assertIn(w, band)
        self.assertEqual(_dist_payload(html)["meta"]["band"], band)

    def test_synthetic_is_stated(self):
        meta = B.build()["meta"]
        self.assertIn("합성", meta["scenario"])
        self.assertIn("실제 시세가 아닙니다", meta["price_note"])


class Boundaries(unittest.TestCase):
    """2-2 경계 처리: 이하/미만을 문서와 시험에 고정, 부동소수 오차로 판정이 바뀌지 않게."""

    def test_grade(self):
        self.assertEqual(B.grade(0.01), "기준 근처")
        self.assertEqual(B.grade(-0.01), "기준 근처")
        self.assertEqual(B.grade(0.01 + 1e-12), "기준 근처")
        self.assertEqual(B.grade(0.3 - 0.29), "기준 근처")       # 0.010000000000000009
        self.assertEqual(B.grade(0.010001), "기준 이상")
        self.assertEqual(B.grade(-0.010001), "기준 미만")
        self.assertIsNone(B.grade(None))
        self.assertIsNone(B.grade(float("nan")))
        self.assertIsNone(B.grade(float("inf")))

    def test_rebalance_band_inclusive(self):
        self.assertTrue(B.within_band(0.05))
        self.assertTrue(B.within_band(-0.05))
        self.assertTrue(B.within_band(0.35 - 0.3))                # 0.04999999999999999
        self.assertFalse(B.within_band(0.050001))

    def test_range_inclusive(self):
        self.assertTrue(B.inside_range(-0.1, -0.1, 0.2))
        self.assertTrue(B.inside_range(0.2, -0.1, 0.2))
        self.assertFalse(B.inside_range(0.200001, -0.1, 0.2))

    def test_quantile(self):
        self.assertEqual(B.quantile([3.0, 1.0, 2.0], 0.5), 2.0)
        with self.assertRaises(ValueError):
            B.quantile([], 0.5)

    def test_engine_rule_boundaries(self):
        """엔진 v0 규칙의 경계(엔진은 고치지 않고 지금 뜻을 고정): 비중 '이하', 추가 매수 '이상 쌀 때', 손절 '이하면 금지'."""
        rules = load_rules()

        def judge(second_price):
            t = [{"id": 1, "side": "deposit", "symbol": "KRW", "qty": 1000, "price": 1, "cash_delta": 1000.0},
                 {"id": 2, "side": "buy", "symbol": "A", "qty": 1, "price": 100, "cash_delta": -100.0},
                 {"id": 3, "side": "buy", "symbol": "A", "qty": 1, "price": second_price, "cash_delta": -float(second_price)}]
            return {j.rule_id: j.ok for j in judge_trades(t, rules) if j.trade_id == 3}

        self.assertTrue(judge(95)["add_buy"])        # 정확히 −5%: 조건 충족(이상)
        self.assertFalse(judge(95.01)["add_buy"])    # −4.99%: 어김
        self.assertFalse(judge(85)["stop_loss"])     # 정확히 −15%: 손절선 이하라 추가 매수 금지
        self.assertTrue(judge(85.01)["stop_loss"])   # −14.99%: 손절선 위

        def weight(qty_ratio):
            t = [{"id": 1, "side": "deposit", "symbol": "KRW", "qty": 1000, "price": 1, "cash_delta": 1000.0},
                 {"id": 2, "side": "buy", "symbol": "A", "qty": qty_ratio * 10, "price": 100, "cash_delta": -qty_ratio * 1000}]
            return [j.ok for j in judge_trades(t, rules) if j.rule_id == "max_weight"][0]

        self.assertTrue(weight(0.4))                 # 정확히 40%: 지킴(이하)
        self.assertFalse(weight(0.4001))

    def test_no_missing_dates_are_skipped(self):
        px = B.synth_prices()
        for s in px:
            for d in B.dates_between(B.START, B.END):
                self.assertIn(d, px[s])
                self.assertTrue(math.isfinite(px[s][d]["close"]) and px[s][d]["close"] > 0)


if __name__ == "__main__":
    unittest.main()


class Board(unittest.TestCase):
    """V2 대시보드(코인·주식·기타): 공개 범위·바깥 호출·고지·확신도 계산."""

    @classmethod
    def setUpClass(cls):
        import build_board as BB
        cls.BB = BB
        with open(os.path.join(MVP, "dist", "alfredo_mvp_board.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_public_scope(self):
        b = self.BB.build()
        self.assertEqual(B.public_view(b, self.BB.BOARD_SCHEMA), b)
        with self.assertRaises(B.PublicScopeError):
            B.public_view({"tabs": {"crypto_wallet": {}}}, self.BB.BOARD_SCHEMA)

    def test_no_request_code_and_links(self):
        for pat in (r"""(?:src|href)\s*=\s*["']https?://""", r"@import", r"url\(\s*['\"]?https?://",
                    r"XMLHttpRequest", r"sendBeacon", r"new WebSocket", r"<link\b", r"<iframe\b", r"<img\b"):
            self.assertIsNone(re.search(pat, self.html), pat)  # 로고도 그림 파일이 아니라 직접 그린 SVG(Top3 로고 뺌, 10-19)
        self.assertIn('id="alf-logo-g"', self.html)
        # 요청 코드는 채팅 한 곳뿐: 같은 로컬 서버의 상대 주소, 파일로 연 화면에서는 부르지 않음
        self.assertEqual(re.findall(r"\bfetch\(([^,)]*)", self.html), ['"api/chat"'])
        self.assertIn('location.protocol === "file:"', self.html)
        found = set(re.findall(r"https?://[^\s\"'<>)\\]+", self.html))
        self.assertTrue(found <= {B.TOP3_URL, "http://127.0.0.1:8787"}, found)  # 로컬 서버 주소는 안내 문장 속 글자

    def test_band_and_no_personal(self):
        band = re.search(r'<div class="band" id="band"[^>]*>(.*?)</div>', self.html).group(1)
        for w in ("AI", "투자 권유가 아닙니다", "모의투자"):
            self.assertIn(w, band)
        low = re.sub(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+", "data:", self.html).lower()
        self.assertEqual([m for m in ("alfredo_private", "data/alfredo/personal", "alfredo_link", "banksalad", "upbit", "/users/") if m in low], [])
        self.assertNotIn("안전 자산", re.sub(r"'안전 자산'이라는 말은[^<]*", "", self.html))

    def test_confidence(self):
        conf = self.BB.confidence
        sig = lambda *xs: [{"x": x} for x in xs]
        self.assertEqual(conf(sig(1, -1, 1, 1, 0.5))["score"], 50)
        self.assertEqual(conf(sig(1, -1, 1, 1, 0.5))["side_pct"], 75)                 # 50 + 50 ÷ 2
        self.assertEqual(conf(sig(0.5, -0.5, 0.5, 0, 0))["label"], "약한 상승 쪽")     # 점수 +10 → 55%(54% 넘음)
        self.assertEqual(conf(sig(0.5, -0.5, 0.25, 0.15, 0))["label"], "중립")       # 점수 +8 → 54%(이하는 중립)
        self.assertEqual(conf(sig(1, -1, 0, 0, 0))["label"], "중립")                 # 0 → 50%
        self.assertEqual(conf(sig(0.5, 0.5, 0.5, 0.5))["score"], 50)
        self.assertEqual(conf(sig(1, None, None, None, None))["score"], None)        # 자료 20% < 50% → 보류
        self.assertEqual(conf(sig(1, 1, 0, None, None))["score"], 67)               # 자료 60%: 분모에서 뺌
        self.assertEqual(self.BB.round_away(-12.5), -13)
        self.assertEqual(self.BB.label_of(20), "약한 상승 쪽")
        self.assertEqual(self.BB.label_of(19), "중립")
        self.assertEqual(self.BB.label_of(-20), "약한 하락 쪽")


class ChatServer(unittest.TestCase):
    """알프레도 채팅(로컬 서버): 권유 표현 검사, AI에 주는 자료는 화면 자료뿐."""

    @classmethod
    def setUpClass(cls):
        import chat_server as C
        cls.C = C
        with open(C.BOARD_JSON, encoding="utf-8") as f:
            cls.board = json.load(f)

    def test_advice_blocked(self):
        for bad in ("지금 사세요.", "BTC는 매수를 추천합니다.", "당장 매도하세요", "비중을 20%로 늘리세요"):
            self.assertTrue(self.C.check(bad)[1], bad)
        ok = "확신도 75%는 신호 다섯 개 중 넷이 같은 방향이라는 뜻입니다. 사고팔 시점은 사용자가 정합니다."
        self.assertEqual(self.C.check(ok), (ok, False))

    def test_prompt_has_only_screen_facts(self):
        p = self.C.build_prompt(self.board, "coin", "BTC", "확신도 설명해줘", [{"role": "user", "text": "안녕"}])
        self.assertIn("투자 권유를 하지 않는다", p)
        self.assertIn('"id": "BTC"', p)
        low = p.lower()
        self.assertEqual([m for m in ("alfredo_private", "personal", "banksalad", "토스", "/users/") if m in low], [])
