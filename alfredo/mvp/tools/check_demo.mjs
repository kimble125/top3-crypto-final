// 데모 화면 점검·화면 사진·PDF (2026-10-13). 맥의 크롬(헤드리스)과 Node 기본 WebSocket만 쓴다(설치 없음).
// Top3 Crypto 화면 점검 도구와 같은 방식이다.
//
//   점검: SP=<임시 폴더> node mvp/tools/check_demo.mjs check <html 파일> <사진 폴더>
//     - 바깥 요청(file:·data: 밖) 수, JS 예외·콘솔 오류, 가로 넘침(PC 1440·휴대폰 390), 글꼴 적용, 깨진 글자(U+FFFD),
//       머리 띠 고지 문장, 카드·탭을 차례로 눌렀을 때의 오류. 화면 사진은 사진 폴더에 남긴다.
//   PDF:  SP=<임시 폴더> node mvp/tools/check_demo.mjs pdf <html 파일> <out.pdf>   (CSS @page를 따름)
// 끝나면 결과를 JSON 한 줄로 찍고, 문제가 있으면 종료 코드 1.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [mode, input, out] = process.argv.slice(2);
if (!["check", "pdf", "board"].includes(mode) || !input || !out) {
  console.error("사용: node check_demo.mjs check|board|pdf <html> <사진 폴더|out.pdf>");
  process.exit(2);
}
const CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const dir = mkdtempSync((process.env.SP || "/tmp") + "/chrome-");
const port = 9300 + Math.floor(Math.random() * 500);
const ch = spawn(CH, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`, "--no-first-run",
  "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let list;
for (let i = 0; i < 60; i++) {
  try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (list.length) break; } catch (e) { /* 아직 안 뜸 */ }
  await sleep(200);
}
const ws = new WebSocket(list.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pend = new Map(), errs = [], requests = [];
ws.addEventListener("message", (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
  if (d.method === "Network.requestWillBeSent") requests.push(d.params.request.url);
  if (d.method === "Runtime.exceptionThrown") errs.push("예외: " + (d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300));
  if (d.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(d.params.type)) errs.push("콘솔 " + d.params.type + ": " + d.params.args.map((a) => a.value ?? a.description).join(" ").slice(0, 300));
  if (d.method === "Log.entryAdded" && d.params.entry.level === "error") errs.push("로그: " + d.params.entry.text.slice(0, 200));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); return r.result?.result?.value ?? r.result?.exceptionDetails?.exception?.description; };
await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable"); await send("Network.enable");
const url = /^https?:\/\//.test(input) ? input : pathToFileURL(resolve(input)).href;   // 로컬 채팅 서버 주소도 받는다
const external = () => requests.filter((u) => !u.startsWith("file:") && !u.startsWith("data:") && !u.startsWith("about:") && !/^http:\/\/(127\.0\.0\.1|localhost)[:/]/.test(u));

async function shot(file) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  writeFileSync(file, Buffer.from(r.result.data, "base64"));
}
async function viewport(width, height, mobile) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
}

if (mode === "pdf") {
  await send("Page.navigate", { url });
  await sleep(1500);
  const r = await send("Page.printToPDF", { preferCSSPageSize: true, printBackground: true });
  writeFileSync(out, Buffer.from(r.result.data, "base64"));
  const res = { pdf: out, external: external(), errors: errs };
  console.log(JSON.stringify(res));
  ws.close(); ch.kill();
  process.exit(res.external.length || res.errors.length ? 1 : 0);
}


if (mode === "board") {
  // V2 대시보드: 탭(코인·주식·기타·AI 분석·공부·설정)과 카드를 차례로 눌러 보고 PC·휴대폰 화면 사진
  const res = {};
  for (const [name, w, h, mobile] of [["pc", 1440, 900, false], ["mobile", 390, 844, true]]) {
    await viewport(w, h, mobile);
    await send("Page.navigate", { url: "about:blank" }); await sleep(300);
    await send("Page.navigate", { url: url + "#coin" }); await sleep(1500);
    const info = await ev(`(async () => { await document.fonts.ready; await document.fonts.load('600 16px "AlfredoSans"', '알프레도');
      return { overflowX: document.documentElement.scrollWidth - window.innerWidth, font: document.fonts.check('16px "AlfredoSans"', '알프레도 가'),
        replacementChars: (document.body.innerText.match(/\\uFFFD/g) || []).length, bandVisible: document.getElementById('band').getBoundingClientRect().height > 0,
        cards: document.querySelectorAll('#cards .kcard').length }; })()`);
    const steps = [];
    for (const v of ["coin", "stock", "other", "ai", "study", "settings"]) {
      steps.push(await ev(`(document.querySelector('.tabs [data-view="${v}"]').click(), new Promise(r => setTimeout(() => r('${v}:' + (document.documentElement.scrollWidth - window.innerWidth) + ':' + (document.getElementById('chart-title') ? document.getElementById('chart-title').textContent : '')), 250)))`));
      if (["coin", "stock", "other"].includes(v)) {
        if (name === "pc" || v === "coin") await shot(`${out}/board_${name}_${v}.png`);
        steps.push(await ev(`(document.querySelectorAll('#cards .kcard')[2].click(), new Promise(r => setTimeout(() => r(document.getElementById('chart-title').textContent + ' ' + document.querySelector('#ev-body .ev-score').textContent), 250)))`));
      }
    }
    if (name === "pc" && process.env.ASK) {   // 로컬 서버로 연 화면에서만: 질문 하나를 보내 답이 오면 사진(GPT 한 번 씀)
      steps.push(await ev(`(document.querySelector('.tabs [data-view="coin"]').click(), document.getElementById('chat-in').value = ${JSON.stringify(process.env.ASK)}, document.getElementById('chat-form').requestSubmit(),
        new Promise(r => { const t0 = Date.now(), t = setInterval(() => { const n = document.querySelectorAll('#chat-log .msg.ai').length; if (n >= 2 || Date.now() - t0 > 90000) { clearInterval(t); r('ai msgs ' + n); } }, 500); }))`));
      await shot(`${out}/board_${name}_chat.png`);
    }
    steps.push(await ev(`(document.querySelector('.tabs [data-view="coin"]').click(), document.querySelector('#chart-range [data-n="180"]').click(), document.querySelector('[data-set="theme"] [data-v="light"]').click(), document.documentElement.dataset.theme)`));
    res[name] = { ...info, steps };
  }
  res.external = external(); res.errors = errs;
  console.log(JSON.stringify(res, null, 1));
  ws.close(); ch.kill();
  process.exit(res.external.length || errs.length || ["pc", "mobile"].some((k) => res[k].overflowX > 0 || res[k].replacementChars) ? 1 : 0);
}

const result = {};
for (const [name, w, h, mobile] of [["pc", 1440, 900, false], ["mobile", 390, 844, true]]) {
  await viewport(w, h, mobile);
  await send("Page.navigate", { url: "about:blank" }); await sleep(300);
  await send("Page.navigate", { url: url + "#home" });
  await sleep(1500);
  const info = await ev(`(async () => {
    await document.fonts.ready;
    await document.fonts.load('600 16px "AlfredoSans"', '알프레도');
    const txt = document.body.innerText;
    return {
      overflowX: document.documentElement.scrollWidth - window.innerWidth,
      font: document.fonts.check('16px "AlfredoSans"', '알프레도 가'),
      replacementChars: (txt.match(/\\uFFFD/g) || []).length,
      band: document.getElementById('band').textContent,
      bandVisible: document.getElementById('band').getBoundingClientRect().height > 0,
      cards: document.querySelectorAll('#cards .kcard').length,
      title: document.title,
    };
  })()`);
  await shot(`${out}/demo_${name}_home.png`);
  const clicks = [];
  for (const k of ["pr", "alloc", "ret"]) {
    clicks.push(await ev(`(document.querySelector('#cards .kcard[data-k="${k}"]').click(), new Promise(r => setTimeout(() => r(document.getElementById('detail-title').textContent), 200)))`));
    if (name === "pc" && k !== "ret") await shot(`${out}/demo_${name}_card_${k}.png`);
  }
  const views = [];
  for (const v of ["report", "guide", "home"]) {
    views.push(await ev(`(document.querySelector('.tabs [data-view="${v}"]').click(), new Promise(r => setTimeout(() => r('${v}:' + !document.getElementById('view-${v}').hidden + ':' + (document.documentElement.scrollWidth - window.innerWidth)), 200)))`));
    if (v !== "home") await shot(`${out}/demo_${name}_${v}.png`);
  }
  const chart = await ev(`(() => { const s = document.querySelector('#chart svg'); if (!s) return 'no svg'; const r = s.getBoundingClientRect();
    s.querySelector('#hit').dispatchEvent(new PointerEvent('pointermove', { clientX: r.left + r.width * 0.5, clientY: r.top + 40, bubbles: true }));
    return document.getElementById('tip').textContent.slice(0, 60); })()`);
  const theme = await ev(`(document.getElementById('theme-btn').click(), document.documentElement.dataset.theme)`);
  if (name === "pc") await shot(`${out}/demo_${name}_home_light.png`);
  result[name] = { ...info, clicks, views, chart, theme };
}
result.external = external();
result.errors = errs;
console.log(JSON.stringify(result, null, 1));
ws.close(); ch.kill();
const bad = result.external.length || errs.length || ["pc", "mobile"].some((k) => result[k].overflowX > 0 || result[k].replacementChars || !result[k].bandVisible);
process.exit(bad ? 1 : 0);
