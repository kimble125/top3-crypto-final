# Top 3 데이터 수집기

바이낸스 현물 캔들·공포탐욕지수·뉴스 헤드라인을 15분마다 받아 `data/raw/market.db`(SQLite)에 쌓는 모듈입니다. 확신도 계산 재료는 캔들뿐이고, 공포탐욕지수와 뉴스는 해설·표시용 보조 자료입니다(2026-10-02 2차 회의 D1·D2, 기획서 ver3).

- API 키: 네이버 뉴스 검색만 필요(`.env`의 `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`). 나머지는 공개 엔드포인트
- 의존성: 수집기는 Python 3 표준 라이브러리만. 실행 스크립트는 엔진(pandas) 때문에 Python 3.14 framework 경로를 우선 사용
- 수집 대상·주기 변경은 코드가 아니라 `conf/collectors.json`만 고칩니다

## 1. 지금 켜져 있는 수집 (2026-10-12 `conf/collectors.json` 기준)

| 항목 | 내용 | 보유 범위 (10-06 DB 기준) |
|---|---|---|
| 바이낸스 현물 캔들 (`candles_binance`) | BTC·ETH·XRP USDT, **15m·1h·4h**. 미완성 봉은 저장하지 않음. 지표 시간대: VPCI 15m, Stochastic·StochRSI 1h, MACD 4h | BTC·ETH 2017-08-17부터, XRP 2018-05-04부터. 15m 각 319,863 / 319,863 / 295,063봉 |
| 공포탐욕지수 (`fear_greed`) | alternative.me. 하루 1회 UTC 00:00 갱신이라 그날 값이 있으면 호출하지 않음. 화면에 표시할 때 출처(alternative.me) 표기 필수 | 2018-02-01부터 3,166일 |
| 뉴스 헤드라인 (`news`) | `src/news.py`. 제목·링크·발행 시각·언론사(publisher)만 저장. 공식 API만 상시 사용: **네이버 뉴스 검색 API**(14분 간격, 질의 비트코인·이더리움·리플 XRP), **GDELT DOC 2.0**(30분 간격, 영문). 매체 RSS 6곳과 Google 뉴스 RSS는 약관 제한으로 꺼 둠(근거 `08_참고자료/기획서ver3_공식근거_2026-10-03.md` Q8) | 네이버 729건(10-03부터). GDELT는 이 맥에서 HTTP 429가 이어져 아직 0건(실패해도 수집기는 계속 돌고 30분 뒤 다시 시도) |

**10-12에 다시 켠 것(호연, 정미님 6대 분류 AI 분석 5절 재료)**: `binance_window`(바이낸스 선물 30일 창: OI·롱숏·테이커, 켜지면 첫 실행에서 최근 약 30일을 다시 받아 10-03 뒤 공백이 메워짐)와 `candles_coinbase`(코인베이스 BTC·ETH·XRP-USD 4h·1d, 코인베이스 프리미엄 = (코인베이스 종가 − 바이낸스 종가) ÷ 바이낸스 종가). AI 분석 입력으로만 쓰고 트리거 조건·확신도에는 넣지 않습니다.

뉴스 자동 수집은 2026-10-03부터 켜져 있습니다. `--news-once`를 주면 꺼 둔 RSS 출처까지 모두 1회 받습니다(출처 비교용, 10-02에 1회 실행한 기록이 DB에 있음).

## 2. 꺼 둔 수집 (데이터 보존)

2026-10-03 05:00 KST 이후 아래 항목은 `conf/collectors.json`의 `enabled`가 `false`입니다(`binance_window`·`candles_coinbase`는 10-12에 다시 켬, 위 1절). 코드와 그때까지 쌓인 데이터는 그대로 두었고, 백필 옵션을 주면 꺼져 있어도 실행됩니다.

| 설정 키 | 내용 | 쌓인 데이터 (마지막 2026-10-02) |
|---|---|---|
| `binance_window` | 바이낸스 선물 30일 창: OI, 전체 계정·상위 포지션·상위 계정 롱숏 비율, 테이커 매수/매도. 엔드포인트가 과거 약 30일만 반환해 9-22부터 적립했음 | `series` 표, 4h 747건·1h 2,250건/지표 |
| `bybit_oi` | 바이비트 OI 4h·1h | BTC 2020-07-20부터, ETH 2020-10-21부터, XRP 2021-05-13부터 |
| `funding` | 바이낸스 펀딩비 (`funding_rate`, period=`event`) | BTC 2019-09-10부터 등 22,629건 |
| `candles_upbit` | 업비트 KRW-BTC·ETH·XRP 4h·1d | 2017-09-25부터 |
| `candles_coinbase` | 코인베이스 BTC·ETH·XRP-USD 4h·1d | BTC 2015-01-08부터 |
| (바이낸스 1d) | `candles.binance.periods`에서 1d 제거 | 2017-08-17부터 2026-10-01까지 |

변경 직전 DB 사본: `data/raw/market_backup_2026-10-03.db`. 그 뒤로는 `scripts/guard.sh`가 하루 1회 `$TOP3_BACKUP_DIR`(기본 `$HOME/top3-backups`)에 백업합니다(저장소 밖).

설계 주의(9-22 교훈): `series` 표의 기본키가 `(source, symbol, metric, period, ts)`라 **서로 다른 엔드포인트는 반드시 다른 metric 이름**을 써야 합니다. 롱숏 비율 3종이 같은 이름을 써서 덮어쓰던 것을 접두사(`global_acc_`·`top_pos_`·`top_acc_`)로 분리했습니다.

## 3. 사용법

```bash
cd 02_데이터수집        # 저장소 루트에서

python3 src/collect.py            # 정기 수집 1회 (켜진 항목만)
python3 src/collect.py --status   # 지표·캔들·뉴스 적재 현황만 출력
python3 src/collect.py --news-once          # 꺼 둔 RSS까지 모든 뉴스 출처 1회 수집
python3 src/collect.py --candles-backfill   # 캔들 3거래소 + 공포탐욕 전체 이력 재수집 (9-28·10-03 완료, 약 6분)
python3 src/collect.py --funding-backfill   # 펀딩비 전체 이력 (꺼져 있어도 실행)
python3 src/collect.py --bybit-oi-backfill  # 바이비트 OI 전체 이력 (꺼져 있어도 실행)
python3 -m unittest discover -s tests       # 뉴스 모듈 시험
```

`scripts/run_collect.sh`가 정기 실행의 진입점입니다. 수집이 끝나면 같은 인터프리터로 `04_엔진/run_cycle.py`를 부르고(`04_엔진/conf/engine.json`의 `cycle_enabled`가 true일 때만 계산), 로그가 5MB를 넘으면 뒤 2,000줄만 남깁니다.

## 4. 저장 구조

`data/raw/market.db` (SQLite, WAL 모드). 표 정의는 `src/store.py`.

```sql
CREATE TABLE series (        -- 선물·OI·펀딩비·공포탐욕 (지표별 시계열)
    source TEXT, symbol TEXT, metric TEXT, period TEXT,
    ts INTEGER,              -- 관측 시각 (epoch ms, UTC)
    value REAL,
    collected_at INTEGER,    -- 우리가 받아온 시각
    PRIMARY KEY (source, symbol, metric, period, ts)
);
CREATE TABLE candles (       -- OHLCV
    source TEXT, symbol TEXT, period TEXT, ts INTEGER,   -- 봉 시작 시각
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, quote_volume REAL,                      -- 거래대금은 코인베이스만 NULL
    collected_at INTEGER,
    PRIMARY KEY (source, symbol, period, ts)
);
CREATE TABLE news (...);     -- source, lang, title, url, published_at, symbols, fetched_at, publisher(10-03 추가, 기존 DB 자동 보강)
CREATE TABLE run_log (...);  -- 실행 이력: 성공/실패 호출 수, 신규 행 수
CREATE TABLE kv (...);       -- 출처별 마지막 호출 시각 등
-- reports, signals, forward_track 표는 엔진(04_엔진)이 씀
```

설계 원칙 두 가지.

1. **멱등.** 같은 관측은 두 번 저장되지 않습니다. 캔들은 저장된 마지막 봉 다음부터 이어 받고, 미완성 봉은 저장하지 않으므로 나중에 값이 바뀌는 행이 없습니다. 몇 번 걸러도 다음 실행이 빈 구간을 이어 받습니다.
2. **`collected_at`을 남깁니다.** "그 값을 언제 알았는가"가 point-in-time 감사의 근거입니다.

봉 누락: 수집기 때문에 중간이 비지는 않습니다. 과거의 빈 구간(15분봉 BTC 33구간 565봉, 마지막 2023-03-24)은 거래소 점검 등 실제 공백이라 다시 받아도 채워지지 않습니다. 엔진은 계산 구간 안에 빈 봉이 있으면 그 시각을 "데이터 부족"으로 처리합니다.

읽기 예시:

```python
import sqlite3, pandas as pd
con = sqlite3.connect("data/raw/market.db")
df = pd.read_sql("SELECT ts, close FROM candles WHERE source='binance' AND symbol='BTCUSDT' AND period='4h' ORDER BY ts", con)
df["dt"] = pd.to_datetime(df.ts, unit="ms", utc=True)
```

## 5. 자동 실행 (macOS launchd)

Finder에서 `scripts/install_launchd.command`를 더블클릭하면 라벨 `com.topo3.market-collector`로 등록되고 즉시 1회 실행됩니다. 주기는 **매시 01·16·31·46분**(15분봉 마감 1분 뒤). 맥이 잠들어 있던 시각은 깨어난 뒤 1회 따라잡습니다. 폴더를 옮겼으면 다시 더블클릭해 경로를 갱신합니다.

- 해제: `scripts/uninstall_launchd.command` 더블클릭. 터미널에서는 `bash scripts/install_launchd.command`
- "확인되지 않은 개발자" 경고가 뜨면 파일을 우클릭 → 열기
- 등록 확인: `launchctl list | grep topo3`. 같이 도는 다른 라벨: `com.topo3.guard`(매시 10·40분 감시·백업), `com.topo3.board-api`, `com.topo3.snapshot-deploy`(매시 7분, 03_백엔드)
- 라벨 `com.topo3.collector`는 이 맥에서 내용과 무관하게 `launchctl bootstrap`이 `Input/output error`를 냈습니다(9-22). 같은 오류가 나면 두 스크립트의 `LABEL`을 다른 이름으로 바꿉니다

`scripts/guard.sh`: 마지막 수집이 40분 넘게 없으면 맥 알림(1시간에 한 번, 외부 전송 없음), 마지막 백업이 20시간보다 오래됐으면 DB 백업(최근 3개 보관).

## 6. 상태 점검

```bash
python3 src/collect.py --status
grep -n "=== 완료" logs/collector.log | tail -5     # 실행별 완료 줄 (호출 성공/실패/신규 행)
grep -n "FAIL\|ERROR" logs/collector.log | tail -10
sqlite3 -readonly data/raw/market.db "SELECT * FROM run_log ORDER BY run_id DESC LIMIT 5;"
```

로그가 끝까지 돌았는지는 `=== 완료: 호출 성공 … ===` 줄로 확인합니다. 한 실행이 수집 상세 + `--status` 출력 + 엔진 출력으로 수십 줄이라 `tail -25`로는 완료 줄이 잘려 보이지 않을 수 있습니다. 실패 1건은 대개 GDELT 429입니다(1절 참고).

## 7. 아직 안 하는 것 (의도적)

| 항목 | 이유 |
|---|---|
| ETF 순유입 | 유료 데이터·미국 ETF 없음(2차 회의) |
| 환율(USD/KRW)·김치 프리미엄 | 업비트 수집을 끄면서 보류 |
| 매체 RSS 상시 수집 | 약관 제한(Q8). `--news-once`로 비교만 |

## 8. 주의

- 바이낸스 API는 IP 가중치 한도가 있습니다. 요청 간 0.25초(`request_sleep_sec`)를 쉽니다. 심볼·주기를 늘리면 값을 올리세요. GDELT는 5초에 1회 제한이라 30분 간격으로만 호출합니다.
- 거래소 API 약관의 재배포 조항은 미확인입니다. 팀 내부 BI용이며 외부 서비스로 내보내지 않습니다.
- `data/`·`logs/`·`.env`는 git에 올리지 않습니다(`.gitignore` 포함). 비밀값은 환경변수 이름만 문서에 씁니다.
- 수집 가능한 API·지표 조사 목록: `수집가능_API_지표_목록_2026-10-01.md`
