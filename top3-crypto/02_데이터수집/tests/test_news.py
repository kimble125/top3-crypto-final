"""뉴스 수집 시험. 실행: cd 02_데이터수집 && python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import news  # noqa: E402
from store import Store  # noqa: E402


class TestParsers(unittest.TestCase):
    def test_naver(self):
        body = json.dumps({"items": [
            {"title": "<b>비트코인</b> 1억 돌파&quot;", "originallink": "https://www.example.co.kr/a/1",
             "link": "https://n.news.naver.com/x", "pubDate": "Sat, 03 Oct 2026 13:00:00 +0900"},
            {"title": "링크 없음", "originallink": "", "link": ""}]}).encode()
        items = news.parse_naver(body)
        self.assertEqual(len(items), 1)
        t, u, p, pub = items[0]
        self.assertEqual(t, '비트코인 1억 돌파"')
        self.assertEqual(u, "https://www.example.co.kr/a/1")     # 원문 링크 우선
        self.assertEqual(pub, "example.co.kr")
        self.assertEqual(p, 1791000000000)                        # 13:00 KST = 04:00 UTC
        self.assertEqual(news.match_symbols(t), "BTC")

    def test_gdelt(self):
        body = json.dumps({"articles": [{"title": "Ethereum ETF flows", "url": "https://www.coindesk.com/x",
                                         "seendate": "20261003T040000Z", "domain": "coindesk.com", "language": "English"}]}).encode()
        (t, u, p, pub, lang), = news.parse_gdelt(body)
        self.assertEqual((pub, lang, p), ("coindesk.com", "en", 1791000000000))
        self.assertEqual(news.match_symbols(t), "ETH")
        with self.assertRaises(ValueError):
            news.parse_gdelt(b"Please limit requests to one every 5 seconds")
        self.assertEqual(news.parse_gdelt(b"{}"), [])


class TestSymbols(unittest.TestCase):
    def test_korean_word_boundary(self):
        self.assertEqual(news.match_symbols("트리플 크라운 달성한 KBO 선수"), "")
        self.assertEqual(news.match_symbols("리플레이 영상 공개"), "")
        self.assertEqual(news.match_symbols("코인노래방 매출 급감"), "")
        self.assertEqual(news.match_symbols("리플, 송금 파트너 추가"), "XRP")
        self.assertEqual(news.match_symbols("리플이 소송에서 이겼다"), "XRP")
        self.assertEqual(news.match_symbols("비트코인·이더리움 동반 하락"), "BTC,ETH")
        self.assertEqual(news.match_symbols("코인 시장 거래량 감소"), "CRYPTO")
        self.assertEqual(news.match_symbols("가상자산 과세 유예"), "CRYPTO")
        self.assertEqual(news.match_symbols("Ripple wins appeal"), "XRP")


class TestTickers(unittest.TestCase):
    def test_ticker_with_korean_particle(self):
        self.assertEqual(news.match_symbols("BTC는 상승"), "BTC")        # 10-04 GPT-6.1 Sol 재현: 전에는 빈 값
        self.assertEqual(news.match_symbols("XRP가 승소"), "XRP")
        self.assertEqual(news.match_symbols("ETHUSD 차트"), "")          # 영문이 이어지면 다른 낱말


class TestStore(unittest.TestCase):
    def test_publisher_column_and_migration(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.db"
            c = sqlite3.connect(path)   # 10-03 이전 스키마(publisher 없음)
            c.execute("CREATE TABLE news (news_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, lang TEXT, "
                      "title TEXT NOT NULL, url TEXT NOT NULL UNIQUE, published_at INTEGER, symbols TEXT, fetched_at INTEGER NOT NULL)")
            c.commit(); c.close()
            s = Store(path)
            self.assertEqual(s.upsert_news([("naver_news", "ko", "제목", "https://a/1", 1, "BTC", "a.kr"),
                                            ("rss", "en", "t", "https://a/2", None, "")]), 2)
            self.assertEqual(s.upsert_news([("naver_news", "ko", "제목", "https://a/1", 1, "BTC", "a.kr")]), 0)  # 같은 URL 무시
            self.assertEqual(s.conn.execute("SELECT publisher FROM news WHERE url='https://a/1'").fetchone()[0], "a.kr")
            # 예전에 꺼진 RSS 로 받은 기사를 공식 API 가 다시 받으면 출처가 바뀐다(새 행은 아님, 10-04 GPT-6.1 Sol)
            self.assertEqual(s.upsert_news([("naver_news", "en", "t", "https://a/2", None, "", "a.com")]), 0)
            self.assertEqual(s.conn.execute("SELECT source, publisher FROM news WHERE url='https://a/2'").fetchone(),
                             ("naver_news", "a.com"))
            s.close()

    def test_prune_news_keeps_recent_and_other_sources(self):   # 네이버 약관 2.4: 서버 보관 최대 21일
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "t.db")
            s.upsert_news([("naver_news", "ko", "old", "https://a/1", 0, ""), ("naver_news", "ko", "new", "https://a/2", 0, ""),
                           ("gdelt", "en", "keep", "https://b/1", 0, "")])
            s.conn.execute("UPDATE news SET fetched_at=1000 WHERE url IN ('https://a/1', 'https://b/1')")
            s.conn.commit()
            self.assertEqual(s.prune_news("naver_news", 5000), 1)
            left = sorted(r[0] for r in s.conn.execute("SELECT title FROM news"))
            self.assertEqual(left, ["keep", "new"])

    def test_error_kind(self):
        import urllib.error
        self.assertEqual(news._error_kind(urllib.error.HTTPError("u", 429, "x", {}, None)), "HTTP 429 요청 제한")
        self.assertEqual(news._error_kind(ValueError("bad json")), "응답 형식 오류")


class TestCollect(unittest.TestCase):
    def test_naver_without_keys_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "c.db")
            logs = []
            conf = {"enabled": {"news": True}, "timeout_sec": 5,
                    "news": {"min_interval_min": 14, "feeds": [{"name": "naver_news", "type": "naver", "queries": ["비트코인"]}]}}
            orig = news._env
            news._env = lambda k: None
            try:
                ok, failed, new = news.collect_news(conf, s, logs.append)
            finally:
                news._env = orig
            self.assertEqual((ok, failed, new), (0, 0, 0))
            self.assertTrue(any("키 없음" in x for x in logs))
            s.close()


if __name__ == "__main__":
    unittest.main()
