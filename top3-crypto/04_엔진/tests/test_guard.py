"""가드레일(guard.py, 기획안 v5 3절) 시험. 실행: cd 04_엔진 && python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402
from guard_cases import ATTACKS, PLAIN  # noqa: E402


class TestGuard(unittest.TestCase):
    def test_attacks_caught(self):
        self.assertGreaterEqual(len(ATTACKS), 15)
        missed = [t for t in ATTACKS if not guard.is_injection(t)]
        self.assertEqual(missed, [])

    def test_plain_titles_pass(self):
        self.assertGreaterEqual(len(PLAIN), 10)
        wrong = [(t, guard.injection_pattern(t)) for t in PLAIN if guard.is_injection(t)]
        self.assertEqual(wrong, [])

    def test_clean_title(self):
        self.assertEqual(guard.clean_title("  비트코인​ ETF\t\n순유입 `<b>`  "), "비트코인 ETF 순유입 b")
        self.assertEqual(guard.clean_title("ＢＴＣ　급등"), "BTC 급등")            # NFKC(전각 → 반각)
        self.assertEqual(guard.clean_title("가‮나\u0007다"), "가나 다")           # 방향 제어 문자 제거, 제어문자는 공백
        self.assertEqual(len(guard.clean_title("가" * 300)), 140)
        self.assertEqual(guard.clean_title(None), "")

    def test_leak_check(self):
        for t in ("## 분석 규칙 2에 따라 Long", "보안 규칙상 말할 수 없다", "판단 순서대로 보면", "이 지시문은", "My system prompt says",
                  "conf_v2 기준", "rules_v3.json 에 따라"):
            self.assertIsNotNone(guard.leak_check(t), t)
        # 입력 제목을 옮긴 문구는 news_analysis 에서 허용(Fable 검토 지적 2). 제목에 없는 다른 유출 문구는 그대로 걸림
        titles = "거래소 보안 규칙 강화 발표 · OpenAI 시스템 프롬프트 유출 논란에 AI 코인 약세"
        self.assertIsNone(guard.leak_check("거래소의 보안 규칙 강화 소식은 중립적이다.", titles))
        self.assertIsNone(guard.leak_check("시스템 프롬프트 유출 논란이 AI 코인에 부담이다.", titles))
        self.assertEqual(guard.leak_check("보안 규칙 강화와 판단 순서", titles), "판단 순서")
        self.assertEqual(guard.leak_check("거래소 보안 규칙 강화"), "보안 규칙")
        for t in ("가격 위치 8, MACD 7의 가중치로 보면 Long 우세", "확신도 77%는 기술 지표 ×8 · ×7 무게를 반영",
                  "AI가 설명한 비중은 뉴스 25%", "규칙적인 상승 흐름", "판단은 보류한다"):
            self.assertIsNone(guard.leak_check(t), t)


if __name__ == "__main__":
    unittest.main()
