import unittest

from _common import temp_db
from alfredo.ledger import BOOKS, Ledger, LedgerError
from alfredo.prices import FixedPriceSource, Top3DbPriceSource


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.path, self._tmp = temp_db()
        self.led = Ledger(self.path, fee_rate=0.001, slippage_rate=0.0)

    def tearDown(self):
        self.led.close()
        self._tmp.cleanup()

    def test_deposit_buy_sell_pnl(self):
        self.led.deposit("experiment", 1_000_000, bench_price=100_000_000)
        self.assertEqual(self.led.cash("experiment"), 1_000_000)
        # 매수: 10개 × 50,000 = 500,000, 수수료 500 → 평균단가 50,050
        self.led.buy("experiment", "XRP", 10, 50_000)
        pos = self.led.position("experiment", "XRP")
        self.assertAlmostEqual(pos.qty, 10)
        self.assertAlmostEqual(pos.avg_cost, 50_050)
        self.assertAlmostEqual(self.led.cash("experiment"), 499_500)
        # 추가 매수: 평균단가 갱신
        self.led.buy("experiment", "XRP", 10, 40_000)  # 400,000 + 400
        pos = self.led.position("experiment", "XRP")
        self.assertAlmostEqual(pos.avg_cost, (500_500 + 400_400) / 20)
        # 매도 5개 @ 60,000: 대금 300,000, 수수료 300, 원가 5×45,045
        self.led.sell("experiment", "XRP", 5, 60_000)
        self.assertAlmostEqual(self.led.realized_pnl("experiment"), 300_000 - 300 - 5 * 45_045)
        self.assertAlmostEqual(self.led.position("experiment", "XRP").qty, 15)
        prices = FixedPriceSource({"XRP": 70_000}).get_prices(["XRP"])
        self.assertAlmostEqual(self.led.unrealized_pnl("experiment", prices), (70_000 - 45_045) * 15)
        self.assertAlmostEqual(self.led.total_value("experiment", prices), self.led.cash("experiment") + 15 * 70_000)

    def test_slippage_and_fee(self):
        led = Ledger(self.path, fee_rate=0.0, slippage_rate=0.01)
        led.deposit("experiment", 1_000)
        led.buy("experiment", "BTC", 1, 100)  # 체결 101
        self.assertAlmostEqual(led.cash("experiment"), 899)
        self.assertAlmostEqual(led.position("experiment", "BTC").avg_cost, 101)
        led.sell("experiment", "BTC", 1, 100)  # 체결 99
        self.assertAlmostEqual(led.realized_pnl("experiment"), -2)
        led.close()

    def test_books_are_separate(self):
        self.assertEqual(set(BOOKS), {"mirror", "experiment"})
        self.led.deposit("mirror", 100)
        self.assertEqual(self.led.cash("mirror"), 100)
        self.assertEqual(self.led.cash("experiment"), 0)
        with self.assertRaises(LedgerError):
            self.led.deposit("real", 1)

    def test_errors(self):
        with self.assertRaises(LedgerError):
            self.led.buy("experiment", "BTC", 1, 100)  # 현금 없음
        self.led.deposit("experiment", 100)
        with self.assertRaises(LedgerError):
            self.led.sell("experiment", "BTC", 1, 100)  # 보유 없음
        with self.assertRaises(LedgerError):
            self.led.withdraw("experiment", 1_000)
        with self.assertRaises(LedgerError):
            Ledger(self.path, fee_rate=-1)

    def test_snapshot(self):
        self.led.deposit("experiment", 1_000)
        self.led.buy("experiment", "ETH", 2, 100)
        sid = self.led.snapshot("experiment", {"ETH": 150}, ts="2026-10-01T00:00:00+00:00")
        rows = self.led.snapshots("experiment")
        self.assertEqual(rows[0]["id"], sid)
        self.assertAlmostEqual(rows[0]["total_value"], self.led.cash("experiment") + 300)

    def test_top3_source_disabled_without_env(self):
        src = Top3DbPriceSource(path="")
        self.assertFalse(src.available())


if __name__ == "__main__":
    unittest.main()
