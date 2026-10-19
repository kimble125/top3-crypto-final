"""가드레일(기획안 v5 3절, 멘토 10-13 1:01:20–1:04:22): 외부 글이 AI 입력으로 들어가는 길과 AI 출력의 유출 검사.

이 서비스에 외부 글이 들어오는 길은 뉴스(제목 · 언론사 이름)뿐이다.
- clean_title: 제목·언론사를 정리한다(NFKC, 제어문자 · 너비 없는 문자 · 방향 제어 문자 제거, 백틱 · 꺾쇠 제거, 공백 정리, 140자).
- is_injection: 지시형 문장(이전 지시 무시, 시스템 프롬프트, 너는 이제 … 등)이 든 제목인지. 걸린 제목은 AI 입력에서 뺀다.
  평범한 금융 · AI 제목('무시할 수 없는 매수세', '규칙 변경', '시스템 점검', 'act as a hedge')이 걸리지 않게 좁게 잡는다.
- leak_check: AI 글 칸에 프롬프트 구조 문구(지시문 제목 · 판단 순서 · 버전 이름)가 나오면 실패. 화면에 공개하는 가중치(8:7:6:5 등)는
  보지 않는다(공개 정보이고, 넣으면 오탐으로 분석이 실패함).
모든 공격을 막는다는 뜻이 아니다. 시험 표본의 결과는 guard_demo.py 로 낸다.
"""
from __future__ import annotations

import re
import unicodedata

MAX_LEN = 140
_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")   # 너비 없는 문자 · 방향 제어
_CONTROL = re.compile("[\u0000-\u001f\u007f-\u009f]")
_SPACES = re.compile(r"\s+")


def _normal(s) -> str:
    t = unicodedata.normalize("NFKC", "" if s is None else str(s))
    t = _INVISIBLE.sub("", t)                 # 'ig​nore' 처럼 낱말을 쪼갠 것은 붙여서 본다
    t = _CONTROL.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


def clean_title(s) -> str:
    """뉴스 제목 · 언론사 이름 정리(AI 입력용)."""
    t = _normal(s).replace("`", "").replace("<", "").replace(">", "")
    return _SPACES.sub(" ", t).strip()[:MAX_LEN]


_KO_VERB_ASK = r"(?:줘|주세요|주십시오|라|해라|하라|하시오|하세요|해|봐)"
INJECTION = [(name, re.compile(p, re.IGNORECASE)) for name, p in (
    ("이전 지시 무시", r"(이전|앞선|앞의|위의?|기존|모든|지금까지의?)\s*(지시|명령|지침|규칙|내용|대화)\S{0,2}\s*(모두\s*|전부\s*|다\s*)?(무시|잊)"),
    ("지시 무시", r"(지시|명령|지침)\S{0,3}\s*(모두\s*|전부\s*|다\s*)?무시\s*(하|해)"),
    ("시스템 프롬프트", r"시스템\s*프롬프트"),
    ("프롬프트 요구", r"프롬프트\S{0,2}\s*(알려|출력|보여|공개|말해|노출|유출)"),
    ("규칙 요구", r"(규칙|지침|지시문|설정)\S{0,2}\s*(?:(출력|노출|유출)|(알려|보여|말해)\s*" + _KO_VERB_ASK + ")"),
    ("역할 바꾸기", r"(너는|넌)\s*(이제|지금부터|앞으로)|지금부터\s*(너는|넌)"),
    ("답 강요", r"(이)?라고\s*(답해|답하라|대답해|대답하라|써라|출력해|출력하라)(?![가-힣])"),
    ("개발자 모드", r"개발자\s*모드|developer\s+mode"),
    ("탈옥", r"탈옥|jailbreak"),
    ("ignore instructions", r"\b(ignore|disregard|forget|override)\s+(?:(?:all|any|the|your|my|of|these)\s+)*"
                            r"(previous|prior|above|earlier|preceding|existing|system|original)\s+(instructions?|prompts?|rules|directions|messages?)\b"),
    ("system prompt", r"\bsystem\s+prompt\b"),
    ("reveal prompt", r"\b(reveal|print|show|output|repeat|leak|dump|tell)\s+(me\s+)?(your|the)\s+(system\s+|hidden\s+|original\s+)?(prompt|instructions|rules)\b"),
    ("you are now", r"\byou\s+are\s+now\s+(an?\s+|the\s+|in\s+)?(ai|assistant|chatbot|dan|gpt|chatgpt|claude|developer|unrestricted|jailbroken|evil|free)\b"),
    ("act as", r"\bact\s+as\s+(an?\s+)?(ai|assistant|chatbot|gpt|chatgpt|unrestricted|jailbroken|system|developer)\b|\bpretend\s+(to\s+be|you\s+are)\b"),
    ("do anything now", r"\bdo\s+anything\s+now\b"),
    ("new instructions", r"\bnew\s+(instructions?|rules?)\s*:"),
    ("역할 태그", r"<\|?\s*/?\s*(system|assistant|user|im_start|im_end)\s*\|?>"),
)]


def injection_pattern(s) -> str | None:
    """걸린 패턴 이름(없으면 None). 꺾쇠 태그도 보도록 정리 전 글(NFKC · 너비 없는 문자 제거)로 본다."""
    t = _normal(s)
    for name, rx in INJECTION:
        if rx.search(t):
            return name
    return None


def is_injection(s) -> bool:
    return injection_pattern(s) is not None


LEAK = [re.compile(p, re.IGNORECASE) for p in (
    r"##\s*분석\s*규칙", r"보안\s*규칙", r"판단\s*순서", r"이\s*지시문", r"system\s+prompt", r"시스템\s*프롬프트",
    r"conf_v\d", r"rules_v\d", r"ai_analysis_v\d", r"##\s*(역할|출력\s*구조|기사\s*표지|항목별\s*비중|입력\s*\(JSON\))",
)]


def leak_check(text, allow_from=None) -> str | None:
    """프롬프트 구조 문구가 나오면 그 문구, 없으면 None. allow_from(입력 뉴스 제목들)에도 같은 문구가 있으면 그 문구는
    제목을 옮긴 것으로 보고 넘어간다(news_analysis 에서만 씀. 10-14 Fable 검토 지적 2: "거래소 보안 규칙 강화" 같은 제목)."""
    t = _normal(text)
    src = _normal(allow_from) if allow_from else ""
    for rx in LEAK:
        m = rx.search(t)
        if m and not (src and rx.search(src)):
            return m.group(0)
    return None
