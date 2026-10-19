// V5 화면 계산(view5.js) 시험(10-14). 실행: node 05_프론트/tests/view5.test.js
const assert = require("assert");
const V = require("../app/view5.js");

// ---- groupDir: ≥10 Long, ≤−10 Short, 그 사이 중립, 없음 null
assert.strictEqual(V.groupDir(10), 1);
assert.strictEqual(V.groupDir(9.9), 0);
assert.strictEqual(V.groupDir(-9.9), 0);
assert.strictEqual(V.groupDir(-10), -1);
assert.strictEqual(V.groupDir(null), null);
assert.strictEqual(V.groupDir(undefined), null);
assert.strictEqual(V.groupDir("x"), null);

// ---- confView: v2
const c2 = (o) => ({ version: "conf_v2", p_long: 77, side: "Long", side_pct: 77, level: "medium", label: "Long 우세", score: 68, ...o });
assert.deepStrictEqual(V.confView(c2()), { v: 2, held: false, big: "77", unit: "%", cls: "up", dir: 1, label: "Long 우세", side: "Long" });
assert.strictEqual(V.confView(c2({ p_long: 18, side: "Short", side_pct: 82, level: "high", label: "강한 Short" })).cls, "down");
assert.strictEqual(V.confView(c2({ p_long: 18, side: "Short", side_pct: 82, level: "high" })).big, "82");
// 중립은 회색, 숫자는 우세 쪽 %
const neu = V.confView(c2({ p_long: 52, side: "Long", side_pct: 52, level: "neutral", label: "중립" }));
assert.strictEqual(neu.cls, "zero"); assert.strictEqual(neu.dir, 0); assert.strictEqual(neu.big, "52");
// 자료 부족(p_long null)
const held = V.confView(c2({ p_long: null, side: null, side_pct: null, level: null, label: "자료 부족", score: null }));
assert.strictEqual(held.held, true); assert.strictEqual(held.big, "–"); assert.strictEqual(held.unit, ""); assert.strictEqual(held.label, "자료 부족");
// side_pct 가 없어도 p_long 에서 되살림 · level 없으면 54 이하는 중립
assert.strictEqual(V.confView({ version: "conf_v2", p_long: 30, side: "Short" }).big, "70");
assert.strictEqual(V.confView({ version: "conf_v2", p_long: 53 }).cls, "zero");
// v1(옛 자료)·없음은 던지지 않고 옛 꼴
const v1 = V.confView({ version: "conf_v1", score: 24, label: "약한 Long" });
assert.strictEqual(v1.v, 1); assert.strictEqual(v1.big, "+24"); assert.strictEqual(v1.unit, ""); assert.strictEqual(v1.cls, "up");
assert.strictEqual(V.confView({ version: "conf_v1", score: -5 }).cls, "zero");
assert.strictEqual(V.confView({ version: "conf_v1", score: -40 }).big, "−40");
assert.strictEqual(V.confView({ version: "conf_v1", score: null }).big, "–");
assert.strictEqual(V.confView(null).big, "–");
assert.strictEqual(V.confView({}).big, "–");
assert.strictEqual(V.confDir(c2()), 1);
assert.strictEqual(V.confDir(neu === null ? null : c2({ level: "neutral", p_long: 51, side_pct: 51 })), 0);
assert.strictEqual(V.confDir(null), 0);
assert.strictEqual(V.aiDir({ trend_direction: "Long" }), 1);
assert.strictEqual(V.aiDir({ trend_direction: "Short" }), -1);
assert.strictEqual(V.aiDir({ trend_direction: "Neutral" }), 0);
assert.strictEqual(V.aiDir(null), 0);

// ---- confSub: 묶음 한 줄 / note 가 있으면 note
const g = (t, m) => ({ tech: { score: t }, market: { score: m } });
assert.deepStrictEqual(V.confSub(c2({ groups: g(86.5, 9.9), note: null })), { text: "기술 Long · 시장 자료 중립", note: false });
assert.deepStrictEqual(V.confSub(c2({ groups: g(-11.5, -50), note: null })), { text: "기술 Short · 시장 자료 Short", note: false });
assert.deepStrictEqual(V.confSub(c2({ groups: g(40, 50), note: "시장 자료 부족: OI·뉴스 없음 → 기술 지표만" })), { text: "시장 자료 부족: OI·뉴스 없음 → 기술 지표만", note: true });
assert.deepStrictEqual(V.confSub(c2({ groups: g(40, null), note: null })), { text: "기술 Long", note: false });
// 묶음이 둘 다 남았으면 가벼운 note 대신 묶음 요약(Fable 검토 아이디어 C), 묶음이 빠졌으면 note
const gu = (t, tu, m, mu) => ({ tech: { score: t, used: tu }, market: { score: m, used: mu } });
assert.deepStrictEqual(V.confSub(c2({ groups: gu(-46.2, true, 50, true), note: "뉴스 방향 없음" })), { text: "기술 Short · 시장 자료 Long", note: false });
assert.deepStrictEqual(V.confSub(c2({ groups: gu(40, true, 9.1, false), note: "시장 자료 부족: OI·코인베이스 프리미엄 없음 → 기술 지표만" })),
  { text: "시장 자료 부족: OI·코인베이스 프리미엄 없음 → 기술 지표만", note: true });
assert.deepStrictEqual(V.confSub(c2({ groups: undefined })), { text: "", note: false });
assert.deepStrictEqual(V.confSub({ version: "conf_v1", score: 3 }), { text: "", note: false });
assert.deepStrictEqual(V.confSub(null), { text: "", note: false });

// ---- topFactors
const fw = { price: { direction: 1, weight_pct: 10 }, macd: { direction: 1, weight_pct: 12 }, stoch: { direction: 1, weight_pct: 8 }, stochrsi: { direction: 0, weight_pct: 5 },
  oi: { direction: 1, weight_pct: 14 }, premium: { direction: -1, weight_pct: 12 }, fng: { direction: 1, weight_pct: 14 }, news: { direction: 1, weight_pct: 25 } };
assert.deepStrictEqual(V.topFactors(fw, 3).map((r) => [r.key, r.pct]), [["news", 25], ["oi", 14], ["fng", 14]]);   // 동률은 항목 순서(oi 가 fng 보다 앞)
assert.deepStrictEqual(V.topFactors(fw).map((r) => r.key), ["news", "oi", "fng"]);
assert.deepStrictEqual(V.topFactors(null, 3), []);
assert.deepStrictEqual(V.topFactors({ news: { direction: 1 } }, 3), []);
assert.strictEqual(V.aiPct(fw, "macd"), 12);
assert.strictEqual(V.aiPct(fw, "zzz"), null);
assert.strictEqual(V.aiPct(null, "macd"), null);

// ---- newsBias
assert.deepStrictEqual(V.newsBias({ news_bias: { x: 1, score: 0.4, n: 5 } }), { none: false, x: 1, n: 5, text: "긍정 +1", cls: "up" });
assert.strictEqual(V.newsBias({ news_bias: { x: -1, score: -0.5, n: 2 } }).text, "부정 −1");
assert.strictEqual(V.newsBias({ news_bias: { x: 0, score: 0.1, n: 3 } }).text, "중립 0");
assert.strictEqual(V.newsBias({ news_bias: { x: null, score: null, n: 0 } }).none, true);
assert.strictEqual(V.newsBias({}), null);
assert.strictEqual(V.newsBias(null), null);

// ---- divergence: 기술 Short · AI Long
const cDiv = { groups: { tech: { score: -20 } } };
const bodyLong = { trend_direction: "Long", factor_weights: fw };
const dv = V.divergence(cDiv, bodyLong);
assert.strictEqual(dv.tech, -1); assert.strictEqual(dv.ai, 1);
// 기술 밖 4항목 중 AI 방향(Long)과 같은 것: oi 14 · fng 14 · news 25 (premium 은 Short) → 비중 큰 순 최대 2개 = news, oi
assert.deepStrictEqual(dv.reasons.map((r) => [r.key, r.word, r.pct]), [["news", "긍정", 25], ["oi", "Long", 14]]);
assert.strictEqual(V.divergenceText(dv), "엇갈림: 기술 지표 Short · AI Long — AI가 설명한 근거: 뉴스(긍정, 25%) · 미결제약정(Long, 14%)");
// 같은 방향·중립·AI Neutral·묶음 점수 없음은 엇갈림 아님
assert.strictEqual(V.divergence({ groups: { tech: { score: 30 } } }, bodyLong), null);
assert.strictEqual(V.divergence({ groups: { tech: { score: 5 } } }, bodyLong), null);
assert.strictEqual(V.divergence(cDiv, { trend_direction: "Neutral", factor_weights: fw }), null);
assert.strictEqual(V.divergence({ groups: { tech: { score: null } } }, bodyLong), null);
assert.strictEqual(V.divergence({}, bodyLong), null);
assert.strictEqual(V.divergence(null, bodyLong), null);
// factor_weights 가 없어도(옛 분석) 엇갈림 자체는 보이고 이유 없이 머리만
const dv2 = V.divergence(cDiv, { trend_direction: "Long" });
assert.deepStrictEqual(dv2.reasons, []);
assert.strictEqual(V.divergenceText(dv2), "엇갈림: 기술 지표 Short · AI Long");
// AI Short · 기술 Long
const dv3 = V.divergence({ groups: { tech: { score: 25 } } }, { trend_direction: "Short", factor_weights: { fng: { direction: -1, weight_pct: 9 }, news: { direction: 1, weight_pct: 30 } } });
assert.strictEqual(V.divergenceText(dv3), "엇갈림: 기술 지표 Long · AI Short — AI가 설명한 근거: 공포탐욕(악화, 9%)");

// ---- newsRows: id 로 제목 짝짓기, 옛 분석은 빈 배열
const body = { news_items: [{ id: "n1", relevance: "coin", direction: 1, importance: 3 }, { id: "n2", relevance: "none", direction: 0, importance: 1 }, { id: "n9", relevance: "market", direction: -1, importance: 2 }],
  news_ref: [{ id: "n1", title: "제목1", publisher: "연합", time: "10-14 08:41" }, { id: "n2", title: "제목2", publisher: "", time: "" }] };
const rows = V.newsRows(body);
assert.strictEqual(rows.length, 3);
assert.deepStrictEqual([rows[0].title, rows[0].dirText, rows[0].relText, rows[0].imp, rows[0].cls], ["제목1", "긍정", "코인", 3, "up"]);
assert.deepStrictEqual([rows[1].rel, rows[1].relText, rows[1].dirText], ["none", "무관", "중립"]);
assert.strictEqual(rows[2].title, "");   // news_ref 에 없는 id: 제목 없음(화면이 대신 글자를 넣음)
assert.strictEqual(rows[2].dirText, "부정");
assert.deepStrictEqual(V.newsRows({}), []);
assert.deepStrictEqual(V.newsRows(null), []);
assert.strictEqual(V.newsRows({ news_items: [{ id: "n1", relevance: "weird", importance: 9 }] })[0].imp, 3);

// ---- aiStatusLines
const lt = (o) => ({ created_kst: "10-14 09:04", ok: false, code: "limit", retry_at_kst: "12:37", retry_est: false, model: "m", fallback_from: null, ...o });
assert.deepStrictEqual(V.aiStatusLines({ BTCUSDT: { latest: {}, last_try: lt({ ok: true, code: null, fallback_from: "limit" }) } }),
  ["BTC AI 분석: 사용 한도(12:37 이후 다시 시도) · Claude로 대신 분석함"]);
assert.deepStrictEqual(V.aiStatusLines({ BTCUSDT: { latest: {}, last_try: lt({ ok: true, code: null, fallback_from: "limit", retry_est: true }) } }),
  ["BTC AI 분석: 사용 한도(12:37(추정) 이후 다시 시도) · Claude로 대신 분석함"]);
assert.deepStrictEqual(V.aiStatusLines({ ETHUSDT: { latest: {}, last_try: lt({ code: "timeout", retry_at_kst: null }) } }), ["ETH AI 분석: 시간 초과 · 이전 분석을 보여 줌"]);
assert.deepStrictEqual(V.aiStatusLines({ XRPUSDT: { latest: null, last_try: lt({ code: "invalid", retry_at_kst: "10-15 09:00" }) } }), ["XRP AI 분석: 검사 실패(10-15 09:00 이후 다시 시도)"]);
assert.deepStrictEqual(V.aiStatusLines({ XRPUSDT: { latest: {}, last_try: lt({ code: "error" }) } }), ["XRP AI 분석: 오류(12:37 이후 다시 시도) · 이전 분석을 보여 줌"]);
assert.deepStrictEqual(V.aiStatusLines({ BTCUSDT: { latest: {}, last_try: lt({ ok: true, code: null, fallback_from: null }) } }), []);   // 정상: 줄 없음
// 옛 형식(code 없음)·last_try 없음·null 은 던지지 않음
assert.deepStrictEqual(V.aiStatusLines({ BTCUSDT: { latest: {}, last_try: { created_kst: "10-14 09:04", ok: false, note: "x" } } }), ["BTC AI 분석의 마지막 시도(10-14 09:04)가 실패했습니다 · 이전 분석을 보여 줌"]);
assert.deepStrictEqual(V.aiStatusLines({ BTCUSDT: { latest: {}, last_try: null }, _at: 1 }), []);
assert.deepStrictEqual(V.aiStatusLines(null), []);
assert.strictEqual(V.failWord(lt({ code: "limit" })), "사용 한도");
assert.strictEqual(V.failWord(lt({ code: null })), "실패");
assert.strictEqual(V.failWord(lt({ ok: true })), "");

// ---- fngEvents · fngLayout
// 시리즈: 09-15 .. 10-14 (30일)
const dates = []; for (let i = 0; i < 30; i++) { const d = new Date(Date.UTC(2026, 8, 15 + i)); dates.push(d.toISOString().slice(0, 10)); }
const ser = dates.map((date, i) => ({ date, value: 40 + (i % 7) * 5 }));
const fng = { series: ser, events: [
  { date: "2026-10-13", value: 57, delta: -12, btc_chg_pct: -2.3, news: [{ title: "A", url: "https://x", publisher: "연합" }, { title: "B", url: "https://y", publisher: "R" }, { title: "C" }], news_note: null },
  { date: "2026-09-19", value: 71, delta: 15, btc_chg_pct: null, news: [], news_note: "뉴스 수집 전" },
  { date: "2026-08-01", value: 10, delta: -9, btc_chg_pct: 1, news: [], news_note: null },   // 시리즈 밖 날짜
] };
const ev = V.fngEvents(fng);
assert.deepStrictEqual(ev.map((e) => e.date), ["2026-08-01", "2026-09-19", "2026-10-13"]);   // 날짜순 번호
assert.strictEqual(ev[2].n, 3); assert.strictEqual(ev[2].prev, 69); assert.strictEqual(ev[2].deltaText, "−12"); assert.strictEqual(ev[2].btc, "BTC −2.3%"); assert.strictEqual(ev[2].news.length, 2);
// btc_date(지수 날짜 D의 값은 D−1 시장을 반영)가 있으면 등락 앞에 그 날짜
const evd = V.fngEvents({ series: ser, events: [{ date: "2026-10-13", value: 57, delta: -12, btc_date: "2026-10-12", btc_chg_pct: -2.3, news: [], news_note: null }] })[0];
assert.strictEqual(evd.btc, "10-12 BTC −2.3%"); assert.strictEqual(evd.btcDate, "10-12");
assert.strictEqual(V.fngEvents({ series: ser, events: [{ date: "2026-10-13", value: 57, delta: -12, btc_date: "2026-10-12", btc_chg_pct: null }] })[0].btc, "");
assert.strictEqual(ev[1].btc, ""); assert.strictEqual(ev[1].note, "뉴스 수집 전"); assert.strictEqual(ev[1].deltaText, "+15");
assert.strictEqual(ev[0].idx, null); assert.strictEqual(ev[2].idx, 28);
assert.deepStrictEqual(V.fngEvents({ series: ser }), []);
assert.deepStrictEqual(V.fngEvents(null), []);
const L = V.fngLayout(fng, 900);
assert.strictEqual(L.W, 560); assert.strictEqual(L.H, 140);   // 가로 최대 560, 높이 140
assert.strictEqual(V.fngLayout(fng, 300).W, 300);
assert.strictEqual(V.fngLayout(fng, 100).W, 280);
assert.deepStrictEqual(L.ticks.map((t) => t.label), ["09-16", "09-23", "09-30", "10-07", "10-14"]);   // 7일마다, 맨 오른쪽은 가장 최근
assert.ok(L.ticks.every((t, i, a) => !i || t.x > a[i - 1].x));
assert.strictEqual(L.dots.length, 2);   // 시리즈 밖 날짜는 점 없음
assert.deepStrictEqual(L.dots.map((d) => d.n), [2, 3]);
assert.ok(L.y50 > 0 && L.y50 < L.H);
assert.strictEqual(V.fngLayout({ series: [{ date: "2026-10-14", value: 50 }] }, 560), null);
assert.strictEqual(V.fngLayout(null, 560), null);
// 값이 null 이어도 던지지 않음
assert.ok(V.fngLayout({ series: [{ date: "2026-10-13", value: null }, { date: "2026-10-14", value: 60 }] }, 560).d.startsWith("M"));

// ---- sparkLayout
const sp = Array.from({ length: 42 }, (_, i) => ({ t: "x", close: 100 + (i % 5) }));
const S = V.sparkLayout(sp, 160, 62);
assert.ok(S.d.startsWith("M") && S.ex > 100 && S.ex < 160 && S.ey >= 0 && S.ey <= 62);
assert.strictEqual(V.sparkLayout([], 160, 62), null);
assert.strictEqual(V.sparkLayout(undefined), null);
assert.strictEqual(V.sparkLayout([{ close: 1 }]), null);
assert.ok(V.sparkLayout([{ close: 5 }, { close: 5 }]).d.includes("L"));   // 값이 모두 같아도 나누기 0 없음

// ---- 검증 화면 helpers
assert.strictEqual(V.thrText({ thr_text: "AAA 2% · BBB 3%(수수료 포함)", success_pct: { AAAUSDT: 1.9 } }), "AAA 2% · BBB 3%(수수료 포함)");
assert.strictEqual(V.thrText({ success_pct: 1.0, fee_pct_per_side: 0.05 }), "+1%(수수료 왕복 0.1% 뺌)");
assert.strictEqual(V.thrText({ success_pct: { default: 1 } }), "");   // 객체를 글로 찍지 않음
assert.strictEqual(V.thrText(null), "");
assert.strictEqual(V.fix24Cell({ fix24_n: 10, fix24_success_pct: 60, fix24_opp_pct: 50 }), "60% · 반대 50% (10)");
assert.strictEqual(V.fix24Cell({ fix24_n: 0, fix24_success_pct: null }), "-");
assert.strictEqual(V.fix24Cell({}), "-");
assert.strictEqual(V.fix24Cell(null), "-");
assert.strictEqual(V.fix24Cell({ fix24_n: 4, fix24_success_pct: 25, fix24_opp_pct: null }), "25% (4)");
assert.deepStrictEqual(V.fix24Row({ fix24_result: "success", fix24_net_pct: 1.4 }), { key: "success", word: "성공", pct: 1.4 });
assert.deepStrictEqual(V.fix24Row({ fix24_result: "fail", fix24_net_pct: -0.3 }), { key: "fail", word: "실패", pct: -0.3 });
assert.deepStrictEqual(V.fix24Row({ fix24_result: null }), { key: "open", word: "진행 중", pct: null });
assert.deepStrictEqual(V.fix24Row(undefined), { key: "open", word: "진행 중", pct: null });

assert.strictEqual(V.fmt1(86.5), "+86.5"); assert.strictEqual(V.fmt1(-11.5), "−11.5"); assert.strictEqual(V.fmt1(0), "0.0"); assert.strictEqual(V.fmt1(null), "–");
console.log("view5.test.js: 모두 통과");
