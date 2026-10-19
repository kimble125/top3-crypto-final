// 지표 그래프 고르기 규칙(기획안_지표그래프 §3)과 그리기 함수 시험. 실행: node 05_프론트/tests/chart_selection.test.js
const assert = require("assert");
const C = require("../app/chart.js");

const S = C.SPLIT();
// 처음(나눠 보기) → 누른 하나만
let st = C.nextSelection(S, "macd");
assert.deepStrictEqual(st, { mode: "pick", sel: ["macd"] });
// 흐린 것을 더하면 겹침(순서는 MACD·Sto·SRSI·VPCI로 고정)
st = C.nextSelection(st, "vpci");
st = C.nextSelection(st, "sto");
assert.deepStrictEqual(st.sel, ["macd", "sto", "vpci"]);
// 선택된 것을 누르면 뺌
st = C.nextSelection(st, "macd");
assert.deepStrictEqual(st.sel, ["sto", "vpci"]);
// 마지막 하나를 누르면 나눠 보기로
st = C.nextSelection(C.nextSelection(st, "sto"), "vpci");
assert.deepStrictEqual(st, S);
// 네 개를 하나씩 모두 고르면 겹쳐 보기(나눠 보기와 다름)
st = ["macd", "sto", "srsi", "vpci"].reduce((a, id, i) => (i === 0 ? C.nextSelection(S, id) : C.nextSelection(a, id)), null);
assert.strictEqual(st.mode, "pick");
assert.strictEqual(st.sel.length, 4);
// 잘못된 값·저장값 복구
assert.deepStrictEqual(C.nextSelection(S, "xx"), S);
assert.deepStrictEqual(C.normalize({ mode: "pick", sel: [] }), S);
assert.deepStrictEqual(C.normalize({ mode: "pick", sel: ["vpci", "macd", "zz"] }), { mode: "pick", sel: ["macd", "vpci"] });
assert.deepStrictEqual(C.normalize(null), S);

// 그리기: 칸 수, 봉 누락에서 선 끊김, 튀는 값 잘림 표시
const H = 3600e3, t0 = Date.UTC(2026, 9, 1), n = 48;
const ts = (step, k) => Array.from({ length: k }, (_, i) => t0 + (i + 1) * step);
const t15 = ts(H / 4, n * 4), t1 = ts(H, n), t4 = ts(4 * H, n / 4);
const vp = t15.map((_, i) => (i === 100 ? 5000 : Math.sin(i / 7) * 10));
const data = {
  symbol: "TESTUSDT", days: 2, range: { from: t0, to: t15[t15.length - 1] },
  price: { t: t15, c: t15.map((_, i) => 100 + Math.sin(i / 9)) },
  macd: { t: t4, macd: t4.map((_, i) => i - 5), signal: t4.map((_, i) => i - 6) },
  sto: { t: t1, k: t1.map((_, i) => (i % 20) * 5), d: t1.map((_, i) => (i % 20) * 5 - 2) },
  srsi: { t: t1.filter((_, i) => i !== 10), k: t1.filter((_, i) => i !== 10).map(() => 50), d: t1.filter((_, i) => i !== 10).map(() => 50) },
  vpci: { t: t15, v: vp, s: vp.map((v) => v / 2) },
  events: [{ t: t1[5], ind: "sto", dir: 1 }], analyses: [{ t: t4[2], score: 100, strong: 1, strong_dir: 1 }], gaps: [],
};
const split = C.render(data, S, { width: 900 });
assert.strictEqual(split.paneInfo.length, 4);
const pick = C.render(data, { mode: "pick", sel: ["sto", "vpci"] }, { width: 900, added: "vpci" });
assert.strictEqual(pick.paneInfo.length, 1);
assert.ok(pick.svg.includes('class="main c-vpci draw"'), "새로 더한 지표는 그리기 효과");
assert.ok(/↑/.test(pick.svg), "튀는 값이 잘리면 표시");
// StochRSI 10번째 봉이 빠짐 → 경로가 두 번 시작(M 두 개)
const srsi = C.render(data, { mode: "pick", sel: ["srsi"] }, { width: 900 });
const m = srsi.svg.match(/class="main c-srsi[^"]*"[^>]*d="([^"]+)"/);
assert.strictEqual((m[1].match(/M/g) || []).length, 2, "봉 누락에서 선이 끊김");
// 마우스 위치 값: 시간대가 다르면 그 시각 직전에 닫힌 봉
const vals = C.valuesAt(data, ["macd", "sto"], t1[10] + 30 * 60e3);
assert.strictEqual(vals.find((v) => v.id === "sto").t, t1[10]);
assert.strictEqual(vals.find((v) => v.id === "macd").t, t4[1]);  // t0+11.5시간 → 마지막 4시간봉 마감은 t0+8시간
// StochRSI 10번째 봉이 빠진 구간에서는 직전 값 대신 '봉 누락'(10-04 GPT-6.1 Sol)
const gapT = data.srsi.t;
const gi = gapT.findIndex((x, i) => i < gapT.length - 1 && gapT[i + 1] - x > 3600e3);
assert.ok(gi >= 0, "시험 데이터에 누락 구간 있음");
assert.strictEqual(C.valuesAt(data, ["srsi"], gapT[gi] + 3600e3 + 60e3).find((v) => v.id === "srsi").gap, true);
assert.strictEqual(C.valuesAt(data, ["srsi"], gapT[gi] + 60e3).find((v) => v.id === "srsi").gap, false);
console.log("chart_selection.test.js: 모두 통과");
