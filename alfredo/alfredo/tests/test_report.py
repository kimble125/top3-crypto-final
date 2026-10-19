import os
import unittest
from datetime import datetime, timezone

from _common import temp_db
from alfredo import AI_NOTICE
from alfredo.cli import main
from alfredo.ledger import Ledger
from alfredo.prices import FixedPriceSource
from alfredo.principles import load_rules
from alfredo.report import benchmark_value, weekly_report


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.path, self._tmp = temp_db()
        self.led = Ledger(self.path, fee_rate=0.0)
        self.rules = load_rules()

    def tearDown(self):
        self.led.close()
        self._tmp.cleanup()

    def test_report_sections(self):
        self.led.deposit("experiment", 1_000_000, bench_price=100_000, ts="2026-09-20T00:00:00+00:00")
        self.led.buy("experiment", "ETH", 10, 10_000, ts="2026-09-21T00:00:00+00:00")
        self.led.snapshot("experiment", {"ETH": 10_000, "BTC": 100_000}, ts="2026-09-22T00:00:00+00:00")
        prices = FixedPriceSource({"ETH": 9_000, "BTC": 120_000}).get_prices(["ETH", "BTC"])
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        md = weekly_report(self.led, "experiment", prices, self.rules, now=now)
        for h in ("불확실한 것", "## 2. 자산", "## 3. 손익", "벤치마크", "원칙 이행률", "정정 기록"):
            self.assertIn(h, md)
        self.assertIn(AI_NOTICE, md)
        self.assertIn(AI_NOTICE, "\n".join(md.splitlines()[:3]))  # 고지는 첫 3줄 안(머리)
        self.assertIn("총 평가액: 990,000원", md)      # 900,000 현금 + 10×9,000
        self.assertIn("BTC 보유 가치: 1,200,000원", md)  # 10 BTC × 120,000
        self.assertIn("수익률: +20.0%", md)
        self.assertIn("손실이 있다", md)               # 미실현 -10,000
        self.assertIn("7일 전 스냅샷 대비: -10,000원", md)
        self.assertIn("이행률: 100%", md)

    def test_benchmark_unknown(self):
        self.led.deposit("experiment", 100)  # bench_price 없음
        val, note = benchmark_value(self.led, "experiment", 100.0)
        self.assertIsNone(val)
        self.assertIn("BTC 기준가 없음", note)
        val, note = benchmark_value(self.led, "experiment", None)
        self.assertIsNone(val)
        md = weekly_report(self.led, "experiment", {}, self.rules)
        self.assertIn("벤치마크(BTC 보유) 비교 미확인", md)

    def test_cli_flow_with_fixed_source(self):
        db = self.path + ".cli"
        base = ["--db", db, "--source", "fixed", "--price", "BTC=100000", "--price", "ETH=5000"]
        self.assertEqual(main(base + ["init"]), 0)
        self.assertEqual(main(base + ["deposit", "100000"]), 0)
        self.assertEqual(main(base + ["buy", "eth", "2", "5000"]), 0)
        self.assertEqual(main(base + ["sell", "ETH", "1", "6000"]), 0)
        self.assertEqual(main(base + ["sell", "ETH", "5", "6000"]), 1)  # 보유 부족
        self.assertEqual(main(base + ["snapshot"]), 0)
        self.assertEqual(main(base + ["principles-check"]), 0)
        out = os.path.join(self._tmp.name, "report.md")
        self.assertEqual(main(base + ["report", "--out", out]), 0)
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("실제 주문·계좌 연동 없음", text)
        self.assertIn(AI_NOTICE, "\n".join(text.splitlines()[:3]))

    def test_help_mentions_simulation(self):
        from alfredo.cli import build_parser
        h = build_parser().format_help()
        self.assertIn("모의", h)
        self.assertIn("실제 주문", h)


if __name__ == "__main__":
    unittest.main()
