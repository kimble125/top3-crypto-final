# 03_백엔드 — 보드 API(FastAPI) + 화면 서빙 + 운영 스크립트

수집기(`02_데이터수집`)와 엔진(`04_엔진`)이 채운 SQLite(`02_데이터수집/data/raw/market.db`)를 **읽기 전용**(`mode=ro`, 잠금 대기 30초)으로 열어 보드 화면·스냅숏 배포가 쓰는 JSON을 내려주고, 같은 서버가 `05_프론트/app`을 `/`에서 정적 파일로 내려준다. 쓰기 엔드포인트는 없다(쓰기는 수집기·엔진 담당). 기준: 2026-10-07 코드.

## 파일

| 경로 | 무엇 |
|---|---|
| `app/main.py` | FastAPI 앱. DB 연결, `/health`, 1주차 데이터 API(기본 꺼짐), `board.router` 연결, `05_프론트/app` 마운트 |
| `app/board.py` | 기획서 ver3 보드 API 7개. 엔진이 쓴 `analyses`·`outcomes`·`explanations`·`rules_versions` 표(그 밖에 `ai_reports`·`news`·`candles`·`series`·`discord_log`·`run_log`·`kv` 등)와 `04_엔진/reports/`·`conf/`를 읽어 화면용으로 묶는다. 지표·채점 계산은 없고, 성적(`track`)은 `outcomes`의 `hit`를 SQL `SUM`으로 집계만 한다(`small_sample` 플래그 포함) |
| `scripts/run_api.sh` | 개발용 실행(처음이면 `.venv` 생성·설치, `--reload`, `PORT` 기본 8765) |
| `scripts/install_board_service.command` / `uninstall_board_service.command` | launchd `com.topo3.board-api` 등록·해제(더블클릭) |
| `scripts/export_snapshot.py` | 로컬 서버 응답을 `05_프론트/dist/`에 정적 파일로 저장(Vercel 배포본) |
| `scripts/deploy_vercel.sh` | 스냅숏 만들고 Vercel에 배포. 바뀐 것이 있을 때만 |
| `scripts/install_snapshot_deploy.command` / `uninstall_snapshot_deploy.command` | launchd `com.topo3.snapshot-deploy` 등록·해제 |
| `tests/test_api.py` | API 시험 6개(아래) |
| `requirements.txt` | `fastapi==0.141.1`, `uvicorn[standard]==0.54.0`. 확인 환경 Python 3.14.5(`.venv`) |
| `logs/` | launchd 표준 출력·오류, `snapshot-deploy.sig`, `snapshot-deploy.status.json`. git 제외 |

## 로컬 실행

```bash
cd 03_백엔드
bash scripts/run_api.sh                                   # http://127.0.0.1:8765/  (보드 화면)
TOP3_API_DOCS=1 ./.venv/bin/uvicorn app.main:app --port 8765    # /docs·/redoc·/openapi.json 켜서 볼 때
TOP3_LEGACY_API=1 ./.venv/bin/uvicorn app.main:app --port 8765  # 1주차 데이터 API(/api/series 등) 켜서 볼 때
```

환경변수(값은 쓰지 않고 이름만): `TOPO3_DB` SQLite 경로(기본 `../02_데이터수집/data/raw/market.db`) · `PORT` run_api.sh 포트(기본 8765) · `TOP3_API_DOCS=1` 자동 문서 켬 · `TOP3_LEGACY_API=1` 1주차 API 켬.

자동 문서와 1주차 API는 기본으로 꺼져 있다. 보드가 Funnel·Vercel로 바깥에 열려 있어, 화면이 쓰지 않는 문은 닫아 둔다(10-03·10-04 검토 반영).

## 시험 (10개)

```bash
cd 03_백엔드 && .venv/bin/python -m unittest discover -s tests
```

API 코드를 고친 뒤, 보드 서버를 다시 띄우기 전과 커밋 전에 돌린다.

| 시험 | 무엇 |
|---|---|
| `RouteTest.test_routes_bound_to_expected_functions` | 보드 경로 7개가 의도한 함수에 붙어 있는지(데코레이터 아래 다른 함수가 끼어 422가 난 10-06 사고 방지) |
| `RouteTest.test_no_required_query_params` | 경로 변수 말고는 꼭 줘야 하는 인자가 없는지 |
| `IncludedTest.test_router_is_included_in_app` | `board.router`가 앱에 연결돼 있는지 |
| `ResponseTest.test_board_shape` | 실제 DB로 `/api/board` 키·종목 순서·24시간 고저 범위·`track.all`·`ai_report` |
| `ResponseTest.test_chart_and_analyses` | `/api/chart`에 `range`, `/api/analyses` 형식 |
| `ResponseTest.test_engine_and_study` | `/api/engine` dict, `/api/study` 비어 있지 않음 |
| `test_public_scope.py` | 공개 범위(10-13 결정 84-A): 로컬·공개 판정(머리글·Host·접속 IP), 공개 `/api/board`·`/api/chart`·`/api/engine`에 금지 키가 없는지, `/api/analyses`·`/api/replay` 빈 응답, 공개 공부 목록에 7장 없음·직접 열면 404, `export_snapshot.py`가 `X-Top3-Public` 머리글을 붙이는지. DB 대신 견본으로 돌고, TestClient(httpx2 필요) 대신 ASGI 앱을 직접 부른다 |

`ResponseTest` 3개는 DB가 없으면 건너뛴다.

## 엔드포인트

### 항상 켜짐 (`app/main.py`, `app/board.py`)

| 경로 | 무엇 | 비고 |
|---|---|---|
| `GET /health` | DB 존재 여부, `series` 행 수 | DB 경로는 응답에 넣지 않음 |
| `GET /api/board` | 홈 화면 한 장: 종목 3개(BTC·ETH·XRP)의 점수·확실한 신호·지표·시세·해설, 규칙 버전, 성적(`track`: 최근 확실한 신호·운영 전체), 뉴스, AI 심층 리포트(`ai_report`, 없으면 null) | `analyses` 표가 없으면 503 · 10-12부터 `v4`: 엔진이 15분마다 쓰는 `04_엔진/reports/trigger_board.json`(매매 트리거 성적·최근 목록·AI 게이트 기록·코인별 AI 분석·Core Condition)을 규칙 버전이 같을 때 그대로 넣음(`_trigger_board`) |
| `GET /api/analyses?symbol=&limit=&all_versions=` | 지난 분석 목록(운영 기록). 4시간 뒤 결과(`next_close`·`ret`·`hit`) 포함. 기본은 현재 규칙만, `all_versions=true`면 이전 규칙도 | `limit` 1–500, 기본 60 |
| `GET /api/replay` | `04_엔진/reports/replay_summary.json` 그대로 | 없으면 404 |
| `GET /api/engine` | 데이터 상태 탭: 수집기 마지막 실행·켜진 수집기, 엔진 마지막 실행·규칙 버전·운영 시작, 캔들 적재 범위(15m·1h·4h), 공포탐욕, 디스코드 마지막 전송, 뉴스 상태, 스냅숏 배포 상태, 채점 보류 수 | |
| `GET /api/study` | `01_운영/공부노트/NN_*.md` 목록(이름·제목) | |
| `GET /api/study/{name}` | 공부노트 한 편의 마크다운 | 이름 형식 `NN_….md`만, 폴더 밖 접근 거부 |
| `GET /api/chart/{symbol}?days=` | 엔진이 15분마다 쓰는 `04_엔진/reports/charts/<SYMBOL>.json`을 기간만 잘라 내려줌(가격·MACD·Stochastic·StochRSI·VPCI·이벤트) | `days` 1–7(기본 3), 종목은 `…USDT`만 |
| `GET /` | `05_프론트/app` 폴더 전체(index.html·app.js·chart.js·now15.js·config.js·style.css·img) | 라우트 뒤에 마운트 |

### 15분 확실한 신호 (2026-10-07)

새 경로는 없고 기존 응답에 키가 늘었다(옛 DB·저장본에는 `strong15` 표가 없을 수 있어 모두 없으면 null).

- `GET /api/board` `symbols[].now15`: `{dir(+1/−1/0), label(롱 확실/숏 확실/없음), kind, t_close, since_kst, since_hm, since_today, close}` — 카드의 "지금(15분 기준): 롱 확실 · HH:MM부터" 줄. 행이 없으면 `없음`에 시각 없음.
- `GET /api/board` `strong15`: `{last_run_kst, rows[종목별 n·called·hit·hit_pct·aux_called·aux_hit·aux_pct], recent[최근 바뀜 8건]}`.
- `GET /api/engine` `strong15`: `{last_run_kst, rows}`.
- 스냅숏(`scripts/export_snapshot.py`)은 `/api/board`를 그대로 쓰고 화면 파일 복사 목록에 `now15.js`가 들어 있어 배포본에도 반영. `scripts/deploy_vercel.sh` 서명에 `now15.dir`·`now15.t_close`가 들어가 15분 상태가 바뀌면 배포된다.
- 시험 `tests/test_api.py` `Strong15Test` 2개(임시 DB로 now15·strong15 블록, 배포 서명이 15분 상태를 보는지). API 시험 합계 8개.
- 화면: `05_프론트/app/now15.js`(글자·알림 키, node 시험 `05_프론트/tests/now15.test.js`), 설정 탭 "15분 확실한 신호 알림" 토글(기본 꺼짐, 이 기기 localStorage). 서버 쪽 디스코드 알림은 `04_엔진/conf/discord.json` `alerts.strong15`(기본 false).

### `TOP3_LEGACY_API=1`일 때만 (1주차 데이터 API, `app/main.py`)

`/api/status`, `/api/series`, `/api/candles`, `/api/snapshot`, `/api/fng`, `/api/reports`, `/api/signals`, `/api/track`. 화면은 쓰지 않는다. 선물·바이비트·업비트·코인베이스 값은 10-03부터 갱신되지 않는다(수집 중단, 데이터 보존). `reports`·`signals`·`forward_track` 표는 비어 있다.

## 운영 (launchd, 이 맥 기준)

`~/Library/LaunchAgents/`에 등록된 Top 3 작업 4개(2026-10-07 확인):

| 라벨 | 무엇 | 시각 | 등록 스크립트 |
|---|---|---|---|
| `com.topo3.board-api` | uvicorn 보드 서버 127.0.0.1:8765, 꺼지면 자동 재시작 | 항상 | `03_백엔드/scripts/install_board_service.command` |
| `com.topo3.snapshot-deploy` | `deploy_vercel.sh` | 매시 7분 | `03_백엔드/scripts/install_snapshot_deploy.command` |
| `com.topo3.market-collector` | 수집 + 엔진 사이클 | 매시 1·16·31·46분 | `02_데이터수집/scripts/install_launchd.command` |
| `com.topo3.guard` | `02_데이터수집/scripts/guard.sh` 감시·백업 | 매시 10·40분 | (plist 직접 등록, 2026-10-06) |

자주 쓰는 명령:

```bash
# 코드 바꾼 뒤 보드 서버 재시작(약 40초 걸릴 때 있음)
launchctl kickstart -k gui/$(id -u)/com.topo3.board-api
# 상태·로그
curl -s http://127.0.0.1:8765/health
tail -n 50 03_백엔드/logs/board-api.err.log
# 강제 배포(바뀐 것이 없어도)
FORCE=1 03_백엔드/scripts/deploy_vercel.sh
# 미리보기 주소로 배포(Vercel 로그인한 사람만 열림)
03_백엔드/scripts/deploy_vercel.sh --preview
```

### 바깥 공개: Tailscale Funnel + Vercel 스냅숏

- **Funnel**: 이 맥의 8765 중 `/api`만 Funnel 주소로 연다(`tailscale funnel status`로 확인, 2026-10-06부터 `/api` 한정). 전체를 다시 열려면 `tailscale funnel --bg 8765`. 자동 문서·1주차 API가 기본 꺼진 이유가 이것이다.
- **Vercel**(프로젝트 `top3-crypto`, 실제 주소 `https://top3-crypto.vercel.app`): `export_snapshot.py`가 로컬 서버에서 `/api/board`·`/api/engine`·`/api/replay`·`/api/analyses`(종목별·전체 × 현재 규칙·전체 규칙, limit 120)·`/api/chart/*`(1·3·7일)·`/api/study`·`/api/study/*`를 받아 `05_프론트/dist/data/`에 쓰고, 화면 파일·`config.js`·`vercel.json`·`meta.json`(저장 시각)을 함께 만든다. 시안(`05_프론트/시안/2026-10-06`)은 `/preview/`로 올라간다.
- **공개 범위**(10-13 결정 84-A, `app/public_scope.py`): 맥에서 직접 연 요청(프록시 머리글 없음, Host가 127.0.0.1·localhost·::1, 접속 IP가 루프백)만 전체 응답(`scope: "local"`)을 받는다. Funnel·Vercel을 거친 요청과 `X-Top3-Public` 머리글이 있는 요청은 공개 응답(`scope: "public"`)으로, 화이트리스트에 적은 것만 담는다: 확신도·AI 분석·뉴스·공포탐욕·Core Condition 충족 여부·트리거 기록(시각·코인·방향·진입가)·지표 그래프 선. 매매 조건(가중치·단계별 상태)과 채점(성적·과거 재현·4시간 분석 점수·AI 게이트 기록), 공부 7장은 맥의 검증 화면에서만 보인다. `export_snapshot.py`는 모든 요청에 `X-Top3-Public: 1`을 붙이고, 공개 응답이 아니면(서버가 옛 코드) 저장본을 만들지 않고 멈춘다. 범위를 바꾸려면 `public_scope.py`의 목록만 고친다.
- 배포된 화면은 같은 주소의 `/api`를 먼저 쓰고(`vercel.json` rewrites가 화면이 쓰는 경로만 Funnel로 넘김), 맥이 꺼져 있으면 `data/` 스냅숏을 보여 준다. 엔진이 내보내는 사이 새 분석을 쓰면 한 번 더 내보낸다.
- `deploy_vercel.sh`는 **바뀐 것이 있을 때만** 배포한다: 새 분석 시각·규칙 버전·확실한 신호, 또는 `05_프론트/app`·시안 파일의 해시(`logs/snapshot-deploy.sig`)가 달라졌거나 마지막 성공 배포가 3시간을 넘었을 때. 아니면 건너뛴다. `FORCE=1`로 무시. 결과는 `logs/snapshot-deploy.status.json`(마지막 성공·실패 시각·주소·오류)에 남고 `/api/engine`의 `snapshot_deploy`가 읽는다. Vercel 무료 한도 하루 100번 안.
- 로컬 `05_프론트/app`을 그대로 올리므로 **로컬 화면 수정은 최대 1시간 안에 공개된다**. 화면 작업은 복사본에서 하고 확인 뒤 옮긴다.
- Vercel 로그인은 이 맥의 CLI 로그인을 쓴다(토큰을 명령줄·파일에 넣지 않음). 토큰 갱신 중 실패하면 20초 뒤 한 번 더 시도한다. `dist/.vercelignore`로 `.env*`는 올리지 않는다.

### 감시·백업 (`02_데이터수집/scripts/guard.sh`)

매시 10·40분에 (1) 마지막 수집이 40분 넘게 멈췄으면 맥 알림(1시간에 한 번, 바깥으로 보내지 않음), (2) 마지막 백업이 20시간보다 오래됐으면 `sqlite3 .backup` → gzip으로 비공개 폴더 `DB백업/`에 저장하고 최근 3개만 남긴다(오래된 것은 휴지통).

## 규칙

- 대시보드·스냅숏은 이 API만 보고 그린다(DB 직접 접근 금지). 계산은 엔진이 끝낸 값을 그대로 쓴다.
- 쓰기 엔드포인트는 두지 않는다. 필요해지면 별도 인증을 붙인 뒤에.
- 응답에 비밀값·로컬 경로를 넣지 않는다. 바깥에서 쓰지 않는 문(자동 문서·1주차 API)은 환경변수로만 켠다.
- `logs/`·`.venv/`·`05_프론트/dist/`·`*.db`는 git 제외.
