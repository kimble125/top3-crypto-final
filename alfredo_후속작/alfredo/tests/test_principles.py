import unittest

from _common import temp_db
from alfredo.ledger import Ledger
from alfredo.principles import check_ledger, compliance_rate, load_rules


class PrinciplesTest(unittest.TestCase):
    def setUp(self):
        self.path, self._tmp = temp_db()
        self.led = Ledger(self.path, fee_rate=0.0)
        self.rules = load_rules()

    def tearDown(self):
        self.led.close()
        self._tmp.cleanup()

    def test_rules_file(self):
        ids = [r["id"] for r in self.rules["rules"]]
        self.assertEqual(ids, ["max_weight", "stop_loss", "add_buy"])

    def test_no_trades_no_rate(self):
        self.assertIsNone(compliance_rate([]))
        js, rate = check_ledger(self.led, "experiment", self.rules)
        self.assertEqual(js, [])
        self.assertIsNone(rate)

    def test_judgements(self):
        self.led.deposit("experiment", 1_000_000)
        # 1) 첫 매수 30% → max_weight 준수. 손절·추가매수 규칙은 해당 없음
        t1 = self.led.buy("experiment", "BTC", 3, 100_000)
        # 2) 추가 매수: 평균단가 100,000 대비 -10% → add_buy 준수(5% 이상), stop_loss 준수(15% 미만).
        #    매수 후 비중 = 6×90,000 / (460,000 + 540,000) = 54% → max_weight 위반
        t2 = self.led.buy("experiment", "BTC", 3, 90_000)
        # 3) 매도는 판정 대상 아님
        self.led.sell("experiment", "BTC", 6, 95_000)
        # 4) 새 자산 첫 매수, 비중 작음 → max_weight 준수만
        t4 = self.led.buy("experiment", "ETH", 1, 10_000)
        # 5) ETH 추가 매수 -20% → stop_loss 위반, add_buy 준수, max_weight 준수
        t5 = self.led.buy("experiment", "ETH", 1, 8_000)
        js, rate = check_ledger(self.led, "experiment", self.rules)
        by = {(j.trade_id, j.rule_id): j.ok for j in js}
        self.assertEqual(by[(t1, "max_weight")], True)
        self.assertNotIn((t1, "stop_loss"), by)
        self.assertEqual(by[(t2, "max_weight")], False)
        self.assertEqual(by[(t2, "stop_loss")], True)
        self.assertEqual(by[(t2, "add_buy")], True)
        self.assertEqual(by[(t4, "max_weight")], True)
        self.assertEqual(by[(t5, "stop_loss")], False)
        self.assertEqual(by[(t5, "add_buy")], True)
        self.assertEqual(len(js), 8)
        self.assertAlmostEqual(rate, 6 / 8)
        # DB에 기록됨, 재실행해도 중복 없음
        self.assertEqual(len(self.led.principle_rows("experiment")), 8)
        check_ledger(self.led, "experiment", self.rules)
        self.assertEqual(len(self.led.principle_rows("experiment")), 8)

    def test_add_buy_violation(self):
        self.led.deposit("experiment", 1_000_000)
        self.led.buy("experiment", "XRP", 10, 1_000)
        t = self.led.buy("experiment", "XRP", 10, 990)  # -1%: 추가 매수 조건(5%) 미달
        js, _ = check_ledger(self.led, "experiment", self.rules, record=False)
        self.assertFalse({(j.trade_id, j.rule_id): j.ok for j in js}[(t, "add_buy")])


if __name__ == "__main__":
    unittest.main()
