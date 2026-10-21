# Top 3 Crypto · 코디세이 파이널 프로젝트 제출본

코인을 처음 시작하는 사람을 위한 AI 트렌드 분석 플랫폼입니다. 비트코인·이더리움·리플(XRP)의 확신도와 지표 그래프, AI 분석, 매매 트리거 기록을 한 화면에 보여 주고, 초보자용 공부 노트를 함께 둡니다.

- 팀: Top 3 (문수향 · 공정미 · 김호연) · 역할은 발표 자료 4쪽
- 이 저장소는 2026-10-21·22 평가용 제출본입니다. 정보 제공용이며 투자 권유가 아닙니다.

## 평가자 5분 안내

| 보려는 것 | 위치 |
|---|---|
| 실시간 화면 | https://top3-crypto.vercel.app |
| 시연 영상(약 2분 18초, 무음·자막) | [presentation/top3-crypto-demo.mp4](presentation/top3-crypto-demo.mp4) |
| 발표 자료 | [presentation/Top3_Crypto_발표_2026-10-21.pdf](presentation/Top3_Crypto_%EB%B0%9C%ED%91%9C_2026-10-21.pdf) |
| 보안·개인정보 설계(데이터 흐름도) | [SECURITY.md](SECURITY.md) |
| 이용약관 · 개인정보 처리방침 · AI 이용 고지 | [docs/legal/](docs/legal/) |
| 개발 과정(버전 V1–V5, 커밋 104개 요약) | [docs/development-history.md](docs/development-history.md) |
| 후속작 실시간 화면 | [http://127.0.0.1:8787/](http://127.0.0.1:8787/) (발표 컴퓨터에서 서버를 켠 동안만 열림) · [코드 폴더 alfredo_후속작/](alfredo_%ED%9B%84%EC%86%8D%EC%9E%91/) |

## 무엇이 동작하나

1. **확신도**: 기술 지표 4개(가격 위치·MACD 4시간·Stochastic 1시간·StochRSI 1시간)와 시장 자료 4개(미결제약정·코인베이스 프리미엄·공포탐욕지수·뉴스 방향)를 반씩 합쳐 우세한 쪽을 10–90%로 보여 줍니다. 숫자는 코드가 15분마다 계산하고, 계산식이 화면에 그대로 나옵니다.
2. **AI 분석**: 하루 2번(09·21시)과 기술 조건이 켜질 때 AI가 6개 항목(전략·확신·뉴스·공포탐욕·시장 흐름·기술 분석)으로 해설합니다. 뉴스는 기사마다 긍정·중립·부정과 중요도를 붙입니다.
3. **매매 트리거**: 4시간·1시간·15분 기술 조건과 AI 추세 방향이 모두 같을 때만 기록하고 팀 디스코드로 알립니다. 트리거의 시각·코인·방향·진입가는 공개 화면 설정 탭의 '성적 리포트' 표에 남고, 채점 결과(성공·실패)는 팀 로컬 화면에서만 봅니다.
4. **공부 노트**: 코인·지표·규제를 처음 배우는 사람용 노트(출처·확인 시각 포함). 공개본은 1–6장과 8장이고, 7장(우리 판정 규칙)은 팀 내부 장이라 본문을 뺐습니다.
5. **향후 발전 계획, 알프레도**: 같은 방법론을 주식·채권·금·달러로 넓힌 모의투자 데모(합성 가격)와, 화면의 확신도를 쉬운 말로 풀어 주는 AI 채팅.

## 폴더

```
top3-crypto/          Top 3 Crypto 제출용 공개 사본(운영본 V5_1014에서 비공개 자료를 빼고 보안 코드를 더함)
  02_데이터수집/      바이낸스·코인베이스·공포탐욕·뉴스 수집기(15분마다)
  03_백엔드/          읽기 전용 API(FastAPI), 공개 범위 거르기, 요청 지킴이, Vercel 배포 스크립트
  04_엔진/            지표·확신도·트리거 계산, AI 분석 호출과 검사
  05_프론트/          화면(HTML·JS, 빌드 없음)
  01_운영/공부노트/   공부 탭에 나오는 노트
alfredo_후속작/       향후 발전 계획 데모(모의투자 엔진 + 대시보드 + 채팅 서버)
presentation/         발표 자료, 시연 영상, 초기 기획서
docs/                 약관 3종, 개발 과정
```

## 실행

### 화면만 보기
설치 없이 https://top3-crypto.vercel.app 를 엽니다. 팀 맥이 꺼져 있으면 1시간마다 저장한 화면이 보입니다.

### Top 3 Crypto를 직접 돌리기 (macOS·Linux)
개발·시험 환경은 Python 3.14, Node.js 26입니다(더 낮은 버전은 확인하지 않음).
```bash
git clone https://github.com/kimble125/top3-crypto-final.git
cd top3-crypto-final/top3-crypto
python3 -m pip install numpy pandas                 # 엔진이 쓰는 라이브러리(수집기는 표준 라이브러리만)
python3 02_데이터수집/src/collect.py                 # 공개 시세·지수·뉴스를 SQLite(02_데이터수집/data/raw/)로 1회 수집
python3 04_엔진/run_cycle.py --force             # 지표·확신도 계산 1회(AI 분석은 Codex CLI 로그인이 있을 때만)
bash 03_백엔드/scripts/run_api.sh                 # 처음이면 가상환경을 만들고 http://127.0.0.1:8765/ 에서 화면을 냄(접속 기록 없음)
```
- 설정은 `04_엔진/conf/`에 있습니다. 공개용 사본이라 내부 메모를 지웠고 채점 기준은 예시 값입니다(지표 문턱·가중치 일부도 예시화하여 운영과 규칙 버전 해시가 다름).
- 네이버 뉴스를 받으려면 `top3-crypto/.env`에 `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`을 넣습니다(저장소에는 없음). 없으면 GDELT 뉴스만 받습니다.

### 시험
```bash
cd top3-crypto
(cd 04_엔진 && python3 -m unittest discover -s tests)        # 150개(1개 건너뜀: 비공개 참고자료)
(cd 03_백엔드 && python3 -m unittest discover -s tests)      # 36개(4개 건너뜀: 자료 DB 필요, fastapi 필요)
(cd 02_데이터수집 && python3 -m unittest discover -s tests)  # 8개
(cd 05_프론트 && node --test tests/*.test.js)                # 3개
cd ../alfredo_후속작
python3 -I -m unittest discover -s alfredo/tests             # 16개
python3 -I -m unittest discover -s mvp/tests                 # 31개
```

### 알프레도 데모
```bash
cd alfredo_후속작
python3 mvp/build_board.py           # 합성 가격으로 대시보드 만들기(바깥 호출 없음)
python3 -I mvp/chat_server.py        # http://127.0.0.1:8787/ (이 컴퓨터 안에서만 열림)
```
채팅은 Codex CLI(ChatGPT 로그인)가 있어야 답합니다. 없으면 `alfredo_후속작/mvp/dist/alfredo_mvp_board.html`을 브라우저로 열어 화면만 볼 수 있습니다.

## 이 저장소에 넣지 않은 것

- 팀 결정(2026-10-13, 공개 범위)에 따라: 매매 조건의 내부 메모와 채점 기준 값(이 사본은 예시 값), AI 프롬프트 원문(뼈대만 둠), 과거 재현·채점 보고서와 성적, 공부 7장 본문. 판정·채점의 계산 방식은 코드로 공개되어 있습니다.
- 자료 DB와 로그, 비밀값(`.env`), 운영 맥의 공개 주소, 팀 내부 회의록·참고 강의 자료.
- 개발 기록 전체(커밋 104개)는 팀의 비공개 원본 저장소에 있고, 요약은 [docs/development-history.md](docs/development-history.md)에 있습니다.

## 저작권과 출처

- 코드와 문서: © 2026 Top 3 팀. 열람·평가 목적으로 공개하며 오픈소스 라이선스를 주지 않습니다. 다시 쓰려면 Issues로 문의해 주세요.
- 글꼴 Pretendard(SIL Open Font License 1.1): 화면은 CDN, 알프레도는 글자 일부만 남긴 사본(`alfredo_후속작/mvp/fonts/OFL_Pretendard.txt`).
- 데이터 출처: Binance, Coinbase, alternative.me 공포탐욕지수, 네이버 뉴스 검색, [GDELT 프로젝트](https://www.gdeltproject.org/). 이들과 제휴 관계가 없습니다.
- 만든 방법: Claude Code·Codex·Aside 같은 AI 도구를 함께 썼습니다(발표 자료와 공부 노트에 표시).

## 제출본 정정 안내

- 발표 PDF는 발표 당시 원본 그대로입니다. 발표의 'AI 분석 하루 4회'는 기획 단계 값이고, 현재 구현은 하루 2번(오전 9시·오후 9시)과 기술 신호가 켜질 때 추가 분석입니다. 뉴스는 네이버 뉴스 검색과 GDELT에서 받되, 네이버 검색 API 약관에 따라 AI 분석에는 GDELT 기사만 넣습니다. 실시간 사이트 반영 기록은 SECURITY.md 9절을 확인해 주세요.
- 초기 기획서는 당시 계획을 보존한 자료이며, 현재 구현과 다른 부분(분석 주기·사용 모델 등)은 위 실행 안내를 기준으로 봐 주세요.
