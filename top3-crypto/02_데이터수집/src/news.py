"""뉴스 헤드라인 수집. 2026-10-03 추가, 같은 날 공식 API 출처를 더함.

- 제목·링크·발행 시각·언론사만 받는다. 기사 본문은 받지 않는다.
- 출처 종류(conf news.feeds[].type)
  - naver: 네이버 뉴스 검색 API(공식, 하루 25,000회 무료). .env 의 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET 필요. 없으면 건너뜀.
  - gdelt: GDELT DOC 2.0 API(공식 무료 공개 데이터, 출처 표기 조건). 키 없음. 5초에 1회 제한.
  - rss: 매체 RSS. 매체 약관에 자동 수집 제한 조항이 있어 기본 꺼짐(feeds[].enabled=false).
    근거: 08_참고자료/기획서ver3_공식근거_2026-10-03.md Q8. 소스 비교용 1회 수집은 `python3 src/collect.py --news-once`.
- 피드마다 요청 간격(feeds[].min_interval_min, 없으면 news.min_interval_min)을 지킨다.
- 종목 표시는 제목 키워드로만 붙인다. 라벨(긍정/부정)은 여기서 하지 않는다.
"""
from __future__ import annotations

import email.utils
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = {"User-Agent": "top3-crypto-internal-reader/1.0"}
ATOM = "{http://www.w3.org/2005/Atom}"

# 제목에서 종목을 찾는 단어. 영문은 앞뒤가 영문·숫자가 아니면(한글 조사가 붙은 "BTC는"도 잡음, 10-04 GPT-6.1 Sol 재현:
# 파이썬 \b 는 한글도 글자로 봐서 "BTC는"을 놓쳤음), 국문은 아래 _ko_word 규칙.
_EN = r"(?<![a-z0-9])({})(?![a-z0-9])"
SYMBOL_WORDS = {
    "BTC": (_EN.format("bitcoin|btc"), ("비트코인",)),
    "ETH": (_EN.format("ethereum|ether|eth"), ("이더리움",)),
    "XRP": (_EN.format("xrp|ripple"), ("리플", "엑스알피")),
}
CRYPTO_WORDS = (_EN.format("crypto|cryptocurrency|stablecoin|altcoin|defi"),
                ("암호화폐", "가상자산", "가상화폐", "코인", "스테이블코인", "디지털자산"))


# 한국어는 띄어쓰기 단위로 본다: 낱말 앞이 한글이 아니고, 뒤는 한글이 아니거나 조사로 끝나야 함
# ("트리플"·"리플레이"·"코인노래방" 같은 부분 일치를 막음, 10-03 Claude Fable 검토)
_HANGUL = re.compile(r"[가-힣]")
_PARTICLES = ("으로", "에서", "까지", "보다", "이다", "이며", "이고", "은", "는", "이", "가", "을", "를",
              "의", "도", "과", "와", "로", "에", "만")


def _ko_word(title: str, word: str) -> bool:
    start = 0
    while True:
        i = title.find(word, start)
        if i < 0:
            return False
        start = i + 1
        if i > 0 and _HANGUL.match(title[i - 1]):
            continue
        rest = title[i + len(word):]
        if not rest or not _HANGUL.match(rest[0]):
            return True
        if any(rest.startswith(p) and (len(rest) == len(p) or not _HANGUL.match(rest[len(p)])) for p in _PARTICLES):
            return True


def match_symbols(title: str) -> str:
    low = title.lower()
    found = [sym for sym, (pat, ko) in SYMBOL_WORDS.items()
             if re.search(pat, low) or any(_ko_word(title, w) for w in ko)]
    if found:
        return ",".join(found)
    pat, ko = CRYPTO_WORDS
    if re.search(pat, low) or any(_ko_word(title, w) for w in ko):
        return "CRYPTO"
    return ""


def _parse_time(text: str | None):
    if not text:
        return None
    text = text.strip()
    try:
        d = email.utils.parsedate_to_datetime(text)  # RSS pubDate (RFC 822)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            import datetime as dt
            d = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))  # Atom (ISO 8601)
        except ValueError:
            return None
    if d.tzinfo is None:
        import datetime as dt
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def parse_feed(xml_bytes: bytes):
    """RSS 2.0 과 Atom 을 모두 읽어 (title, url, published_ms) 목록으로."""
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        url = (it.findtext("link") or "").strip()
        if title and url:
            items.append((title, url, _parse_time(it.findtext("pubDate"))))
    for it in root.iter(f"{ATOM}entry"):
        title = (it.findtext(f"{ATOM}title") or "").strip()
        link = it.find(f"{ATOM}link")
        url = (link.get("href") if link is not None else "") or ""
        pub = it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated")
        if title and url:
            items.append((title, url.strip(), _parse_time(pub)))
    return items


REPO = Path(__file__).resolve().parents[2]


def _env(key: str) -> str | None:
    """환경변수, 없으면 저장소 루트 .env 에서 읽는다. 값은 출력하지 않는다."""
    if os.environ.get(key):
        return os.environ[key]
    path = REPO / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == key and v.strip():
                    return v.strip().strip('"').strip("'")
    return None


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _clean(text: str) -> str:
    """네이버 결과의 <b> 태그·HTML 엔티티 제거."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def parse_naver(body: bytes):
    """네이버 뉴스 검색 JSON → (title, url, published_ms, publisher). 원문 링크(originallink)를 우선."""
    items = []
    for it in json.loads(body.decode("utf-8")).get("items", []):
        title = _clean(it.get("title"))
        url = (it.get("originallink") or it.get("link") or "").strip()
        if title and url:
            items.append((title, url, _parse_time(it.get("pubDate")), _domain(url)))
    return items


def parse_gdelt(body: bytes):
    """GDELT DOC 2.0 artlist JSON → (title, url, published_ms, publisher, lang). 제한 안내(문자열)면 ValueError."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text.startswith("{"):
        raise ValueError("GDELT 응답이 JSON 아님(요청 간격 제한 안내 등): " + text[:60])
    items = []
    for a in json.loads(text).get("articles", []) or []:
        title, url, seen = (a.get("title") or "").strip(), (a.get("url") or "").strip(), a.get("seendate") or ""
        ms = None
        m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z", seen)
        if m:
            import datetime as dt
            ms = int(dt.datetime(*map(int, m.groups()), tzinfo=dt.timezone.utc).timestamp() * 1000)
        lang = {"English": "en", "Korean": "ko"}.get(a.get("language"), (a.get("language") or "")[:2].lower())
        if title and url:
            items.append((title, url, ms, a.get("domain") or _domain(url), lang))
    return items


def _get(url: str, timeout, headers=None) -> bytes:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fetch_feed(feed, timeout):
    """출처 하나를 받아 (title, url, published_ms, publisher, lang) 목록으로. 키가 없으면 None."""
    kind = feed.get("type", "rss")
    if kind == "naver":
        cid, sec = _env("NAVER_CLIENT_ID"), _env("NAVER_CLIENT_SECRET")
        if not (cid and sec):
            return None
        out = []
        for q in feed["queries"]:
            url = ("https://openapi.naver.com/v1/search/news.json?display=%d&sort=date&query=%s"
                   % (int(feed.get("display", 20)), urllib.parse.quote(q)))
            body = _get(url, timeout, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
            out += [(t, u, p, pub, "ko") for (t, u, p, pub) in parse_naver(body)]
        return out
    if kind == "gdelt":
        params = {"query": feed["query"], "mode": "artlist", "format": "json", "sort": "datedesc",
                  "maxrecords": str(feed.get("maxrecords", 50)), "timespan": feed.get("timespan", "3h")}
        return parse_gdelt(_get("https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params), timeout))
    return [(t, u, p, feed["name"], feed.get("lang")) for (t, u, p) in parse_feed(_get(feed["url"], timeout))]


def _error_kind(exc: Exception) -> str:
    """화면에 보일 짧은 실패 이유(비밀값·주소 없이)."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return {401: "HTTP 401 인증 실패", 403: "HTTP 403 거절", 429: "HTTP 429 요청 제한"}.get(code, f"HTTP {code}")
    if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc):
        return "시간 초과"
    if isinstance(exc, ValueError):
        return "응답 형식 오류"
    return type(exc).__name__


def collect_news(conf, store, log, force: bool = False, now_ms=None):
    """반환: (성공 호출 수, 실패 수, 신규 행 수). force=True 면 꺼져 있어도 1회 수집."""
    nconf = conf["news"]
    if not force and not conf.get("enabled", {}).get("news", False):
        return 0, 0, 0
    now = now_ms() if now_ms else int(time.time() * 1000)
    ok = failed = new = 0
    for feed in nconf["feeds"]:
        # 꺼진 출처는 건너뜀. --news-once(force)는 약관 확인용으로 RSS 도 1회 받는다
        if not feed.get("enabled", True) and not force:
            continue
        gap_ms = int(feed.get("min_interval_min", nconf.get("min_interval_min", 55))) * 60 * 1000
        key = f"news_last_fetch:{feed['name']}"
        last = store.kv_get(key)
        if not force and last and now - int(last) < gap_ms:
            continue
        try:
            items = _fetch_feed(feed, conf["timeout_sec"])
            if items is None:
                log(f"  news    {feed['name']:<28} 키 없음(.env NAVER_CLIENT_ID·SECRET) → 건너뜀")
                continue
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log(f"  [FAIL] news {feed['name']}: {str(exc)[:120]}")
            store.kv_set(key, now)  # 실패해도 간격은 지킨다
            store.kv_set(f"news_last_error:{feed['name']}", _error_kind(exc))  # 데이터 상태 탭에서 이유를 보이게
            continue
        # 링크는 http(s)만 저장한다(javascript:·data: 등은 버림)
        rows = [(feed["name"], lang or feed.get("lang"), t, u, p, match_symbols(t), pub) for (t, u, p, pub, lang) in items
                if u.lower().startswith(("https://", "http://"))]
        added = store.upsert_news(rows)
        store.kv_set(key, now)
        store.kv_set(f"news_last_ok:{feed['name']}", now)
        store.kv_set(f"news_last_error:{feed['name']}", "")
        new += added
        matched = sum(1 for r in rows if r[5])
        log(f"  news    {feed['name']:<28} {feed.get('lang', ''):<8}     "
            f"수신 {len(rows):>5}건 신규 {added:>5}행 (코인 관련 {matched}건)")
        time.sleep(float(nconf.get("request_sleep_sec", 1.0)))
    # 보관 기간이 정해진 출처(retain_days)는 지난 자료를 지운다(네이버 검색 API 약관 특약 2.4: 서버 보관 최대 21일)
    for feed in nconf["feeds"]:
        days = feed.get("retain_days")
        if days:
            gone = store.prune_news(feed["name"], now - int(days) * 86_400_000)
            if gone:
                log(f"  news    {feed['name']:<28} 보관 {int(days)}일 지난 {gone}행 지움")
    return ok, failed, new
