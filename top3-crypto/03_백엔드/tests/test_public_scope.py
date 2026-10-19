"""공개 범위(10-13 결정 84-A) 시험: 맥에서 직접 연 요청만 전체, 그 밖은 app/public_scope.py 의 화이트리스트만.

- 이 가상환경의 starlette TestClient 는 httpx2 가 있어야 돌아서 쓰지 않고, ASGI 앱(main.app)을 직접 불러 HTTP 요청을 흉내 낸다.
  참고: TestClient 를 쓰면 접속 주소가 'testclient'(루프백 아님)라 늘 공개로 판정된다. 그래서 로컬 경우는 접속 IP·Host 를
  루프백으로 직접 넣고, 'testclient' 접속은 공개가 되는지도 따로 본다.
- 보드·데이터 상태는 DB 대신 실제 응답 모양(04_엔진/reports/trigger_board.json 등)을 본뜬 견본을 _board_full·_engine_full
  자리에 넣는다. 값은 지어낸 것이다(실제 데이터 아님).
실행: cd 03_백엔드 && .venv/bin/python -m unittest discover -s tests
"""
import asyncio
import copy
import importlib.util
import json
import sys
import tempfile
import unicodedata
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starlette.requests import Request  # noqa: E402

from app import main, board, public_scope as pub  # noqa: E402

LOOP = ("127.0.0.1", 50123)
HOST = "127.0.0.1:8765"
HIDDEN = "07_우리_프로젝트는_어떻게_돌아가나.md"

# 공개 응답 어디에도 있으면 안 되는 키(매매 조건·채점·검증 화면 자료)
FORBIDDEN = {"stats", "checks", "tech", "result", "mfe_net_pct", "mae_pct", "ret_net_pct", "h4", "h1", "m15", "weights",
             "indicators", "history_hint", "success_pct", "fee_pct_per_side", "ban_hours", "track", "replay", "strong15",
             "tries_log",
             # 더 본 것: 4시간 분석 점수·계산식 묶음, 15분 확실한 신호, 디스코드·배포·채점 보류, 규칙 시작 시각
             "conf", "explain", "ai_report", "pair_dir", "chase", "strong_marks", "now15", "strong", "strong_dir",
             "explanation", "discord", "snapshot_deploy", "scoring_held", "rules_since_kst", "next_t_close_kst",
             "verify_text", "fix24_success_pct", "thr_pct", "input_json", "conf_replay"}
# 그래프 공개 응답에서 더 빠져야 하는 키(4시간 분석 점수 표시·판정 교차 사건·판정 기준선)
CHART_FORBIDDEN = FORBIDDEN | {"score", "ind", "upper", "lower"}

H4, M15 = 4 * 3_600_000, 900_000
T = 1_791_873_000_000

STAT = {"n": 3, "closed": 2, "open": 1, "success": 1, "success_pct": 50.0, "open_reached": 0, "avg_mfe_pct": 1.2,
        "avg_mae_pct": 0.8, "avg_ret_pct": -0.1, "base_success_pct": 50.0, "opp_success_pct": 50.0, "both_pct": 0.0,
        "avg_hours": 20.5, "long": 2, "short": 1, "small_sample": True}
TRIG = {"symbol": "ETHUSDT", "short": "ETH", "t_bar": T - 8 * M15, "issued_at": T - 8 * M15 + 87_810, "dir": 1, "kind": "on",
        "entry": 2531.69, "end_t": None, "end_close": None, "status": "open", "result": "open", "ai_created_at": None,
        "mfe_net_pct": 0.02, "mae_pct": 0.19, "ret_net_pct": None}
AI_BODY = {"trend_direction": "Short", "expected_change_pct": {"low": -3.5, "high": 1.5},
           "expected_price_range": {"low": 78535, "high": 82605}, "summary_reasoning": "요약",
           "confidence_level": "Medium", "confidence_pct": 70, "key_signals": ["a"], "risks": ["b"],
           "news_analysis": "뉴스", "fear_greed_analysis": "심리",
           "coinbase_premium": {"value_pct": -0.13, "trend": "하락", "interpretation": "해석"},
           "open_interest": {"oi_change_pct": -1.18, "price_change_pct": -2.3, "interpretation": "해석"},
           "technical": {"stochastic": {"k": 8.2, "d": 18.2, "interpretation": "해석"},
                         "macd": {"macd": -152.1, "signal": -89.5, "histogram": -62.6, "interpretation": "해석"},
                         "stochrsi_k": {"value": 16.9, "interpretation": "해석"}},
           "current_price": 81384.4,
           "news_items": [{"id": "n1", "relevance": "coin", "direction": 1, "importance": 2}],
           "factor_weights": {k: {"direction": 0, "weight_pct": 12.5} for k in ("price", "macd", "stoch", "stochrsi", "oi",
                                                                                "premium", "fng", "news")},
           "news_bias": {"x": 1, "score": 1.0, "n": 1},
           "news_ref": [{"id": "n1", "title": "제목", "publisher": "매체", "time": "10-13 09:00"}], "news_filtered": 0}
AI_NODE = {"latest": {"created_at": T - 3_600_000, "kind": "scheduled", "ref_t": T - 3_700_000, "trend_dir": -1,
                      "confidence_pct": 70, "model": "claude-sonnet-5-5", "source": "claude", "created_kst": "10-13 09:47",
                      "ref_kst": "10-13 09:45", "body": AI_BODY},
           "last_try": {"created_kst": "10-13 09:47", "ok": True, "code": None, "retry_at_kst": "12:37", "retry_est": False,
                        "model": "claude-sonnet-5-5", "fallback_from": "limit",
                        "note": "호출 실패 RuntimeError codex 종료 코드 1: … try again at 12:37 PM"}}
CONF = {"version": "conf_v2", "p_long": 77, "side": "Long", "side_pct": 77, "level": "medium", "label": "Long 우세",
        "score": 68, "coverage_pct": 90, "support_pct": 76,
        "groups": {"tech": {"score": 86.5, "coverage_pct": 100, "used": True, "missing": []},
                   "market": {"score": 50.0, "coverage_pct": 81, "used": True, "missing": ["뉴스 방향"]}},
        "missing": ["뉴스 방향"], "note": "뉴스 방향 없음",
        "formula": "기술 지표 (8×(+1)) ÷ 8 × 100 = +100.0 · D = 100.0 · 확신도 = 50 + 0.4 × 100 = 90%",
        "signals": [{"key": "price", "name": "가격 위치", "group": "tech", "w": 8, "x": 1, "used": True,
                     "value": "현재가 > EMA20", "note": "EMA20 위"}],
        "ref_t": T, "ref_kst": "2026-10-13 15:30", "price": 83718.0}
SAMPLE_V4 = {
    "generated_at": "2026-10-13T06:40:08Z", "rules_version": "v-test", "live_start": "2026-10-13T00:46:43Z",
    "conf": {"success_pct": 1.0, "fee_pct_per_side": 0.05, "ban_hours": 12, "on_time_min": 30, "ai_fresh_hours": 4,
             "ai_schedule_kst_hours": [9, 21]},
    "stats": {"official": STAT, "tech": STAT, "official_by_symbol": [{**STAT, "symbol": "BTCUSDT", "short": "BTC"}],
              "tech_by_symbol": [{**STAT, "symbol": "BTCUSDT", "short": "BTC"}],
              "replay": {"reference": {"from": "2018-01-01", "to_exclusive": "2023-12-31", "all": STAT, "rows": [STAT]}}},
    "recent": {"official": [TRIG], "tech": [TRIG],
               "checks": [{"symbol": "ETHUSDT", "short": "ETH", "t_bar": T, "dir": 1, "checked_at": T, "ai_dir": 0,
                           "result": "neutral", "label": "AI 중립", "ai_created_at": T, "ai_ref_t": T}]},
    "ai": {"BTCUSDT": AI_NODE, "ETHUSDT": AI_NODE, "XRPUSDT": {"latest": None, "last_try": None}},
    "core": {"BTCUSDT": {"t": T, "state": 0, "ok": True, "h4": -1, "h1": 0, "m15": 1},
             "ETHUSDT": {"t": T, "state": 1, "ok": True, "h4": 1, "h1": 1, "m15": 1},
             "XRPUSDT": {"t": T, "state": 0, "ok": True, "h4": -1, "h1": 0, "m15": 1}, "_at": T + 120_018},
    "confidence": {"BTCUSDT": CONF, "ETHUSDT": CONF, "XRPUSDT": CONF, "_at": T + 120_018},
}
MARKET = {"price": 83718.0, "at_kst": "15:45", "high_24h": 85000.0, "low_24h": 83000.0, "chg_24h": -1200.0, "chg_24h_pct": -1.4}
SYMBOL = {"symbol": "BTCUSDT", "short": "BTC", "name": "비트코인", "spark": [{"t": "x", "close": 1.0}],
          "strong_marks": [{"t": "x", "dir": 1}], "market": MARKET,
          "now15": {"dir": 1, "label": "롱 확실", "kind": "on", "t_close": "x", "since_kst": "x", "since_hm": "x",
                    "since_today": True, "close": 1.0},
          "status": "ok", "close": 83000.0, "close_kst": "13:00", "chg_24h_pct": -1.0, "score": 43, "strong": False,
          "strong_dir": 0, "label": "Long 우세",
          "indicators": [{"key": "macd", "name": "MACD", "tf": "4시간", "dir": 1, "values": {"MACD": 1.0, "시그널": 0.5},
                          "last_kst": "x", "last_word": "마지막 교차", "rule": "MACD선이 시그널선 위 Long · 아래 Short"}],
          "pair_dir": 1, "formula": "4×(+1) + 2×(+1) + 1×(−1) = +5 → ÷7 ×100 = +71",
          "history_hint": {"score": 43, "n": 10, "period": "a–b", "dir_word": "오른", "match_pct": 55.0},
          "explanation": "해설", "chase": {"move_pct": 1.0, "warn": False, "warn_pct": 5.0, "streak": 1, "bucket": None}}
SAMPLE_BOARD = {
    "generated_at": "2026-10-13T06:41:00Z", "t_close": "2026-10-13T04:00:00Z", "t_close_kst": "10-13 13:00",
    "next_t_close_kst": "10-13 17:00",
    "rules": {"version": "v-test", "status": "temp", "weights": {"macd": 4, "pair": 2, "vpci": 1}},
    "explain": {"source": "llm", "model": "m", "overall": "전체"},
    "alerts": [{"kind": "data", "text": "데이터 지연 · 마지막 15분봉 마감: BTC 10-13 15:30 KST"}],
    "symbols": [SYMBOL, {**SYMBOL, "symbol": "ETHUSDT", "short": "ETH", "name": "이더리움"},
                {"symbol": "XRPUSDT", "short": "XRP", "name": "리플", "spark": [], "strong_marks": [], "market": None,
                 "now15": None, "status": "none", "label": "분석 없음", "explanation": None}],
    "fng": {"value": 60, "date": "2026-10-13", "classification": "Greed", "source": "alternative.me",
            "series": [{"date": "2026-10-13", "value": 60}],
            "events": [{"date": "2026-10-13", "value": 57, "delta": -12, "btc_date": "2026-10-12", "btc_chg_pct": -2.3,
                        "news": [{"title": "제목", "url": "https://example.com/a", "publisher": "매체"}], "news_note": None}]},
    "track": {"since_kst": "x", "rows": [{"symbol": "BTCUSDT", "n": 1, "hit": 1}], "late_n": 0, "prev_versions": None,
              "recent_strong": [{"symbol": "BTCUSDT", "hit": True}], "all": {"strong_scored": 1}},
    "ai_report": {"t_close_kst": "x", "model": "m", "summary": "s"},
    "strong15": {"last_run_kst": "x", "rows": [{"symbol": "BTCUSDT", "hit_pct": 50.0}], "recent": []},
    "replay": {"from": "2024-01-01", "to_exclusive_kst": "x", "reused": False, "rows": [{"symbol": "BTCUSDT", "hit": 1}]},
    "news": [{"source": "gdelt", "source_label": "GDELT", "publisher": "p", "title": "제목", "url": "https://example.com",
              "published": "x", "published_kst": "x", "symbols": "BTC"}],
    "briefing": None,
    "v4": SAMPLE_V4,
    "conf_replay": {"version": "conf_v2", "n_points": 10, "table": {"ALL": {"all": {"r4": {"n": 10, "hit_pct": 50.0}}}}},
}
SAMPLE_ENGINE = {
    "collector": {"last_run_kst": "10-13 15:46:02", "ok_calls": 12, "failed_calls": 0,
                  "schedule": "매시 01·16·31·46분 (15분봉 마감 1분 뒤)", "enabled": {"binance_spot": True, "news": True}},
    "engine": {"cycle_enabled": True, "last_run_kst": "10-13 15:47:00", "live_start": "2026-10-13T00:46:43Z",
               "live_start_kst": "2026-10-13 09:46", "rules_version": "v-test", "rules_status": "temp",
               "rules_since_kst": "10-13 09:00"},
    "candles": [{"symbol": "BTCUSDT", "period": "15m", "n": 100, "min_ts": 1, "max_ts": 2, "from_kst": "a", "to_kst": "b"}],
    "fear_greed": {"n": 30, "from": "a", "to": "b", "source": "alternative.me"},
    "discord": {"t_kst": "x", "status": "sent"},
    "strong15": {"last_run_kst": "x", "rows": 3},
    "news": [{"name": "gdelt", "label": "GDELT", "last_try_kst": "x", "last_ok_kst": "x", "last_error": None, "n_48h": 5}],
    "snapshot_deploy": {"last_ok_kst": "x", "last_fail_kst": None, "failing": False, "last_error": None},
    "scoring_held": 2,
}


def chart_file() -> dict:
    """04_엔진/chart_export.build 와 같은 모양의 그래프 파일(값은 지어냄)."""
    t15 = [T - (20 - i) * M15 for i in range(20)]
    t1 = [T - (5 - i) * 3_600_000 for i in range(5)]
    t4 = [T - (3 - i) * H4 for i in range(3)]
    return {"symbol": "BTCUSDT", "rules_version": "v-test", "days": 7, "generated_at": "x", "generated_ms": T + 60_000,
            "last_close": {"4h": t4[-1], "1h": t1[-1], "15m": t15[-1]},
            "price": {"t": t15, "c": [100.0 + i for i in range(20)]},
            "macd": {"t": t4, "macd": [1.0, 2.0, 3.0], "signal": [0.5, 1.5, 2.5]},
            "sto": {"t": t1, "k": [10.0] * 5, "d": [20.0] * 5}, "srsi": {"t": t1, "k": [30.0] * 5, "d": [40.0] * 5},
            "vpci": {"t": t15, "v": [0.1] * 20, "s": [0.2] * 20},
            "events": [{"t": t4[-1], "ind": "macd", "dir": 1}, {"t": t15[-2], "ind": "vpci", "dir": -1}],
            "analyses": [{"t": t4[-1], "status": "ok", "score": 43, "strong": 1, "strong_dir": 1}],
            "gaps": [], "zone": {"upper": 80, "lower": 20}}


def keys_of(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from keys_of(v)
    elif isinstance(o, list):
        for v in o:
            yield from keys_of(v)


def call(path, headers=None, client=LOOP, host=HOST):
    """ASGI 앱에 GET 한 번. path 는 퍼센트 인코딩된 주소(물음표 뒤는 쿼리)."""
    raw, _, qs = path.partition("?")
    hdrs = ([(b"host", host.encode())] if host is not None else []) + [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": urllib.parse.unquote(raw), "raw_path": raw.encode("ascii"), "query_string": qs.encode("ascii"),
             "root_path": "", "headers": hdrs, "client": client, "server": ("127.0.0.1", 8765)}
    msgs = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        msgs.append(m)

    asyncio.run(main.app(scope, receive, send))
    status = next(m["status"] for m in msgs if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in msgs if m["type"] == "http.response.body")
    return status, (json.loads(body) if body else None)


def fake_request(headers=None, client=LOOP, host=HOST):
    hdrs = ([(b"host", host.encode())] if host is not None else []) + [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": hdrs, "client": client})


class DecideTest(unittest.TestCase):
    """요청 하나가 공개인지 판정(public_scope.is_public)."""

    def test_local_only_when_everything_is_loopback(self):
        for host, client in ((HOST, LOOP), ("localhost:8765", LOOP), ("localhost", LOOP), ("[::1]:8765", ("::1", 1)),
                             ("LOCALHOST:8765", LOOP), ("127.0.0.1:8765", ("::ffff:127.0.0.1", 1))):
            self.assertFalse(pub.is_public(fake_request(host=host, client=client)), (host, client))

    def test_public_cases(self):
        cases = {
            "X-Top3-Public 1": dict(headers={"X-Top3-Public": "1"}),
            "X-Top3-Public 다른 값도": dict(headers={"X-Top3-Public": "0"}),
            "X-Forwarded-For": dict(headers={"X-Forwarded-For": "203.0.113.5"}),
            "X-Forwarded-Host": dict(headers={"X-Forwarded-Host": "top3-crypto.vercel.app"}),
            "X-Forwarded-Proto": dict(headers={"X-Forwarded-Proto": "https"}),
            "Forwarded": dict(headers={"Forwarded": "for=203.0.113.5"}),
            "Tailscale-Funnel-Request": dict(headers={"Tailscale-Funnel-Request": "?1"}),
            "Tailscale- 로 시작": dict(headers={"Tailscale-User-Login": "someone@example.com"}),
            "Host 가 ts.net": dict(host="example-mac.tailnet-example.ts.net"),
            "Host 가 vercel": dict(host="top3-crypto.vercel.app"),
            "Host 에 루프백 IP 가 아닌 숫자": dict(host="192.168.0.10:8765"),
            "Host 없음": dict(host=None),
            "접속 IP 가 바깥": dict(client=("100.101.102.103", 443)),
            "접속 주소 testclient(TestClient 기본)": dict(client=("testclient", 50000)),
            "접속 주소 없음": dict(client=None),
        }
        for name, kw in cases.items():
            self.assertTrue(pub.is_public(fake_request(**kw)), name)

    def test_in_process_call_is_local_and_odd_object_is_public(self):
        self.assertFalse(pub.is_public(None))      # 시험·스크립트에서 함수를 바로 부를 때(HTTP 요청이 아님)
        self.assertTrue(pub.is_public(object()))   # 판단할 수 없는 것 → 공개


class EndpointScopeTest(unittest.TestCase):
    """HTTP 요청(ASGI)으로 각 경로가 로컬·공개에 맞게 답하는지. DB 대신 견본을 넣는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "BTCUSDT.json").write_text(json.dumps(chart_file()), encoding="utf-8")
        for p in (mock.patch.object(board, "_board_full", side_effect=lambda: copy.deepcopy(SAMPLE_BOARD)),
                  mock.patch.object(board, "_engine_full", side_effect=lambda: copy.deepcopy(SAMPLE_ENGINE)),
                  mock.patch.object(board, "CHART_DIR", Path(self.tmp.name))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_local_board_is_full_payload(self):
        st, b = call("/api/board")
        self.assertEqual(st, 200)
        self.assertEqual(b, {**json.loads(json.dumps(SAMPLE_BOARD)), "scope": "local",
                             "verify_text": json.loads(json.dumps(board.pub.LOCAL_VERIFY_TEXT))})

    def test_condition_text_is_not_in_public_bundle(self):
        """검증 화면 설명 문장(조건 논리·채점 정의)은 화면 파일에 없고 로컬 응답으로만 온다(10-13 84-A)."""
        app_dir = Path(__file__).resolve().parents[2] / "05_프론트" / "app"
        bundle = "".join(f.read_text(encoding="utf-8") for f in sorted(app_dir.iterdir()) if f.suffix in (".html", ".js"))
        for k, text in board.pub.LOCAL_VERIFY_TEXT.items():
            self.assertNotIn(text[:30], bundle, k)
        for word in ("80 이상에서 꺾여", "VPCI(15분)가 4시간·1시간이", "세 단계(4시간·1시간·15분)", "가중치 4·2·1"):
            self.assertNotIn(word, bundle, word)

    def test_public_triggers_on_board(self):
        for name, kw in {"X-Forwarded-For": dict(headers={"X-Forwarded-For": "203.0.113.5"}),
                         "X-Top3-Public": dict(headers={"X-Top3-Public": "1"}),
                         "Tailscale-Funnel-Request": dict(headers={"Tailscale-Funnel-Request": "?1"}),
                         "Host 가 루프백 아님": dict(host="example-mac.tailnet-example.ts.net"),
                         "testclient 접속": dict(client=("testclient", 50000))}.items():
            st, b = call("/api/board", **kw)
            self.assertEqual((st, b["scope"]), (200, "public"), name)
            self.assertNotIn("track", b, name)

    def test_public_board_whitelist(self):
        _, b = call("/api/board", headers={"X-Top3-Public": "1"})
        self.assertEqual(set(b), {"generated_at", "t_close", "t_close_kst", "alerts", "fng", "news", "briefing", "rules",
                                  "symbols", "v4", "scope"})
        self.assertEqual(b["rules"], {"version": "v-test", "status": "temp"})
        self.assertEqual([set(s) for s in b["symbols"]], [{"symbol", "short", "name", "market", "spark"}] * 3)
        self.assertEqual(b["symbols"][0]["market"], MARKET)
        self.assertEqual(b["symbols"][0]["spark"], [{"t": "x", "close": 1.0}])               # V5: 7일 가격선 공개
        self.assertEqual(b["fng"], json.loads(json.dumps(SAMPLE_BOARD["fng"])))            # 공포탐욕 · 크게 움직인 날
        self.assertEqual(b["news"], SAMPLE_BOARD["news"])
        v = b["v4"]
        self.assertEqual(set(v), {"generated_at", "rules_version", "live_start", "ai", "confidence", "core", "recent"})
        want_ai = json.loads(json.dumps(SAMPLE_V4["ai"]))
        for node in want_ai.values():                                                       # 원문 실패 사유(note)만 빠짐
            if node.get("last_try"):
                node["last_try"].pop("note")
        self.assertEqual(v["ai"], want_ai)
        self.assertEqual(v["confidence"], json.loads(json.dumps(SAMPLE_V4["confidence"])))  # 확신도는 계약 필드 그대로
        self.assertEqual(v["core"]["ETHUSDT"], {"t": T, "state": 1, "ok": True})            # 충족 여부만
        self.assertEqual(v["core"]["_at"], T + 120_018)
        self.assertEqual(v["recent"], {"official": [{k: TRIG[k] for k in ("symbol", "short", "t_bar", "issued_at", "dir",
                                                                         "entry")}]})

    def test_unknown_inner_keys_stay_local(self):
        """V5 6절 3): 안쪽 객체에 새 내부 필드가 생겨도 공개 응답에는 저절로 나가지 않고, 로컬 원본은 그대로."""
        full = copy.deepcopy(SAMPLE_BOARD)
        full["v4"]["ai"]["BTCUSDT"]["latest"]["secret_a"] = 1
        full["v4"]["ai"]["BTCUSDT"]["latest"]["body"]["secret_b"] = 1
        full["v4"]["ai"]["BTCUSDT"]["last_try"]["secret_c"] = 1
        full["v4"]["confidence"]["BTCUSDT"]["secret_d"] = 1
        full["v4"]["confidence"]["BTCUSDT"]["groups"]["tech"]["secret_e"] = 1
        full["v4"]["confidence"]["BTCUSDT"]["signals"][0]["secret_f"] = 1
        full["fng"]["secret_g"] = 1
        full["fng"]["events"][0]["secret_h"] = 1
        full["fng"]["events"][0]["news"][0]["secret_i"] = 1
        full["symbols"][0]["spark"][0]["secret_j"] = 1
        full["news"][0]["secret_k"] = 1
        full["alerts"][0]["secret_l"] = 1
        secrets = {f"secret_{c}" for c in "abcdefghijkl"}
        with mock.patch.object(board, "_board_full", side_effect=lambda: copy.deepcopy(full)):
            _, pb = call("/api/board", headers={"X-Top3-Public": "1"})
            _, loc = call("/api/board")
        self.assertEqual(set(keys_of(pb)) & secrets, set())
        self.assertEqual(set(keys_of(loc)) & secrets, secrets)
        self.assertEqual(loc["v4"]["ai"]["BTCUSDT"]["last_try"]["note"], AI_NODE["last_try"]["note"])   # 로컬은 원문 사유 그대로
        self.assertNotIn("note", pb["v4"]["ai"]["BTCUSDT"]["last_try"])

    def test_forbidden_keys_absent_from_public_board_chart_engine(self):
        pubh = {"X-Top3-Public": "1"}
        for path, forbidden in (("/api/board", FORBIDDEN), ("/api/engine", FORBIDDEN),
                                ("/api/chart/BTCUSDT?days=7", CHART_FORBIDDEN)):
            st, body = call(path, headers=pubh)
            self.assertEqual(st, 200, path)
            if path == "/api/board":   # 확신도 묶음 이름(groups.tech · market)은 공개 계약이라 키 이름 검사에서 뺀다(모양은 위 시험이 봄)
                for c in (body["v4"]["confidence"] or {}).values():
                    if isinstance(c, dict):
                        self.assertEqual(set(c.pop("groups") or {}), {"tech", "market"})
            self.assertEqual(set(keys_of(body)) & forbidden, set(), path)
        # 같은 견본의 로컬 응답에는 그 키들이 있다(시험이 헛돌지 않는지)
        self.assertTrue({"stats", "checks", "h4", "weights", "indicators", "track", "conf_replay"} <= set(keys_of(call("/api/board")[1])))
        self.assertTrue({"discord", "scoring_held", "rules_since_kst"} <= set(keys_of(call("/api/engine")[1])))

    def test_engine_public_keeps_collection_status_only(self):
        _, e = call("/api/engine", headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertEqual(set(e), {"collector", "engine", "candles", "fear_greed", "news", "scope"})
        self.assertEqual(e["collector"], SAMPLE_ENGINE["collector"])
        self.assertEqual(set(e["engine"]), {"cycle_enabled", "last_run_kst", "live_start", "live_start_kst",
                                            "rules_version", "rules_status"})
        self.assertEqual((e["candles"], e["news"]), (SAMPLE_ENGINE["candles"], SAMPLE_ENGINE["news"]))
        _, loc = call("/api/engine")
        self.assertEqual(loc, {**SAMPLE_ENGINE, "scope": "local"})

    def test_chart_public_keeps_series_drops_markers(self):
        _, loc = call("/api/chart/BTCUSDT?days=7")
        _, pc = call("/api/chart/BTCUSDT?days=7", headers={"X-Top3-Public": "1"})
        self.assertEqual(loc["scope"], "local")
        self.assertTrue(loc["analyses"] and loc["events"] and loc["zone"])
        self.assertEqual((pc["scope"], pc["analyses"], pc["events"], pc["zone"]), ("public", [], [], None))
        for k in ("price", "macd", "sto", "srsi", "vpci", "gaps", "range", "last_close", "last_close_kst", "stale",
                  "days", "generated_ms"):
            self.assertEqual(pc[k], loc[k], k)

    def test_analyses_and_replay_public_are_empty_same_shape_without_reading(self):
        def no_db():
            raise AssertionError("공개 요청이 DB 를 열면 안 됨")
        with mock.patch.object(board, "_db", no_db):
            st, a = call("/api/analyses?limit=120&symbol=BTCUSDT&all_versions=true", headers={"X-Top3-Public": "1"})
        self.assertEqual((st, a), (200, {"count": 0, "data": [], "other_versions_n": 0, "all_versions": True,
                                         "scope": "public"}))
        with mock.patch.object(board, "ENGINE", Path(self.tmp.name)):      # 재현 파일이 없어도 공개는 빈 모양
            st, r = call("/api/replay", headers={"X-Top3-Public": "1"})
        self.assertEqual(st, 200)
        self.assertEqual(r["scope"], "public")
        self.assertTrue(all(v in (None, [], {}) for k, v in r.items() if k not in ("scope", "periods")))
        self.assertEqual(r["periods"], {"reference": None, "check": None})
        real = board._json(board.ENGINE / "reports" / "replay_summary.json")
        if real is not None:                                              # 저장소에 있는 재현 요약과 모양(맨 위 키)이 같다
            self.assertEqual(set(r) - {"scope"}, set(real))
            self.assertEqual(call("/api/replay")[1], {**real, "scope": "local"})


class StudyScopeTest(unittest.TestCase):
    def test_hidden_chapter_exists_so_the_rule_is_not_dead(self):
        for name in pub.STUDY_LOCAL_ONLY:
            self.assertTrue((board.STUDY / name).exists(), f"숨길 장 {name} 이 없음(이름이 바뀌었으면 public_scope 도 고칠 것)")

    def test_list_and_fetch(self):
        q = urllib.parse.quote
        _, loc = call("/api/study")
        _, pubs = call("/api/study", headers={"X-Forwarded-For": "203.0.113.5"})
        self.assertIn(HIDDEN, [d["name"] for d in loc["data"]])
        self.assertNotIn(HIDDEN, [d["name"] for d in pubs["data"]])
        self.assertEqual(pubs["count"], loc["count"] - 1)
        self.assertEqual(call("/api/study/" + q(HIDDEN))[0], 200)
        self.assertEqual(call("/api/study/" + q(HIDDEN), headers={"X-Top3-Public": "1"})[0], 404)
        self.assertEqual(call("/api/study/" + q(HIDDEN), host="top3-crypto.vercel.app")[0], 404)
        nfd = unicodedata.normalize("NFD", HIDDEN)                       # 맥 파일 시스템은 NFD 이름으로도 같은 파일을 찾음
        self.assertEqual(call("/api/study/" + q(nfd), headers={"X-Top3-Public": "1"})[0], 404)
        st, doc = call("/api/study/" + q("00_공부노트_안내.md"), headers={"X-Top3-Public": "1"})
        self.assertEqual(st, 200)
        self.assertIn("공부 노트", doc["markdown"])


class ExportSnapshotTest(unittest.TestCase):
    """저장본(Vercel)은 공개 응답으로만 만든다: 모든 요청에 X-Top3-Public 머리글, 공개 응답이 아니면 멈춤."""

    @classmethod
    def setUpClass(cls):
        p = Path(__file__).resolve().parents[1] / "scripts" / "export_snapshot.py"
        spec = importlib.util.spec_from_file_location("export_snapshot_under_test", p)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def _get(self, path, payload):
        seen = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            seen.append(req)
            return Resp()
        with mock.patch.object(self.mod.urllib.request, "urlopen", fake_urlopen):
            out = self.mod.get(path)
        return out, seen[0]

    def test_every_request_carries_public_header(self):
        for path, payload in (("/api/board", {"scope": "public", "t_close": "x"}), ("/api/study", {"count": 0, "data": []}),
                              ("/api/chart/BTCUSDT?days=3", {"scope": "public"})):
            out, req = self._get(path, payload)
            self.assertEqual(out, payload)
            self.assertEqual(req.get_header("X-top3-public"), "1", path)
            self.assertEqual(req.full_url, self.mod.API + path)

    def test_robots_asks_ai_crawlers_not_to_collect(self):
        txt = self.mod.robots_txt()
        for ua in ("GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "CCBot", "PerplexityBot", "Bytespider", "Amazonbot",
                   "Applebot-Extended"):
            self.assertIn(f"User-agent: {ua}\nDisallow: /", txt)
        self.assertTrue(txt.rstrip().endswith("User-agent: *\nAllow: /"))

    def test_refuses_non_public_answers(self):
        with self.assertRaises(self.mod.NotPublic):
            self._get("/api/board", {"t_close": "x"})                  # 옛 서버: scope 없음
        with self.assertRaises(self.mod.NotPublic):
            self._get("/api/engine", {"scope": "local"})


if __name__ == "__main__":
    unittest.main()
