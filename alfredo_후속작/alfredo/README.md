# 알프레도(Alfredo) 모의투자 엔진 v0

알프레도는 Top3 Crypto(팀 보드 BTC·ETH·XRP, 4시간 판정·채점)를 포함해 발전시키는 '충실한 투자 집사'다. 이 폴더는 그 엔진의 **v0 뼈대**(파이썬 표준 라이브러리만, python3)다. 개발 본격화는 Top3 제출(10-16) 뒤가 원칙이며, 지금은 설계·문서·뼈대까지만 한다.

## 목적과 경계 (호연 2026-10-07 결정)

- **모의투자까지만.** 자동 투자·실제 주문 코드가 없다. `buy`·`sell`은 sqlite 장부 안의 숫자만 바꾼다.
- **고객 계좌 등록 없음.** 거래소 API 키·마이데이터·스크래핑을 쓰지 않는다. 사용자가 보유 현황을 직접 입력(`mirror` 장부)하거나 가상 포트폴리오로 시작(`experiment` 장부)한다.
- 가격 소스는 모두 **읽기 전용**: 고정값(시험용), 업비트 공개 시세(키 없음), Top3 수집 DB(환경변수 `ALFREDO_TOP3_DB`가 있을 때만, `mode=ro`).
- 개인 맞춤 투자 권유를 약속하지 않는다. 규제는 조문 인용으로만 다루고 법률 판단은 하지 않는다.
- **AI 고지**(AI기본법 31조): 모든 보고 **머리**(제목 바로 아래, 첫 3줄 안)에 AI가 생성했음과 투자 권유가 아님을 붙인다(설계서 B4·rubric '첫 3줄' 검사와 일치)(`alfredo/__init__.py`의 `AI_NOTICE`).
- 페르소나 규칙: 불확실성 먼저(보고 §1), 틀리면 정정 기록(보고 §6), 과장 금지, 손실 때는 사실과 다음 행동(보고 §3), 최종 결정은 사용자.

## 구조

| 파일 | 역할 |
|---|---|
| `ledger.py` | 가상 장부(sqlite). 표 `holdings`·`trades`·`snapshots`·`principles`. `book` 열로 `mirror`(실보유 거울)와 `experiment`(실험)를 구분. 입금·출금·매수·매도, 평균단가(수수료 포함), 실현·미실현 손익, 수수료·슬리피지 파라미터 |
| `prices.py` | 가격 소스 인터페이스 `PriceSource` + `FixedPriceSource`(시험) + `UpbitPriceSource`(urllib, 실패 시 `PriceSourceError`) + `Top3DbPriceSource`(환경변수 없으면 비활성) |
| `principles.py` | `conf/principles_v0.json` 로드, 거래 기록을 재생해 거래마다 규칙 준수 판정. 이행률 = 준수 / 전체 판정 |
| `report.py` | 주간 보고 md: AI 고지(머리) → 불확실성 → 자산 → 손익 → 벤치마크(입금액을 BTC로만 들고 있었을 때) → 원칙 이행률 → 정정 기록 |
| `cli.py` | `init` `deposit` `buy` `sell` `snapshot` `report` `principles-check`. `--help`에 모의 전용임을 명시 |
| `conf/principles_v0.json` | 예시 규칙 3개: 단일 자산 비중 상한(40%), 손절선 아래 추가 매수 금지(−15%), 추가 매수 조건(평균단가 대비 −5% 이하). **코드 규칙 3개는 예시이고, 설계서 K1–K8 체크 항목은 P3(Top3 연결·원칙 이행률)에서 코드화한다** |
| `tests/` | 고정값 어댑터·임시 DB만 쓴다. 네트워크 호출 없음 |

## 사용법

저장소 루트에서 실행한다(패키지 상대 임포트).

```bash
cd <저장소>/alfredo
python3 -m alfredo.cli --help
python3 -m alfredo.cli --price BTC=100000000 init
python3 -m alfredo.cli --price BTC=100000000 deposit 1000000
python3 -m alfredo.cli buy XRP 100 3000
python3 -m alfredo.cli --price BTC=100000000 --price XRP=3300 snapshot
python3 -m alfredo.cli principles-check
python3 -m alfredo.cli --price BTC=100000000 --price XRP=3300 report --out data/alfredo/report_2026-10-07.md
```

- 공통 옵션: `--db`(기본 `data/alfredo/alfredo.db`, 환경변수 `ALFREDO_DATA`로 폴더 변경), `--book mirror|experiment`(기본 experiment), `--fee`(기본 0.05%), `--slippage`(**CLI 기본 0, 설계서 비용표 기본은 0.10%** — v0 뼈대라 다름, P2에서 `conf/costs.json`으로 통일), `--source fixed|upbit|top3`, `--price SYMBOL=가격`(fixed용), `--rules`.
- `deposit`은 그 시점 BTC 가격을 벤치마크 기준가로 함께 저장한다. 가격이 없으면 벤치마크 비교는 보고에 "미확인"으로 나온다.
- `--source upbit`은 네트워크를 쓴다. 실패하면 경고만 내고 가격 없는 자산은 평균단가로 평가한다.

## 시험

```bash
python3 -I -m unittest discover -s alfredo/tests
```

2026-10-07 기준 16개 통과(확인됨).

## 데이터 위치

개인 장부·스냅샷·보고는 모두 **`data/alfredo/`**(저장소 루트 기준, 절대경로 `<저장소>/alfredo/data/alfredo/`)에 둔다. 설계서·로드맵도 같은 경로를 쓴다(10-07 통일). 개인 보유 현황이 들어가므로 `.gitignore`에 `data/alfredo/`가 들어 있다(확인: `git check-ignore data/alfredo/x`).

## 다음 단계(제안, 결정은 호연)

- Q: `mirror` 장부에 실보유를 손으로 넣을 때의 입력 형식(CSV? CLI?)
- Q: 통화. 장부는 KRW 기준, Top3 DB는 USDT 종가라 환산 규칙이 필요하다.
- Top3 `judge.py`의 4시간 판정을 알프레도 보고에 어떻게 연결할지(읽기 전용 어댑터 뒤)
