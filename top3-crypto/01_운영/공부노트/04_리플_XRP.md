# 4장. 리플(XRP)은 어떻게 만들어졌나

조사: Aside 브라우저 에이전트(2026-10-03 07:50~08:10 KST, 공식·1차 출처 우선). 정리: 김호연. 각 사실의 출처 URL과 확인 시각은 본문 표와 끝의 출처 목록에 있습니다. 숫자는 확인 시각 기준이며 바뀔 수 있습니다. [추정]은 출처가 직접 말하지 않은 읽기이고, 미확인은 이번 조사에서 확인하지 못한 것입니다. 투자 권유가 아니며, 전망은 기관·연구자의 견해를 출처와 함께 옮긴 것입니다.

## 한 줄 요약
XRP Ledger(XRPL)는 2011~2012년에 개발자 3명이 "채굴 없는 비트코인"을 목표로 만든 공개 장부이고, XRP는 그 장부의 기본 코인입니다. Ripple은 그 직후 세워진 회사로, 창시자들에게서 XRP 800억 개를 받아 송금 사업에 써 왔습니다. 미국 SEC 소송은 2025-08-07에 양측이 항소를 거둬들이면서 끝났고, 2023년 1심 판단(기관 판매는 증권 판매, 거래소 익명 판매는 아님)과 2024년 최종 판결(금지명령, 벌금 약 1.25억 달러)이 그대로 남았습니다.

## 핵심 사실

| 항목 | 내용 | 출처 URL | 확인 시각(KST) |
|---|---|---|---|
| XRPL 개발자와 출시 | 2011년 David Schwartz, Jed McCaleb, Arthur Britto가 개발을 시작했고, XRPL은 2012년 6월 처음 출시됐다. | https://xrpl.org/about/history | 2026-10-03 07:53 |
| 회사의 시작 | Chris Larsen이 합류해 2012년 9월 NewCoin을 세웠고, 곧 OpenCoin으로 이름을 바꿨으며, 지금 이름은 Ripple이다. 설립 당시 Larsen은 CEO, McCaleb은 공동창업자 겸 CTO, Schwartz는 최고암호책임자, Britto는 자문이었다. | https://xrpl.org/about/history | 07:53 |
| Ripple Labs로 개명 | 2013년. 프로젝트(Ripple)와 회사(OpenCoin)를 헷갈려 하는 고객이 많아 회사를 Ripple Labs로 바꿨고, 나중에 줄여서 "Ripple"이 됐다. | https://xrpl.org/about/history | 07:53 |
| 사전 발행과 회사 몫 | 처음 만들 때 XRP는 1000억 개였고, Ripple이 XRP Ledger를 개발하는 조건으로 800억 개를 받았다. | https://xrpl.org/docs/introduction/what-is-xrp | 07:53 |
| 이름의 유래 | 원래 기술 전체 이름이 "Ripple"이었고, 코드 XRP는 "ripples"에 ISO 4217의 X 접두어(국가 통화가 아닌 것)를 붙인 것이다. "XRP" 상표는 2022년부터 XRPL Foundation(에스토니아 비영리)이 갖고 있다. | https://xrpl.org/docs/introduction/what-is-xrp | 07:53 |
| 에스크로(2017) | 10억 XRP짜리 계약 55개를 만들어 0~54개월째 매달 1일 하나씩 풀리게 했고, 쓰지 않은 양은 줄 맨 뒤에 다시 잠근다. 잠금 완료 공지는 2017-12-07. | https://ripple.com/insights/ripple-escrows-55-billion-xrp-for-supply-predictability/ ; 날짜: SEC 소장 229항 https://www.sec.gov/files/litigation/complaints/2020/comp-pr2020-338.pdf | 07:54 |
| Ripple 공식 마지막 보유량 | 2025-03-31 기준, Ripple이 보유한 XRP 4,562,433,147개, 에스크로 37,130,000,005개. Ripple은 이 분기 보고서를 2025년 2분기부터 중단했다. | https://ripple.com/insights/q1-2025-xrp-markets-report/ | 07:54 |
| 현재 에스크로 [3자 추정] | 2026-10-02 기준 약 309.8억 XRP(전체의 31.0%). 회사 발표가 아니라 장부를 집계한 제3자 사이트 값이다. 2026-10-01에 10억 XRP가 풀렸고 7억 XRP가 다시 잠겼다(Finbold 보도). | https://xrp-insights.com/xrp-radar ; https://finbold.com/ripple-locks-1-billion-worth-of-xrp-into-escrow/ | 07:54 |
| 합의 방식 | 채굴이 없다. 검증자들이 거래 목록을 주고받으며, 검증자 80%가 같은 거래 묶음에 동의하면 새 장부를 만들고, 이 과정에 4~6초가 걸린다. | https://xrpl.org/docs/introduction/what-is-the-xrp-ledger | 07:53 |
| UNL(신뢰 검증자 목록) | 서버마다 "서로 짜고 속이지 않을 것"이라 믿는 검증자 목록이 UNL이다. 목록끼리 겹치는 비율이 최악의 경우 90%는 돼야 장부가 갈라지지 않는다. 기본 설정은 XRPL Foundation 목록과 Ripple 목록 두 개를 쓰며, 둘은 보통 매우 비슷하거나 같다. | https://xrpl.org/docs/concepts/consensus-protocol/unl | 07:53 |
| 기본 UNL 규모 | XRPL Foundation이 공개한 목록(sequence 2026070302)에 검증자 35개. 공개 JSON을 내려받아 직접 센 값이다. | https://unl.xrplf.org/ | 07:55 |
| 수수료 | 표준 거래의 최소 비용은 10 drops이고, 수수료는 누구에게도 지급되지 않고 영구히 소각된다. 2025년 1분기에 수수료로 소각된 XRP는 500,691개(Ripple 보고서). | https://xrpl.org/docs/concepts/transactions/transaction-cost ; https://ripple.com/insights/q1-2025-xrp-markets-report/ | 07:54 |
| 설계 목적 | 개발자들이 "더 지속 가능하고 결제 전용인 디지털 자산"을 목표로 했다고 공식 역사 페이지에 적혀 있다. Ripple은 국경 간 결제에서 유동성 관리 용도로 XRP를 쓴다고 밝힌다. | https://xrpl.org/about/history | 07:53 |
| 실제 쓰임 (회사 주장) | Ripple 홈페이지: 결제 정산 3~5초, 커스터디 지갑 100만 개 이상. 결제·커스터디·RLUSD·프라임브로커리지·토큰화 사업. XRP가 결제에 실제로 얼마나 쓰이는지는 수치가 공개되지 않는다. | https://ripple.com/ | 07:55 |
| SEC 제소 | 2020-12-22 SEC가 Ripple과 Larsen, Garlinghouse를 13억 달러 넘는 미등록 증권 판매 혐의로 제소했다. 사건번호 1:20-cv-10832(S.D.N.Y.). | https://www.sec.gov/newsroom/press-releases/2020-338 | 07:54 |
| 2023 법원 판단 | 2023-07-13 Torres 판사 약식판결: 기관 투자자 대상 판매는 미등록 투자계약(증권) 판매로 증권법 5조 위반. 그 밖의 2차 판매는 위반이 아니라고 봤다. | https://www.nutter.com/assets/htmldocuments/SEC%20v%20Ripple%20Labs%202025.06.26.pdf (법원 문서 989호 사본) ; https://www.sec.gov/newsroom/speeches-statements/crenshaw-statement-ripple-050825 | 07:54 |
| 최종 판결 | 2024-08-07: 영구 금지명령과 민사 벌금 125,035,150달러. 양측 모두 항소(SEC 2024-10-02, Ripple 교차항소 2024-10-10). | 법원 문서 989호(위 URL) ; SEC 항소심 경과보고 https://storage.courtlistener.com/recap/gov.uscourts.ca2.c99a6526-19b6-430d-a15c-e0c1dd869735/gov.uscourts.ca2.c99a6526-19b6-430d-a15c-e0c1dd869735.63.0.pdf | 07:54 |
| 합의 시도와 기각 | 2025-05-08 합의서 제출(벌금 중 5000만 달러만 SEC에 내고 나머지는 Ripple에 반환, 금지명령 해제 요청). 2025-05-15 1차 기각(절차상 이유), 2025-06-26 2차 기각. 판사는 "예외적 사정에 근처도 가지 못했다"고 했다. | https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26306 ; 법원 문서 989호 | 07:54 |
| 소송 종결 | 2025-08-07 SEC 항소와 Ripple 교차항소를 함께 취하했고, 최종 판결(벌금 125,035,150달러와 금지명령)은 계속 효력을 갖는다. 항소법원(2nd Cir.)은 2025-08-22 취하를 승인하는 명령(mandate)을 냈다. | https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26369 ; https://storage.courtlistener.com/recap/gov.uscourts.ca2.f031d7d4-2abc-4ba5-88f9-d20482f024ea/gov.uscourts.ca2.f031d7d4-2abc-4ba5-88f9-d20482f024ea.45.0.pdf | 07:54 |
| 종결 후 1심 기록 | 최근 기록은 2025-11-10 명령(사건 당사자가 아닌 제3자의 증거 제출 요청 기각)이고, 마지막 제출일은 2025-11-12. 새 소송 절차는 보이지 않는다(CourtListener, 2026-07-09 갱신 기준). | https://www.courtlistener.com/docket/19857399/securities-and-exchange-commission-v-ripple-labs-inc/ | 07:54 |
| RLUSD | 달러에 1:1로 연동된 Ripple의 스테이블코인이다. 현금, 단기 미국 국채, 현금성 자산으로 뒷받침되고, Ripple 자회사 Standard Custody & Trust Company가 뉴욕주 금융감독청(NYDFS) 제한목적 신탁회사 인가로 발행한다. 두바이 금융감독청(DFSA) 승인도 받았다. 2024-12-17부터 글로벌 거래소에서 거래가 시작됐다. | https://ripple.com/products/stablecoin/ ; https://ripple.com/ripple-press/raising-the-standard-for-stablecoins-ripple-usd-launches-globally/ | 07:54 |
| RLUSD 추가 규제 | NYDFS 최종 승인은 2024-12-10(CEO X 게시물, CoinMarketCap 보도로 확인). 2025-12-12 미국 통화감독청(OCC)이 Ripple National Trust Bank를 조건부 승인했다(최종 인가 아님). 시가총액은 Ripple 발표로 1년이 안 돼 10억 달러를 넘었고, 2026-10-02 제3자 집계로는 약 24억 달러[3자 추정]. | https://ripple.com/ripple-press/ripple-secures-federal-approval-to-establish-national-trust-bank ; https://ripple.com/insights/what-actually-makes-a-stablecoin-regulated-a-guide-for-institutions-evaluating-rlusd/ ; https://xrp-insights.com/xrp-radar | 07:54 |
| XRP 현물 ETF 제도 | 2025-09-17 SEC가 현물 상품(디지털 자산 포함) ETP에 쓸 "일반 상장 기준"을 승인했다. 이 기준을 맞추면 거래소가 상품마다 SEC 규칙 변경 승인을 따로 받지 않아도 된다. | https://www.sec.gov/newsroom/press-releases/2025-121-sec-approves-generic-listing-standards-commodity-based-trust-shares | 07:54 |
| 첫 XRP 현물 ETF | 2025-11-13 Canary XRP ETF(XRPC)가 나스닥에서 거래를 시작했다. 보수 0.50%, 실제 XRP를 Gemini와 BitGo가 보관(ETF Trends 보도). 이어서 Bitwise XRP(NYSE, 2025-11-20 보도), Grayscale GXRP(NYSE Arca 상장 인증 2025-11-21, SEC 제출 문서), 21Shares TOXR(Cboe, 2025-12-11)이 나왔다. | https://www.etftrends.com/canary-capital-launches-first-u-s-spot-xrp-etf/ ; https://www.sec.gov/Archives/edgar/data/2037427/000114336225000417/GXRP112125.pdf ; https://www.nasdaq.com/press-release/21shares-broadens-us-spot-crypto-lineup-launch-xrp-etf-toxr-2025-12-11 | 07:54 |
| ETF 보유량 [3자 추정] | 2026-10-02 기준 미국 현물 XRP ETF 7개가 약 11.9억 XRP 보유. 가장 큰 것은 Bitwise로 4.152억 XRP. | https://xrp-insights.com/xrp-radar | 07:54 |
| 이더리움 비교 | 이더리움은 The Merge로 작업증명(채굴)을 지분증명으로 영구 교체했고, 에너지 사용이 약 99.95% 줄었다고 추정된다. | https://ethereum.org/roadmap/merge/ | 07:55 |

## 쉬운 설명

**사실**
- **XRPL / XRP / Ripple은 서로 다른 것입니다.** XRPL은 누구나 서버를 띄워 참여할 수 있는 오픈소스 장부(네트워크), XRP는 그 장부의 기본 코인, Ripple은 장부를 만든 사람들이 세운 회사입니다. 회사는 XRP 800억 개를 받았고, 지금도 기본 UNL 목록 두 개 중 하나를 냅니다.
- **채굴 대신 "믿을 만한 심사위원 투표"를 씁니다.** 비트코인은 계산 경쟁(채굴)에서 이긴 사람이 다음 장부를 씁니다. XRPL은 각 서버가 믿는 검증자 목록(UNL)을 정해 두고, 그중 80%가 같은 거래 묶음에 동의하면 장부를 확정합니다.
- **새 XRP는 생기지 않습니다.** 1000억 개를 처음에 한꺼번에 만들었고, 수수료로 쓴 XRP는 소각되어 사라집니다.
- **에스크로는 "시간 잠금 금고"입니다.** Ripple 몫 가운데 550억 개를 10억 개씩 55칸으로 나눠 매달 한 칸씩 열리게 했고, 쓰지 않은 양은 맨 뒤 칸에 다시 넣습니다.

**비유**
- 비트코인이 "가장 빨리 퍼즐을 푼 사람이 장부를 쓰는 대회"라면, XRPL은 "미리 정한 심사위원단 가운데 80%가 손을 들면 통과되는 회의"입니다. 회의는 빠르고 전기를 거의 안 쓰지만, 심사위원 명단을 누가 짜느냐가 핵심 쟁점이 됩니다.
- 에스크로는 회사가 가진 쌀을 은행 금고 55칸에 나눠 두고 매달 한 칸씩만 열리게 시간 자물쇠를 건 것과 비슷합니다. 다만 쌀의 주인은 여전히 회사입니다.

**해석(이 노트 작성자의 해석. 사실과 구분)**
- 중앙화 논쟁의 핵심은 "검증자 명단을 실질적으로 누가 정하느냐"로 보입니다. 공식 문서는 명단을 내는 곳(publisher)이 "널리 신뢰받는 검증자를 고르는 데 상당한 힘을 갖는다"고 스스로 적고, 기본 명단 두 개가 보통 거의 같다고 밝힙니다.
- 소송 결과는 "XRP는 증권이 아니다"로 줄여 말하기 어렵습니다. 같은 XRP라도 누구에게 어떤 방식으로 팔았느냐에 따라 판단이 갈렸습니다.

**긍정 견해와 비판 견해(중앙화와 안전성)**

| 관점 | 누가 | 요지 | 출처 |
|---|---|---|---|
| 긍정 | Ripple Research (Chase & MacBrough, 2018, arXiv) | 계획된 탈중앙화 단계에서 합의 알고리즘이 장부 분기 없음(safety)과 멈춤 없음(liveness)을 보장한다고 증명했다고 주장. 저자들은 Ripple 소속이다. | https://arxiv.org/abs/1802.07242 |
| 긍정 | Ripple (2018) | 독립 검증자 2개를 기본 UNL에 넣을 때마다 Ripple 운영 검증자 1개를 빼는 계획을 밝힘 | https://ripple.com/insights/continued-decentralization-xrp-ledger-consensus-protocol/ |
| 비판 | Amores-Sesar, Cachin, Mićić (2020, arXiv, 베른대) | 소스코드로 프로토콜을 재구성한 결과, 비교적 무난한 네트워크 조건에서도 안전성과 진행성이 깨질 수 있는 실행 경로가 있다고 지적 | https://arxiv.org/abs/2011.14816 |
| 비판 | Tumas 외 (2022 arXiv, 2023 ACM SAC) | 소수 노드가 네트워크의 뼈대 역할을 하고, 5일마다 노드의 3분의 1이 바뀐다고 측정. 안정성과 안전에 큰 함의가 있다고 봄. 이 연구는 Ripple UBRI 지원을 받았다. | https://arxiv.org/html/2205.00869v2 |
| 비판(법·규제) | SEC 소장(2020), Crenshaw 위원 반대 의견(2025-05-08) | SEC 소장은 XRP 매수자들이 Ripple의 노력에 기대를 건다고 주장했다. Crenshaw 위원은 2025년 합의가 SEC 집행을 스스로 허무는 일이라며 반대했다. | https://www.sec.gov/files/litigation/complaints/2020/comp-pr2020-338.pdf ; https://www.sec.gov/newsroom/speeches-statements/crenshaw-statement-ripple-050825 |

## 연표

| 날짜 | 사건 | 출처 |
|---|---|---|
| 2011년 초 | Schwartz, McCaleb, Britto가 채굴 없는 시스템 개발 시작 | xrpl.org/about/history |
| 2012-06 | XRP Ledger 출시 | xrpl.org/about/history |
| 2012-09 | NewCoin 설립, 곧 OpenCoin으로 개명. XRP 800억 개를 회사에 줌 | xrpl.org/about/history ; xrpl.org/docs/introduction/what-is-xrp |
| 2013 | OpenCoin에서 Ripple Labs로 개명. SEC 소장은 이해부터 XRP 판매로 자금을 모았다고 주장 | xrpl.org/about/history ; SEC 보도자료 2020-338 |
| 2014 | 합의 백서 "The Ripple Protocol Consensus Algorithm"(Schwartz, Youngs, Britto) | https://xrpl.org/docs/concepts/consensus-protocol/consensus-research |
| 2017-05 | 550억 XRP 에스크로 계획 발표 | ripple.com 에스크로 공지 ; SEC 소장 229항 |
| 2017-12-07 | 에스크로 잠금 완료 | ripple.com 에스크로 공지 ; SEC 소장 229항 |
| 2018-02-20 | Ripple 연구진, 합의 분석 논문과 Cobalt 논문을 arXiv에 공개 | arxiv.org/abs/1802.07242 |
| 2018-05 | 커뮤니티가 XRP 전용 "X" 로고를 선정 | xrpl.org/docs/introduction/what-is-xrp |
| 2020-09-24 | XRPL Foundation 출범(Coil, Ripple, Gatehub이 650만 달러 넘게 기부) | xrpl.org/about/history |
| 2020-12-22 | SEC, Ripple과 경영진 2명 제소 | sec.gov 보도자료 2020-338 |
| 2023-07-13 | 1심 약식판결(기관 판매만 위반) | 법원 문서 989호 |
| 2023-10 | SEC, Garlinghouse와 Larsen에 대한 청구 취하(Decrypt 보도. 정확한 날짜는 미확인) | https://finance.yahoo.com/news/sec-ripple-end-appeals-closing-235853898.html |
| 2024-08-07 | 최종 판결: 영구 금지명령, 벌금 125,035,150달러 | 법원 문서 989호 ; SEC LR-26369 |
| 2024-10-02 / 10-10 | SEC 항소, Ripple 교차항소 | SEC 항소심 경과보고(CourtListener) |
| 2024-12-10 / 12-17 | RLUSD NYDFS 최종 승인(보도) / 글로벌 출시 | Yahoo(CoinMarketCap) ; ripple.com 보도자료 |
| 2025-04-10 | 합의 원칙에 따라 항소심 보류 신청(4-16 승인) | SEC 항소심 경과보고 |
| 2025-05-08 | 합의서 제출과 1차 지시적 판단(indicative ruling) 신청. Crenshaw 반대 성명 | SEC LR-26306 ; Crenshaw 성명 |
| 2025-05-15 | 1차 신청 기각 | SEC 항소심 경과보고 |
| 2025-06-26 | 2차 신청 기각(문서 989호) | 법원 문서 989호 ; CourtListener 기록 |
| 2025-07 | GENIUS Act(미국 스테이블코인법) 서명 | ripple.com OCC 보도자료 |
| 2025-08-07 | 양측 항소 취하. 최종 판결 확정 | SEC LR-26369 |
| 2025-08-22 | 2nd Cir. 항소 취하 승인 명령 | CourtListener 항소법원 문서 |
| 2025-09-17 | SEC, 현물 상품 ETP 일반 상장 기준 승인 | sec.gov 보도자료 2025-121 |
| 2025-11-13 | 첫 미국 XRP 현물 ETF(Canary XRPC) 나스닥 거래 시작 | ETF Trends |
| 2025-12-12 | OCC, Ripple National Trust Bank 조건부 승인 | ripple.com 보도자료 |
| 2026-10-01 | 정기 에스크로 해제(10억). 7억 다시 잠금(Finbold 보도) | finbold.com |

## 우리 프로젝트와의 연결
- **데이터의 범위(사실):** 우리 대시보드는 바이낸스 현물 XRP 캔들만 씁니다. Ripple 보고서(2024년 2분기)에 따르면 XRP 현물 거래량의 65% 이상이 Binance, Bybit, Upbit 세 곳에서 나왔고, 주된 거래 상대는 USDT였습니다(https://ripple.com/insights/q2-2024-xrp-markets-report/). [해석] 바이낸스 캔들은 시장의 큰 부분이지만 전부는 아니고, 업비트(원화) 쪽 움직임과 시차나 괴리가 생길 수 있습니다.
- **정해진 일정 이벤트(사실):** 에스크로는 매달 1일 풀립니다. [해석] 대시보드에 "에스크로 해제일" 표시를 해 두면, 그날 거래량이 튈 때 VPCI(15분봉) 신호를 해석하는 데 참고가 됩니다. 해제 시각(UTC 기준)은 미확인입니다.
- **뉴스 충격(사실, 언론 기준):** 2025-08-07 항소 취하 소식 직후 XRP가 약 7% 올랐다고 The Block이 보도했습니다. [해석] 법원이나 규제 뉴스로 가격이 갑자기 뛰면 1시간봉 Stochastic과 StochRSI가 금방 과매수·과매도 끝에 붙고, 4시간봉 MACD는 늦게 따라옵니다. 이런 날은 점수에 "이벤트 발생" 플래그를 붙여 따로 보는 방식을 생각해 볼 수 있습니다(설계 아이디어이며 효과는 검증하지 않았습니다).
- **BTC·ETH와의 구조 차이:** XRP는 공급이 고정돼 있고, 한 회사(Ripple)가 에스크로와 지갑을 합쳐 큰 몫을 갖고 있습니다(제3자 집계로 약 357억 XRP, 2026-10-02). [해석] 같은 지표를 써도 세 코인이 "왜 움직이는지"는 다를 수 있으니, 가중치를 코인마다 나눠 볼지 팀에서 논의할 거리입니다.
- 이 노트는 공부용이고, 대시보드 점수는 매수·매도 권유가 아닙니다.

## 오해하기 쉬운 점
1. **"Ripple = XRP"가 아닙니다.** 회사, 코인, 네트워크는 서로 다릅니다. 상표도 지금은 XRPL Foundation이 갖고 있습니다.
2. **"법원이 XRP는 증권이 아니라고 했다"는 반만 맞습니다.** 1심은 기관 대상 판매를 증권 판매로 봤고, 금지명령과 벌금이 확정됐습니다. [해석] 항소심 판단 없이 1심에서 끝났으므로, 다른 사건에서 꼭 따라야 하는 상급심 선례는 아닙니다.
3. **"SEC가 합의로 벌금을 5000만 달러로 깎았다"는 틀립니다.** 판사가 두 번 거부했고, 최종 판결의 125,035,150달러가 그대로 남았습니다. 실제 납부가 끝났는지는 SEC나 법원 문서로 확인하지 못했습니다(Decrypt는 에스크로에 맡긴 벌금이 미국 재무부로 넘어간다고 보도).
4. **에스크로는 소각이 아닙니다.** 잠긴 XRP의 주인은 Ripple이고, 매달 풀려서 쓰일 수 있습니다. 실제로 사라지는 것은 수수료로 소각되는 XRP뿐입니다.
5. **"채굴이 없으니 수수료도 없다"도 아닙니다.** 아주 작은 수수료(최소 10 drops)를 내고, 그 XRP는 사라집니다.
6. **ETF 출시는 SEC가 XRP를 보증한다는 뜻이 아닙니다.** 일반 상장 기준과 공시 절차에 따라 상장된 것입니다. Canary 출시 전날 Cointelegraph는 "SEC 최종 승인이 형식상 아직 남아 있다"는 시각을 보도하기도 했습니다.
7. **RLUSD는 XRP가 아닙니다.** 달러에 연동된 별도 토큰이고, XRPL과 이더리움 두 곳에서 발행됩니다.
8. **"Ripple 결제망은 다 XRP로 돈을 보낸다"는 확인되지 않습니다.** Ripple은 스테이블코인, 암호자산, 현지 통화를 함께 다룬다고 소개하고, XRP 사용량 보고서는 2025년 2분기부터 중단했습니다.
9. **출시와 창업 시점이 다릅니다.** 장부 출시는 2012-06, 회사 설립은 2012-09입니다. 공식 문서끼리도 설명이 조금 다릅니다. 역사 페이지는 "세 개발자에 Larsen이 합류"라고 쓰고, What is XRP 페이지는 "Jed와 Arthur가 Larsen과 함께 설립"이라고 씁니다.

## 미확인·더 볼 곳
- **sec.gov 직접 열람 막힘:** sec.gov는 자동 접근을 HTTP 403으로 막았습니다(LR-26306, LR-26369). 본문은 검색 결과에 나온 SEC 페이지 내용으로 확인했습니다. 다음 행동: 브라우저에서 https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26369 와 첨부 Joint Stipulation PDF를 직접 열어 대조하기.
- **벌금 실제 납부와 금지명령 이후 상황:** 미확인. 2025-08-18 Ripple 서한(문서 992호, 금전 부분 집행정지 관련)의 본문을 CourtListener에서 열어 볼 것.
- **SEC가 경영진 청구를 취하한 정확한 날짜(2023-10):** 법원 문서로는 미확인. 1심 기록에서 2023-10 무렵 stipulation을 찾아볼 것.
- **현재 에스크로 잔량과 Ripple 보유량:** 회사 공식 수치는 2025-03-31이 마지막입니다. 현재 값(약 309.8억)은 제3자 집계입니다. ripple.com의 보유량 공개 페이지나 XRPL 장부 직접 조회로 확인이 필요합니다.
- **에스크로 종료 시점:** 2025년 1분기 보고서는 "앞으로 42개월에 걸쳐 해제"라고 썼고, 일부 매체는 "2026년에 끝난다"고 써서 서로 맞지 않습니다. 미확인.
- **XRP ETF가 일반 상장 기준의 어느 조건으로 상장됐는지:** 예를 들어 6개월 이상 거래된 선물이 근거인지 미확인입니다. Canary의 S-1, 424B3와 나스닥 8-A 인증(https://www.sec.gov/Archives/edgar/data/2039505/000135445725001122/XRPC_8-A_Cert_2039505.pdf)을 볼 것.
- **XRP가 실제 송금에 쓰이는 규모:** 공식 수치가 없어 미확인입니다.
- **국제기구(BIS·IMF·FSB)와 한국 당국의 XRP 관련 문서:** 이번 조사에서는 찾지 못했습니다(미확인).
- **비트코인 백서 원문(https://bitcoin.org/bitcoin.pdf):** 이번에 열람하지 않았습니다. 이더리움 The Merge의 정확한 날짜는 열람한 ethereum.org 본문에 나오지 않았습니다.
- **미국 시장구조법(Clarity Act):** Ripple 블로그 "The Road to Clarity Ends (for now)"(2026-09-15)가 있습니다. 규제 흐름을 보려면 원문과 의회 자료를 확인할 것.
- **조사 방식에 대한 고지:** xrpl.org 페이지 몇 개는 병렬로 동시에 읽어서, 같은 사이트 5초 간격 규칙을 지키지 못한 부분이 있습니다.

## 출처 목록
1. XRPL 공식, History: https://xrpl.org/about/history (07:53)
2. XRPL 공식, What is the XRP Ledger: https://xrpl.org/docs/introduction/what-is-the-xrp-ledger (07:53)
3. XRPL 공식, What is XRP: https://xrpl.org/docs/introduction/what-is-xrp (07:53)
4. XRPL 공식, Unique Node List: https://xrpl.org/docs/concepts/consensus-protocol/unl (07:53)
5. XRPL 공식, Consensus Research: https://xrpl.org/docs/concepts/consensus-protocol/consensus-research (07:54)
6. XRPL 공식, Transaction Cost: https://xrpl.org/docs/concepts/transactions/transaction-cost (07:54)
7. XRPL Foundation 검증자 목록 JSON: https://unl.xrplf.org/ (07:55)
8. Ripple, 550억 XRP 에스크로 완료(2017): https://ripple.com/insights/ripple-escrows-55-billion-xrp-for-supply-predictability/ (07:54)
9. Ripple, Q1 2025 XRP Markets Report: https://ripple.com/insights/q1-2025-xrp-markets-report/ (07:54)
10. Ripple, Q2 2024 XRP Markets Report: https://ripple.com/insights/q2-2024-xrp-markets-report/ (07:54)
11. Ripple 홈페이지: https://ripple.com/ (07:55)
12. Ripple, RLUSD 제품 페이지: https://ripple.com/products/stablecoin/ (07:54)
13. Ripple 보도자료, RLUSD 글로벌 출시(2024-12-16): https://ripple.com/ripple-press/raising-the-standard-for-stablecoins-ripple-usd-launches-globally/ (07:54)
14. Ripple 보도자료, OCC 조건부 승인(2025-12-12): https://ripple.com/ripple-press/ripple-secures-federal-approval-to-establish-national-trust-bank (07:54)
15. Ripple, 규제받는 스테이블코인 안내(2026-09-11): https://ripple.com/insights/what-actually-makes-a-stablecoin-regulated-a-guide-for-institutions-evaluating-rlusd/ (07:54)
16. Ripple, 탈중앙화 계획(2018-02-22): https://ripple.com/insights/continued-decentralization-xrp-ledger-consensus-protocol/ (07:54)
17. SEC 보도자료 2020-338: https://www.sec.gov/newsroom/press-releases/2020-338 (07:54)
18. SEC 소장(2020-12-22): https://www.sec.gov/files/litigation/complaints/2020/comp-pr2020-338.pdf (07:54)
19. SEC Litigation Release 26306(2025-05-08): https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26306 (07:54, 직접 열람 403, 검색 본문으로 확인)
20. SEC Litigation Release 26369(2025-08-07): https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26369 (07:54, 같음)
21. SEC Crenshaw 위원 성명(2025-05-08): https://www.sec.gov/newsroom/speeches-statements/crenshaw-statement-ripple-050825 (07:54)
22. SEC 보도자료 2025-121, 일반 상장 기준: https://www.sec.gov/newsroom/press-releases/2025-121-sec-approves-generic-listing-standards-commodity-based-trust-shares (07:54)
23. SEC EDGAR, Grayscale XRP NYSE Arca 인증: https://www.sec.gov/Archives/edgar/data/2037427/000114336225000417/GXRP112125.pdf (07:54)
24. 법원 문서 989호(2025-06-26 Torres 명령) 사본: https://www.nutter.com/assets/htmldocuments/SEC%20v%20Ripple%20Labs%202025.06.26.pdf (07:54)
25. CourtListener, 1심 기록 1:20-cv-10832: https://www.courtlistener.com/docket/19857399/securities-and-exchange-commission-v-ripple-labs-inc/ (07:54)
26. CourtListener, 항소심 SEC 경과보고(2025-06-16): https://storage.courtlistener.com/recap/gov.uscourts.ca2.c99a6526-19b6-430d-a15c-e0c1dd869735/gov.uscourts.ca2.c99a6526-19b6-430d-a15c-e0c1dd869735.63.0.pdf (07:54)
27. CourtListener, 2nd Cir. mandate(2025-08-22): https://storage.courtlistener.com/recap/gov.uscourts.ca2.f031d7d4-2abc-4ba5-88f9-d20482f024ea/gov.uscourts.ca2.f031d7d4-2abc-4ba5-88f9-d20482f024ea.45.0.pdf (07:54)
28. 논문, Chase & MacBrough(2018): https://arxiv.org/abs/1802.07242 (07:54)
29. 논문, Amores-Sesar, Cachin, Mićić(2020): https://arxiv.org/abs/2011.14816 (07:54)
30. 논문, Tumas 외, Topology Analysis of the XRP Ledger: https://arxiv.org/html/2205.00869v2 (07:54)
31. ethereum.org, The Merge: https://ethereum.org/roadmap/merge/ (07:55)
32. 언론(날짜 확인용), The Block 2025-08-07: https://www.theblock.co/news/business/2025-08-07-sec-ripple-to-end-legal-battle-as-both-parties-abandon-appeals-leaving-xrp-ruling-intact-366096 (07:54)
33. 언론(날짜 확인용), Decrypt via Yahoo Finance 2025-08-07: https://finance.yahoo.com/news/sec-ripple-end-appeals-closing-235853898.html (07:54)
34. 언론(날짜 확인용), CoinMarketCap via Yahoo Finance 2024-12-11(RLUSD NYDFS 승인): https://finance.yahoo.com/news/ripple-secures-nydfs-approval-rlusd-065226515.html (07:54)
35. 언론(날짜 확인용), ETF Trends 2025-11-13(Canary XRPC): https://www.etftrends.com/canary-capital-launches-first-u-s-spot-xrp-etf/ (07:54)
36. 언론(날짜 확인용), Cointelegraph 2025-11-13: https://cointelegraph.com/news/first-spot-xrp-etf-launch-thursday-canary-community (07:54)
37. 보도자료(GlobeNewswire via Nasdaq) 2025-12-11(21Shares TOXR): https://www.nasdaq.com/press-release/21shares-broadens-us-spot-crypto-lineup-launch-xrp-etf-toxr-2025-12-11 (07:54)
38. 언론(날짜 확인용), Finbold 2026-10-02(에스크로): https://finbold.com/ripple-locks-1-billion-worth-of-xrp-into-escrow/ (07:54)
39. 제3자 장부 집계(수치 참고용, 3자 추정): https://xrp-insights.com/xrp-radar (07:54)
