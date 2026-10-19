"""공개 API 요청 지킴이 시험(app/request_guard.py, 2026-10-20).

실행: cd 03_백엔드 && .venv/bin/python -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.requests import Request  # noqa: E402

from app import request_guard as rg  # noqa: E402

LOOP = ("127.0.0.1", 50000)
HOST = "127.0.0.1:8765"


def req(path="/api/board", headers=None, client=LOOP, host=HOST):
    hdrs = [(k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()]
    if host is not None:
        hdrs.append((b"host", host.encode()))
    return Request({"type": "http", "method": "GET", "path": path, "headers": hdrs, "client": client,
                    "query_string": b"", "scheme": "http", "server": ("127.0.0.1", 8765)})


VIA_VERCEL = {"X-Forwarded-For": "203.0.113.5", "X-Forwarded-Host": "top3-crypto.vercel.app",
              "User-Agent": "Mozilla/5.0 (Macintosh) Safari/605.1.15"}


class GuardTest(unittest.TestCase):
    def test_local_screen_is_never_limited(self):
        lim = rg.RateLimiter(per_key=2, global_limit=2)
        for _ in range(10):
            self.assertIsNone(rg.verdict(req(), lim, now=0.0))

    def test_local_snapshot_exporter_is_not_limited(self):
        lim = rg.RateLimiter(per_key=2, global_limit=2)
        for _ in range(10):
            self.assertIsNone(rg.verdict(req(headers={"X-Top3-Public": "1"}), lim, now=0.0))

    def test_public_request_is_limited_per_key_and_recovers(self):
        lim = rg.RateLimiter(per_key=3, global_limit=100)
        for i in range(3):
            self.assertIsNone(rg.verdict(req(headers=VIA_VERCEL), lim, now=float(i)))
        blocked = rg.verdict(req(headers=VIA_VERCEL), lim, now=3.0)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("retry-after", {k.lower() for k in blocked.headers.keys()})
        other = dict(VIA_VERCEL, **{"X-Forwarded-For": "198.51.100.7"})
        self.assertIsNone(rg.verdict(req(headers=other), lim, now=3.0))        # 다른 주소는 따로 센다
        self.assertIsNone(rg.verdict(req(headers=VIA_VERCEL), lim, now=61.0))   # 60초가 지나면 다시 됨

    def test_idle_addresses_are_forgotten(self):                            # 접속 주소는 60초 넘게 조용하면 메모리에서 지움
        lim = rg.RateLimiter(per_key=100, global_limit=1000)
        a = dict(VIA_VERCEL, **{"X-Forwarded-For": "203.0.113.1"})
        b = dict(VIA_VERCEL, **{"X-Forwarded-For": "203.0.113.2"})
        self.assertIsNone(rg.verdict(req(headers=a), lim, now=0.0))
        self.assertIn("203.0.113.1", lim.hits)
        self.assertIsNone(rg.verdict(req(headers=b), lim, now=70.0))
        self.assertNotIn("203.0.113.1", lim.hits)
        self.assertIn("203.0.113.2", lim.hits)

    def test_global_cap(self):
        lim = rg.RateLimiter(per_key=100, global_limit=2)
        a = dict(VIA_VERCEL, **{"X-Forwarded-For": "203.0.113.1"})
        b = dict(VIA_VERCEL, **{"X-Forwarded-For": "203.0.113.2"})
        c = dict(VIA_VERCEL, **{"X-Forwarded-For": "203.0.113.3"})
        self.assertIsNone(rg.verdict(req(headers=a), lim, now=0.0))
        self.assertIsNone(rg.verdict(req(headers=b), lim, now=0.0))
        self.assertEqual(rg.verdict(req(headers=c), lim, now=0.0).status_code, 429)

    def test_ai_crawlers_are_blocked_on_public_api_only(self):
        lim = rg.RateLimiter()
        for ua in ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
                   "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", "CCBot/2.0 (https://commoncrawl.org/faq/)",
                   "Mozilla/5.0 (compatible; PerplexityBot/1.0)", "Mozilla/5.0 (compatible; Bytespider)"):
            r = rg.verdict(req(headers=dict(VIA_VERCEL, **{"User-Agent": ua})), lim, now=0.0)
            self.assertIsNotNone(r, ua)
            self.assertEqual(r.status_code, 403, ua)
        # 화면 파일(/api 밖)은 지킴이가 보지 않는다(정적 파일은 Vercel 이 낸다)
        self.assertIsNone(rg.verdict(req(path="/index.html", headers=dict(VIA_VERCEL, **{"User-Agent": "GPTBot"})), lim, now=0.0))
        # 맥에서 직접 연 요청은 막지 않는다
        self.assertIsNone(rg.verdict(req(headers={"User-Agent": "GPTBot"}), lim, now=0.0))

    def test_normal_browsers_and_search_engines_pass(self):
        lim = rg.RateLimiter()
        for ua in ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36",
                   "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                   "Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)"):
            self.assertIsNone(rg.verdict(req(headers=dict(VIA_VERCEL, **{"User-Agent": ua})), lim, now=0.0), ua)

    def test_client_key_uses_first_forwarded_address(self):
        self.assertEqual(rg.client_key(req(headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})), "203.0.113.9")
        self.assertEqual(rg.client_key(req(client=("100.64.0.5", 1))), "100.64.0.5")

    def test_middleware_answers_blocked_request_without_calling_app(self):
        called = []

        async def app(scope, receive, send):
            called.append(scope["path"])

        mw = rg.RequestGuardMiddleware(app, limiter=rg.RateLimiter())
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {"type": "http", "method": "GET", "path": "/api/board", "query_string": b"", "scheme": "http",
                 "server": ("127.0.0.1", 8765), "client": LOOP,
                 "headers": [(b"host", HOST.encode()), (b"x-forwarded-for", b"203.0.113.5"), (b"user-agent", b"GPTBot/1.2")]}
        asyncio.run(mw(scope, receive, send))
        self.assertEqual(called, [])
        self.assertEqual(sent[0]["status"], 403)
        scope_ok = dict(scope, headers=[(b"host", HOST.encode())])
        asyncio.run(mw(scope_ok, receive, send))
        self.assertEqual(called, ["/api/board"])


if __name__ == "__main__":
    unittest.main()
