"""공개 API 요청 지킴이(2026-10-20, 멘토 보안 코멘트 반영): 요청 횟수 제한과 AI 수집기 차단.

- 대상: 공개 요청(public_scope.is_public)으로 들어온 /api 경로만. 맥에서 직접 연 화면과 저장본 만들기(맥 안 127.0.0.1)는 제외.
- AI 수집기: robots.txt·noai 는 '요청'일 뿐이라(보장 아님), 알려진 AI 학습용 수집기 User-Agent 는 /api 에서 403 으로 막는다.
- 요청 횟수: 한 접속 주소(키)마다 60초에 PER_KEY_LIMIT 번, 공개 요청 전체는 60초에 GLOBAL_LIMIT 번까지. 넘으면 429.
  접속 주소는 프록시(Vercel·Funnel)가 넘긴 X-Forwarded-For 의 첫 주소다. 바깥에서 지어낸 값으로 키를 바꿔도 전체 한도는 남는다.
  화면은 60초마다 몇 개의 /api 를 부르므로(05_프론트/app/app.js) 한 사람이 쓰는 데는 닿지 않는 값이다.
  같은 와이파이(공용 IP)에서 여럿이 열어도 여유가 있게 잡았다. 값은 환경 변수로 바꿀 수 있다.
- 접속 주소는 메모리에서 횟수를 세는 데만 쓰고 파일에 남기지 않는다(최소 수집). 60초 넘게 조용한 주소는 다음 정리(요청이 올 때
  60초마다 한 번) 때 지운다. 서버를 다시 켜면 모두 사라진다.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import public_scope

WINDOW_SEC = 60.0
PER_KEY_LIMIT = int(os.environ.get("TOP3_RATE_PER_MIN", "600"))
GLOBAL_LIMIT = int(os.environ.get("TOP3_RATE_GLOBAL_PER_MIN", "3000"))
MAX_KEYS = 5000                      # 키가 너무 많아지면 오래된 것부터 버린다(메모리 보호)

# 알려진 AI 학습·수집용 User-Agent(소문자 비교, 부분 일치). 일반 검색엔진·브라우저는 막지 않는다.
AI_CRAWLER_MARKERS = ("gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "claude-web", "claude-user", "anthropic-ai",
                      "ccbot", "perplexitybot", "perplexity-user", "bytespider", "amazonbot", "meta-externalagent",
                      "meta-externalfetcher", "facebookbot", "cohere-ai", "cohere-training-data-crawler", "diffbot",
                      "imagesiftbot", "omgili", "timpibot", "youbot", "ai2bot", "scrapy")
# (Google-Extended · Applebot-Extended 는 User-Agent 가 아니라 robots.txt 표식이라 robots.txt 쪽에만 둔다)


def is_ai_crawler(user_agent: Optional[str]) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in AI_CRAWLER_MARKERS)


def client_key(request: Request) -> str:
    """횟수를 셀 키. 프록시(Vercel·Funnel)를 거친 요청은 X-Forwarded-For 의 첫 주소, 아니면 접속 주소."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff.strip():
        return xff.split(",")[0].strip()[:64]
    client = request.client
    return (client.host if client else "unknown")[:64]


class RateLimiter:
    """60초 미끄럼 창. 시험에서 now 를 넘길 수 있게 순수하게 둔다."""

    def __init__(self, per_key: int = PER_KEY_LIMIT, global_limit: int = GLOBAL_LIMIT, window: float = WINDOW_SEC):
        self.per_key, self.global_limit, self.window = per_key, global_limit, window
        self.hits: dict[str, deque] = {}
        self.all: deque = deque()
        self.lock = threading.Lock()
        self.last_sweep = None

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0] >= self.window:
            q.popleft()

    def _sweep(self, now: float) -> None:
        """60초 넘게 요청이 없던 주소를 지운다(요청이 올 때 60초마다 한 번)."""
        if self.last_sweep is not None and now - self.last_sweep < self.window:
            return
        self.last_sweep = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] >= self.window]:
            del self.hits[k]

    def allow(self, key: str, now: Optional[float] = None) -> tuple[bool, int]:
        """(허용 여부, 다시 시도까지 초)."""
        now = time.monotonic() if now is None else now
        with self.lock:
            self._sweep(now)
            self._trim(self.all, now)
            if len(self.all) >= self.global_limit:
                return False, max(1, int(self.window - (now - self.all[0])) + 1)
            q = self.hits.get(key)
            if q is None:
                if len(self.hits) >= MAX_KEYS:            # 가장 오래 조용한 키부터 버림
                    oldest = min(self.hits, key=lambda k: self.hits[k][-1] if self.hits[k] else 0)
                    self.hits.pop(oldest, None)
                q = self.hits[key] = deque()
            self._trim(q, now)
            if len(q) >= self.per_key:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            self.all.append(now)
            return True, 0


def is_local_exporter(request: Request) -> bool:
    """저장본 만들기(scripts/export_snapshot.py): 맥 안 127.0.0.1 에서 X-Top3-Public 만 붙여 부른다. 프록시 머리글이 있으면 아니다."""
    names = {k.lower() for k in request.headers.keys()}
    if public_scope.PUBLIC_HEADER not in names:
        return False
    if names & public_scope.PROXY_HEADERS or any(n.startswith(public_scope.PROXY_PREFIX) for n in names):
        return False
    if public_scope._hostname(request.headers.get("host", "")) not in public_scope.LOCAL_HOSTS:
        return False
    client = request.client
    return client is not None and public_scope._loopback(client.host)


def verdict(request: Request, limiter: RateLimiter, now: Optional[float] = None) -> Optional[JSONResponse]:
    """막아야 하면 응답을, 통과면 None 을 돌려준다."""
    if not request.url.path.startswith("/api"):
        return None
    if not public_scope.is_public(request) or is_local_exporter(request):
        return None
    if is_ai_crawler(request.headers.get("user-agent")):
        return JSONResponse({"detail": "AI 학습·수집용 자동 접근은 허용하지 않습니다(이용약관 금지 행위)."}, status_code=403)
    ok, retry = limiter.allow(client_key(request), now)
    if not ok:
        return JSONResponse({"detail": "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요."}, status_code=429,
                            headers={"Retry-After": str(retry)})
    return None


class RequestGuardMiddleware:
    """순수 ASGI 미들웨어(응답 본문을 감싸지 않아 가볍다)."""

    def __init__(self, app, limiter: Optional[RateLimiter] = None):
        self.app = app
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        blocked = verdict(Request(scope), self.limiter)
        if blocked is not None:
            await blocked(scope, receive, send)
            return
        await self.app(scope, receive, send)
