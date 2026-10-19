// Top 3 Crypto 보드. 데이터는 03_백엔드 API만 읽는다(/api/board, /api/analyses, /api/engine, /api/study).
// 외부에서 온 글자(뉴스 제목·해설·공부 노트)는 항상 esc()로 이스케이프하고, 링크는 http(s)만 허용한다.
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "#");
  const DIR = { 1: ["Long", "▲", "up"], "-1": ["Short", "▼", "down"], 0: ["방향 없음", "·", "zero"] };
  const dirOf = (d) => DIR[String(d ?? 0)] || DIR[0];
  const sign = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n);
  const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "zero");
  const pct = (a, b) => (b ? `${a}/${b} (${((100 * a) / b).toFixed(1)}%)` : "-");
  let board = null;
  let selected = null;
  const C = window.Top3Chart;
  const N15 = window.Top3Now15 || null;   // 15분 확실한 신호 글자(now15.js, 10-07)
  const V5 = window.Top3View5;            // V5 확신도·AI 분석·공포탐욕 사건 계산(view5.js, 10-14). 글자는 날것이라 쓸 때 esc()
  let chartData = null, chartSym = null;
  let chartState = C.SPLIT(), chartDays = 3;
  try {
    const saved = JSON.parse(localStorage.getItem("top3-chart") || "null");
    if (saved) { chartState = C.normalize(saved.state); chartDays = [1, 3, 7].includes(saved.days) ? saved.days : 3; }
  } catch (e) { /* 저장 불가 무시 */ }

  // ---------- 데이터 출처 ----------
  // 맥에서 직접 열면 같은 서버의 /api. Vercel 배포본(config.js 의 TOP3_CONFIG 가 있을 때)은 Vercel 이 같은 주소의 /api 를
  // 맥의 Funnel 로 넘겨 주고(vercel.json rewrites), 안 되면(맥이 꺼짐) 1시간마다 저장한 스냅샷(data/)을 쓴다.
  // 한 번 고칠 때(1분마다) 출처는 보드 요청이 정하고 그래프·지난 분석도 같은 출처를 쓴다(10-04 GPT-6.1 Sol: 실시간 카드와
  // 저장본 그래프가 한 화면에 섞였음). 실시간 중 다른 요청이 연결 오류로 실패하면 화면 전체를 저장본으로 다시 그린다.
  const CFG = window.TOP3_CONFIG || null;
  let mode = "live", liveRetryAt = 0, snapMeta = null;
  let decision = null;    // 보드 요청이 출처를 정하는 동안의 약속(load 가 만든다). 다른 요청은 이것을 기다린다(10-04 Fable)
  let shownMode = null;   // 화면에 마지막으로 그린 출처. 바뀌면 보이는 탭을 다시 그린다
  async function fetchJSON(url, ms) {
    const ctl = new AbortController();
    const tm = setTimeout(() => ctl.abort(), ms || 15000);
    try {
      const r = await fetch(url, { signal: ctl.signal, cache: "no-store" });
      if (!r.ok) { const e = new Error(`HTTP ${r.status}`); e.status = r.status; throw e; }
      return await r.json();
    } finally { clearTimeout(tm); }
  }
  // 연결 실패(네트워크·시간 초과·5xx·프록시 오류)만 '실시간 끊김'으로 본다. 4xx 는 서버가 답한 것이라 그대로 오류
  const connFail = (e) => !e.status || e.status >= 500;
  function snapPath(url) {
    const u = new URL(url, location.origin), p = u.pathname, q = u.searchParams;
    if (p === "/api/board") return "data/board.json";
    if (p === "/api/engine") return "data/engine.json";
    if (p === "/api/replay") return "data/replay.json";
    if (p === "/api/study") return "data/study.json";
    if (p.startsWith("/api/study/")) return `data/study/${p.slice(11)}.json`;
    if (p.startsWith("/api/chart/")) return `data/chart_${p.slice(11)}_${q.get("days") || 3}.json`;
    if (p === "/api/analyses") {
      const sym = q.get("symbol"), all = q.get("all_versions") === "true";
      return `data/analyses${sym ? "_" + sym : ""}${all ? "_all" : ""}.json`;
    }
    return null;
  }
  let snapNote = "";      // 저장본을 보는 중이면 그 안내(10-13 v4: 화면 위 안내 띠 대신 '⚠ 상태' 탭에)
  function setMode(kind) {
    mode = kind;
    const changed = shownMode !== null && shownMode !== kind;
    shownMode = kind;
    if (kind === "snapshot") {
      const saved = (snapMeta && snapMeta.saved_kst) || "";
      const age = snapMeta && snapMeta.saved_at ? Math.round((Date.now() - Date.parse(snapMeta.saved_at)) / 60e3) : null;
      const ageTxt = age != null && age >= 75 ? ` 저장한 지 ${age >= 120 ? `${Math.floor(age / 60)}시간` : `${age}분`} 지나 그 뒤 데이터는 없습니다.` : "";
      snapNote = `실시간 데이터에 연결되지 않아 <b>${esc(saved)}</b>에 저장한 화면을 보여 줍니다(1시간마다 저장).${esc(ageTxt)} 연결되면 저절로 바뀝니다. <button type="button" class="linkbtn" data-retry-live>지금 다시 연결</button>`;
    } else snapNote = "";
    updateStatusTab();
    if (changed) rerenderVisible();
  }
  // 출처가 바뀌면 지금 보이는 탭(지난 분석·데이터 상태·공부)도 같은 출처로 다시 그린다. [지금] 탭은 load 가 그린다
  function rerenderVisible() {
    studyEpoch++;   // 공부 탭은 지우지 않고 다시 받아 내용이 달라졌을 때만 바꾼다(7절 9 C)
    if (!$("#view-ai").hidden) loadHistory();
    if (!$("#view-status").hidden) loadStatus();
    if (!$("#view-study").hidden) loadStudyIndex();
  }
  async function fromSnapshot(url) {
    const sp = snapPath(url);
    if (!sp) throw new Error("스냅샷 없음");
    if (!snapMeta || sp === "data/board.json") {   // 1분마다 저장 시각도 새로(매시 배포 반영)
      try { snapMeta = await fetchJSON("data/meta.json"); } catch (e) { snapMeta = snapMeta || {}; }
    }
    return fetchJSON(sp);
  }
  async function getJSON(url, decide) {
    if (!CFG) return fetchJSON(url);
    const live = CFG.liveApi + url;
    if (decide) {   // 보드 요청: 이번 화면의 출처를 정한다
      if (mode === "live" || Date.now() > liveRetryAt) {
        try { const d = await fetchJSON(live, 10000); setMode("live"); return d; }
        catch (e) { liveRetryAt = Date.now() + 5 * 60e3; }
      }
      const d = await fromSnapshot(url);
      setMode("snapshot");
      return d;
    }
    if (decision) await decision;   // 출처가 정해질 때까지 기다린다
    if (mode === "live") {
      try { return await fetchJSON(live, 10000); }
      catch (e) {
        if (!connFail(e)) throw e;
        // 실시간이 끊김: 이 요청 하나만 저장본으로 채우지 않고(섞인 화면) 화면 전체를 저장본으로 다시 그린다
        liveRetryAt = Date.now() + 5 * 60e3;
        mode = "snapshot"; setTimeout(load, 0);
        e.switching = true;
        throw e;
      }
    }
    return fromSnapshot(url);
  }
  // 저장본을 보고 있으면 저장 당시의 '지연 아님'을 그대로 믿지 않고 지금 시각으로 다시 본다
  const snapshotMode = () => !!CFG && mode === "snapshot";

  // ---------- 설정(10-06 호연 P3, 이 기기에만 저장) ----------
  // 10-12: 알림은 공식 매매 트리거만. verify = 검증 화면(트리거 성적·지표·이전 방식 기록) 보기, 기본 꺼짐
  const SET_DEFAULT = { theme: "dark", palette: "kr", coin: "BTCUSDT", days: "3", notify: false, notifyCoins: ["BTCUSDT", "ETHUSDT", "XRPUSDT"], verify: false };
  let settings = { ...SET_DEFAULT };
  try {
    const old = localStorage.getItem("top3-theme");   // 예전 버튼 테마 값을 이어받음
    settings = { ...SET_DEFAULT, ...(old ? { theme: old } : {}), ...JSON.parse(localStorage.getItem("top3-settings") || "{}") };
  } catch (e) { /* 저장 불가 무시 */ }
  const saveSettings = () => { try { localStorage.setItem("top3-settings", JSON.stringify(settings)); } catch (e) { /* 무시 */ } };
  const sysDark = window.matchMedia("(prefers-color-scheme: dark)");
  function setTheme(t) {
    document.documentElement.dataset.theme = t === "system" ? (sysDark.matches ? "dark" : "light") : t;
  }
  sysDark.addEventListener("change", () => { if (settings.theme === "system") setTheme("system"); });
  document.documentElement.dataset.palette = settings.palette;
  if (!selected) selected = settings.coin;
  const query = new URLSearchParams(location.search);
  const qTheme = query.get("theme"); // 스크린샷용: ?theme=light
  const qInd = query.get("ind");      // 스크린샷용: ?ind=macd,sto (고른 상태), ?days=7
  if (qInd) chartState = C.normalize({ mode: "pick", sel: qInd.split(",") });
  if (["1", "3", "7"].includes(query.get("days"))) chartDays = Number(query.get("days"));
  setTheme(qTheme || settings.theme);
  // 검증 화면(설정에서 켬, ?verify=1): AI 분석 탭 목차 '7 검증'(트리거 성적·지표 상태·이전 방식 기록)과 성적 리포트의 결과 열
  // 공개 범위(10-13 결정 84-A): 보드 응답의 scope 가 "local"(맥에서 직접 연 화면)일 때만 쓸 수 있다.
  // 공개 화면(Vercel·Funnel·저장본)과 scope 가 없는 옛 저장본은 설정·주소와 상관없이 꺼짐(서버도 그 자료를 내려주지 않음)
  if (query.get("verify") === "1") settings.verify = true;   // 주소로 켜면 설정 버튼도 켜짐(저장은 버튼을 누를 때만)
  const isLocal = () => !!board && board.scope === "local";
  const verifyOn = () => isLocal() && !!settings.verify;
  // 검증 화면의 설명 문장(조건·채점)은 공개 번들에 두지 않고 맥에서 연 보드 응답(verify_text)으로만 받는다(84-A)
  const VT = (k) => (board && board.verify_text && board.verify_text[k]) || "";
  function applyVerify() {
    const on = verifyOn(), local = isLocal();
    document.querySelectorAll("[data-vt]").forEach((el) => { el.textContent = VT(el.dataset.vt); });
    const z = $("#verify-zone");
    if (z) z.hidden = !on;
    document.querySelectorAll(".vz-link").forEach((el) => { el.hidden = !on; });
    const row = $("#verify-row");
    if (row) row.hidden = !local;
    document.querySelectorAll(".local-only").forEach((el) => { el.hidden = !local; });
  }
  applyVerify();

  // ---------- 탭 ----------
  const TITLES = { now: "홈", ai: "AI 분석", study: "공부", settings: "설정", status: "데이터 상태" };
  const GUIDE = "08_사용_방법.md";
  let viewNow = "now";
  function showView(view) {
    if (view === "record" || view === "history") { showView("settings"); setTimeout(() => $("#records").scrollIntoView({ block: "start" }), 30); return; }
    if (view === "guide") { showView("study"); openStudy(GUIDE); return; }
    if (!TITLES[view]) view = "now";
    viewNow = view;
    document.querySelectorAll(".tabs button").forEach((x) => { const on = x.dataset.view === view; x.classList.toggle("on", on); x.setAttribute("aria-selected", on); });
    for (const v of Object.keys(TITLES)) $(`#view-${v}`).hidden = v !== view;
    // 탭을 열 때 그 탭을 그린다. 60초 새로 고침(renderNow)은 보이는 탭만 그리므로 숨은 탭의 새 자료는 여기서 반영된다(10-14 7절 9 E)
    if (view === "ai") { if (verifyOn()) loadHistory(); if (board) renderAiTab(); }
    if (view === "now" && board) { renderNews(board); renderNowTab(); loadChart(true); }
    if (view === "study") loadStudyIndex();
    if (view === "status") { renderStatusAlerts(); loadStatus(); }
    if (view === "settings") { renderSettings(); if (board) renderRecords(); }
    syncBrand();
  }
  // AI 분석 탭의 절로 이동(목차·홈의 '자세히'): 절 제목이 고정 상단 바 바로 아래에 오게 하고 잠깐 강조한다(10-13 v4)
  let goTarget = null, goAt = 0;
  function goSection(n) {
    if (viewNow !== "ai") showView("ai");
    goTarget = String(n); goAt = Date.now();
    document.querySelectorAll("#ai-toc button").forEach((b) => b.classList.toggle("on", b.dataset.sec === String(n)));
    const el = document.getElementById(`ai-sec-${n}`);
    if (!el || el.offsetParent === null) return;
    const top = el.getBoundingClientRect().top + window.scrollY - ($(".gnav").offsetHeight + 16);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    el.setAttribute("tabindex", "-1"); el.focus({ preventScroll: true });
  }
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => { window.scrollTo({ top: 0 }); showView(b.dataset.view); }));
  $("#ai-toc").addEventListener("click", (e) => { const b = e.target.closest("[data-sec]"); if (b) goSection(+b.dataset.sec); });
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-goto-sec]"); if (b) { e.preventDefault(); window.scrollTo({ top: 0 }); goSection(+b.dataset.gotoSec); } });
  // 목차에 지금 읽는 절 표시
  window.addEventListener("scroll", () => {
    if (viewNow !== "ai") return;
    const lim = $(".gnav").offsetHeight + 24;   // 목차 이동 위치(상단 바 + 16px)보다 조금 아래까지
    let cur = null;
    document.querySelectorAll("#ai-doc .air-h").forEach((h) => { if (h.offsetParent !== null && h.getBoundingClientRect().top <= lim) cur = h.id.slice(7); });
    const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
    if (goTarget && (Date.now() - goAt < 1500 || atBottom)) cur = goTarget;   // 끝 절은 맨 위까지 못 올라오므로 누른 절을 유지
    else goTarget = null;
    document.querySelectorAll("#ai-toc button").forEach((b) => b.classList.toggle("on", b.dataset.sec === cur));
  }, { passive: true });
  document.querySelectorAll("#ai-coin button").forEach((b) => b.addEventListener("click", () => {
    if (selected === b.dataset.sym) return;
    selected = b.dataset.sym;
    if (board) { renderAiReport(); renderIndStatus(); renderOldEvidence(); renderRefLine(); }
    syncBrand();
    chartSym = null;   // 홈 그래프는 홈으로 돌아갈 때 이 코인으로 다시 그린다
  }));
  document.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); window.scrollTo({ top: 0 }); showView(a.dataset.open); }));

  // ---------- 공포탐욕 30일 선 (SVG, 외부 라이브러리 없음) ----------
  function fngSVG(series) {
    if (!series || series.length < 2) return "";
    const W = 300, H = 120, P = 8;
    const x = (i) => P + (i / (series.length - 1)) * (W - 2 * P);
    const y = (v) => H - P - (v / 100) * (H - 2 * P);
    const d = series.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s.value).toFixed(1)}`).join("");
    return `<svg class="fng-chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="공포탐욕지수 30일">
      <line class="grid50" x1="${P}" x2="${W - P}" y1="${y(50)}" y2="${y(50)}" vector-effect="non-scaling-stroke"/>
      <path class="line" d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
  }

  const fmtPrice = (sym, v) => v == null ? "-" : "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: sym === "XRPUSDT" ? 4 : 2 });
  const fmtNum = (v) => v == null ? "-" : Math.abs(v) >= 100 ? Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 }) : Number(v).toFixed(Math.abs(v) >= 1 ? 2 : 4);

  // ---------- 홈(10-13 v4, 호연 P5·P6): 뉴스 띠 → 확신도 카드 3개 → 지표 그래프 → AI 분석 · 근거 ----------
  const V4 = () => (board && board.v4) || null;
  const TREND = { 1: "Long", "-1": "Short", 0: "Neutral" };
  const trendOf = (d) => TREND[String(d ?? 0)] || "Neutral";
  const RES = { success: ["성공", "ok"], fail: ["실패", "ng"], open_success: ["진행 중 · 기준 넘음", "ok"], open: ["진행 중", "muted"] };
  const kstOf = (ms, sec) => { if (ms == null) return "-"; const i = new Date(Number(ms) + 9 * 3600e3).toISOString(); return `${i.slice(5, 10)} ${i.slice(11, sec ? 19 : 16)}`; };
  const isoKst = (iso) => (iso ? kstOf(Date.parse(iso)) : "-");
  const pctTxt = (v) => (v == null ? "-" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}%`);
  const fmtU = (p) => (p == null ? "-" : Number(p).toLocaleString("en-US", { minimumFractionDigits: p >= 1000 ? 1 : p >= 10 ? 2 : 4, maximumFractionDigits: p >= 1000 ? 1 : p >= 10 ? 2 : 4 }));
  const CF = (sym) => { const v = V4(); return (v && v.confidence && v.confidence[sym]) || null; };
  const held = (c) => !c || c.score == null;   // 자료 충족률이 낮아 숫자·방향을 보류(confidence.py MIN_COVERAGE)
  const scoreTxt = (c) => (held(c) ? "–" : sign(c.score));
  const confCls = (c) => (held(c) || Math.abs(c.score) < 10 ? "zero" : cls(c.score));   // |값| < 10은 중립(회색)
  const supportTxt = (c) => (c.support_pct == null ? "" : `지지 ${c.support_pct}% · `);
  const KIND = { scheduled: "정기 분석", on_demand: "트리거 확인 분석", manual: "분석" };
  const signed2 = (v, sym) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: sym === "XRPUSDT" ? 4 : 2 });
  const xTxt = (x) => (x === 0 ? "0" : `${x > 0 ? "+" : "−"}${Math.abs(x)}`);
  const ARW = (x) => (x == null ? ["제외", "muted"] : x > 0 ? [`▲ ${xTxt(x)}`, "up"] : x < 0 ? [`▼ ${xTxt(x)}`, "down"] : ["· 0", "zero"]);
  let loadError = false;
  // 홈 카드 · AI 분석 카드 · 근거 카드 · 그래프 틀(그래프 선은 loadChart)
  function renderNowTab() { renderCards(); renderAiBrief(); renderEvidence(); renderChartFrame(); }
  // AI 분석 탭(검증 화면 칸은 켜져 있을 때만 그려짐)
  function renderAiTab() { renderAiReport(); renderTrack(); renderScoring(); renderIndStatus(); renderOldEvidence(); }
  // 새 자료가 오면(60초마다) 보이는 탭만 다시 그린다. 숨은 탭은 열 때 showView 가 그린다(10-14 7절 9 E)
  function renderNow() {
    const b = board;
    if (!selected) selected = (b.symbols[0] || {}).symbol;
    renderRefLine();
    updateStatusTab();
    if (viewNow === "now") { renderNews(b); renderNowTab(); }
    if (viewNow === "ai") renderAiTab();
    if (viewNow === "settings") renderRecords();
    syncBrand();
  }
  // 로고 '3' 색(10-14 7절 3): 홈 등은 고른 코인 확신도의 방향, AI 분석 탭은 그 코인 AI 추세 방향. 중립·자료 없음은 회색(--ink-48).
  // 팔레트(빨강·파랑 / 민트·마젠타)는 --up·--down 이 따라가므로 변수로만 건다
  function syncBrand() {
    let d = 0;
    try {
      const v = V4();
      if (board && viewNow === "ai") d = V5.aiDir(v && v.ai && v.ai[selected] && v.ai[selected].latest && v.ai[selected].latest.body);
      else if (board) d = V5.confDir(CF(selected));
    } catch (e) { d = 0; }
    document.documentElement.style.setProperty("--brand3", d > 0 ? "var(--up)" : d < 0 ? "var(--down)" : "var(--ink-48)");
  }
  // 상단 바 오른쪽 기준 줄: 확신도·가격·Core Condition이 기준으로 삼은 마지막 15분봉(15분마다 바뀜)
  function renderRefLine() {
    const c = CF(selected) || CF("BTCUSDT");
    const t = c && c.ref_kst ? String(c.ref_kst).slice(5) : (board && board.t_close_kst) || "";
    $("#ref-line").textContent = t ? `바이낸스 현물 · ${t} KST 기준` : "바이낸스 현물";
    $("#ref-line").title = "확신도·가격·Core Condition이 기준으로 삼은 마지막 15분봉 마감 시각입니다. 15분마다 바뀝니다.";
  }
  // 상태 이상(자료·분석 지연, 저장본 보기, 그래프 자료 멈춤·실패, 확신도 계산 지연·실패, AI 실패)이면 '⚠ 상태' 탭을 띄운다(10-13 v4: 경고 띠 대신)
  let chartStaleNote = "", chartErrNote = "";
  function statusItems() {
    const out = ((board && board.alerts) || []).map((a) => esc(a.text));
    if (loadError) out.push("자료를 불러오지 못했습니다. 1분 뒤 다시 시도합니다.");
    if (snapNote) out.push(snapNote);
    if (chartStaleNote) out.push(esc(chartStaleNote));
    if (chartErrNote) out.push(esc(chartErrNote));
    const v = V4();
    if (v && !snapshotMode()) {   // 저장본은 위 snapNote가 이미 알림
      const gen = Date.parse(v.generated_at || "");
      const age = Number.isFinite(gen) ? Math.round((Date.now() - gen) / 60e3) : null;
      if (age == null || age > 35) out.push(esc(`확신도·Core Condition·AI 분석 자료가 ${age == null ? "아직 없습니다" : `${age}분 전 것입니다`}(15분마다 바뀌어야 함, 엔진 확인 필요).`));
    }
    if (v && !v.confidence) out.push("확신도 자료가 없습니다. 엔진이 새 버전으로 한 번 돈 뒤 채워집니다.");
    for (const [sym, why] of Object.entries((v && v.confidence && v.confidence._errors) || {})) out.push(esc(`${sym.replace("USDT", "")} 확신도: ${why}.`));
    // AI 분석: 사용 한도·시간 초과 같은 사유, 다시 시도할 시각, Claude로 대신 분석했는지(10-14 7절 10)
    if (v && v.ai) V5.aiStatusLines(v.ai).forEach((t) => out.push(esc(t)));
    return out;
  }
  function updateStatusTab() {
    const n = statusItems().length, t = $("#tab-status");
    t.hidden = !n;
    t.textContent = n ? `⚠ 상태 ${n}` : "⚠ 상태";
    renderStatusAlerts();
  }
  function renderStatusAlerts() {
    const items = statusItems();
    $("#status-alerts").innerHTML = items.length ? items.map((h) => `<div class="alert" role="status">⚠ ${h}</div>`).join("") : `<p class="fine">지금은 이상이 없습니다.</p>`;
  }
  $("#status-alerts").addEventListener("click", (e) => { if (e.target.closest("[data-retry-live]")) { liveRetryAt = 0; mode = "live"; load(); } });

  // 24시간 창 결과 글: "성공 +1.4%" · "실패 −0.3%" · "진행 중"(검증 화면에서만 쓰임)
  function fix24Txt(r) {
    const f = V5.fix24Row(r);
    return f.pct == null ? f.word : `${f.word} ${pctTxt(f.pct)}`;
  }
  // 설정 › 성적 리포트(10-13 v4 P6): 매매 트리거(Signal) 기록. 결과(채점)는 검증 화면을 켰을 때만
  function renderRecords() {
    const v = V4(), body = $("#rec-body");
    if (!v) { body.innerHTML = `<p class="muted">트리거 데이터가 아직 없습니다.</p>`; return; }
    $("#rec-meta").textContent = v.live_start ? `${isoKst(v.live_start)} KST 운영 시작부터` : "";
    const rows = (v.recent && v.recent.official) || [];
    const vOn = verifyOn();
    const link = vOn ? `<p class="fine"><button type="button" class="linkbtn" data-goto-sec="7">트리거 성적 리포트 → AI 분석 › 7 검증</button></p>` : "";
    if (!rows.length) { body.innerHTML = `<p class="muted">아직 매매 트리거가 없습니다.</p>${link}`; return; }
    body.innerHTML = `<table class="t sig"><tr><th>시각(KST)</th><th>코인</th><th>방향</th><th>Open U$</th>${vOn ? "<th>결과</th><th>최대수익률</th><th>최대 손실</th><th>다음 트리거 때</th><th>기준</th><th>24시간 창</th>" : ""}</tr>${rows.map((r) => {
      const [rt, rc] = RES[r.result] || ["-", "muted"];
      return `<tr><td class="num">${esc(kstOf(r.issued_at, true))}</td><td><b>${esc(r.short)}</b></td>
        <td class="${r.dir > 0 ? "up" : "down"}">${r.dir > 0 ? "Long" : "Short"}</td><td class="num">${fmtU(r.entry)}</td>${vOn ? `<td class="${rc}">${rt}</td>
        <td class="num">${pctTxt(r.mfe_net_pct)}</td><td class="num">${r.mae_pct == null ? "-" : `−${r.mae_pct}%`}</td><td class="num">${pctTxt(r.ret_net_pct)}</td><td class="num">${r.thr_pct == null ? "-" : `${esc(r.thr_pct)}%`}</td><td class="num">${esc(fix24Txt(r))}</td>` : ""}</tr>`;
    }).join("")}</table>${link}`;
  }

  // 확신도 카드(10-14 V5 7절 2): 이름·가격 한 줄 → '확신도'(고른 카드만) · 우세 쪽 % · 7일 가격선 → 라벨 + 묶음 요약. 누르면 그래프·AI 분석·근거가 그 코인으로
  // 큰 숫자 = 우세 쪽 %(conf_v2 side_pct). 색: Long --up · Short --down · 중립 회색. 옛 자료(conf_v1)면 예전 꼴(부호 있는 점수)
  function sparkSVG(s) {
    const L = V5.sparkLayout(s.spark, 160, 64);
    if (!L) return `<div class="kc-spark" aria-hidden="true"></div>`;
    return `<div class="kc-spark"><svg viewBox="0 0 ${L.W} ${L.H}" role="img" aria-label="최근 7일 가격(4시간 종가)"><path class="line" d="${L.d}"/><circle class="end" cx="${L.ex.toFixed(1)}" cy="${L.ey.toFixed(1)}" r="3"/></svg><span class="kc-7d">7일</span></div>`;
  }
  function renderCards() {
    const fsym = document.activeElement && document.activeElement.closest && document.activeElement.closest("#cards .kcard") ? document.activeElement.dataset.sym : null;
    $("#cards").innerHTML = board.symbols.map((s) => {
      const mk = s.market, c = CF(s.symbol), on = s.symbol === selected, cv = V5.confView(c), sub = V5.confSub(c);
      const px = mk ? `<b class="num">${fmtPrice(s.symbol, mk.price)}</b> <span class="${cls(mk.chg_24h_pct)} num">${signed2(mk.chg_24h, s.symbol)} (${mk.chg_24h_pct > 0 ? "+" : ""}${mk.chg_24h_pct}%)</span>` : "";
      const lab = c ? (cv.label || (cv.held ? "자료 부족" : "")) : "자료 없음";
      const extra = cv.v === 1 && cv.held && c ? ` <span class="kc-grp">자료 ${esc(c.coverage_pct)}%</span>` : sub.text ? ` <span class="kc-grp${sub.note ? " note" : ""}" title="${esc(sub.text)}">${esc(sub.text)}</span>` : "";
      const spoken = c ? (cv.held ? "확신도 자료 부족" : `확신도 ${cv.side ? cv.side + " " : ""}${cv.big}${cv.unit}`) : "";
      return `<article class="tile kcard${on ? " sel" : ""}" data-sym="${esc(s.symbol)}" tabindex="0" role="button" aria-pressed="${on}" aria-label="${esc(s.name)} 고르기${spoken ? " · " + esc(spoken) : ""}">
        <div class="kc-top"><span class="kc-name"><b>${esc(s.short)}</b> · ${esc(s.name)}</span><span class="kc-px">${px}</span></div>
        <div class="kc-mid">
          <div class="kc-main"><div class="kc-l"${on ? "" : ' aria-hidden="true"'}>확신도</div>
            <div class="kc-big num ${cv.cls}${cv.held ? " held" : ""}"><span class="kc-n">${esc(cv.big)}</span>${cv.unit ? `<span class="kc-pct">${cv.unit}</span>` : ""}</div></div>
          ${sparkSVG(s)}
        </div>
        <div class="kc-lab"><span class="kc-lbl">${esc(lab)}</span>${extra}</div>
      </article>`;
    }).join("");
    document.querySelectorAll("#cards .kcard").forEach((el) => {
      const pick = () => {
        if (selected === el.dataset.sym) return;
        selected = el.dataset.sym;
        renderCards(); renderAiBrief(); renderEvidence(); renderChartFrame(); renderRefLine(); syncBrand(); loadChart();
        const again = document.querySelector(`#cards .kcard[data-sym="${selected}"]`);
        if (again) again.focus({ preventScroll: true });   // 다시 그린 카드에 초점을 돌려준다(키보드 사용)
      };
      el.addEventListener("click", pick);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
    if (fsym) { const el = document.querySelector(`#cards .kcard[data-sym="${fsym}"]`); if (el) el.focus({ preventScroll: true }); }
  }

  function coreTxt(sym) {
    const v = V4(), c = v && v.core && v.core[sym];
    return !c ? `<span class="muted">-</span>` : c.state ? `<span class="${cls(c.state)}">충족 · ${c.state > 0 ? "Long" : "Short"}</span>` : `<span class="muted">미충족</span>`;
  }
  // 홈 AI 분석 카드(10-14 V5 7절 4): Trend Direction · 뉴스 방향 · Core Condition · 요약 → AI가 설명한 비중 상위 3개 → 엇갈림(있을 때만)
  // → 근거 카드보다 120px 넘게 짧으면 'AI 예상 범위'(AI 추정)를 아래에 더한다(fitAiRange)
  const dirSpan = (d, txt) => `<span class="${V5.dirCls(d)}">${esc(txt)}</span>`;
  function factorBars(fw) {
    const rows = V5.topFactors(fw, 3);
    if (!rows.length) return "";
    const max = rows[0].pct || 1;
    return `<div class="fw"><div class="fw-h">AI가 설명한 비중</div>${rows.map((r) => {
      const [, ar, k] = dirOf(r.dir);
      return `<div class="fw-r"><span class="fw-n">${esc(r.name)} <span class="fw-a ${k}" title="${esc(V5.dirWord(r.dir))}">${ar}</span></span><span class="fw-bar"><i class="${k}" style="width:${Math.max(4, Math.round((r.pct / max) * 100))}%"></i></span><span class="fw-p num">${esc(r.pct)}%</span></div>`;
    }).join("")}</div>`;
  }
  // 'AI 예상 범위' 칸의 글(홈 카드 아래, 홈 AI 카드가 짧을 때만 보임 / 데이터가 없으면 ''. 값 자체는 AI 분석 1절과 같다)
  function rangeCard(b) {
    const ch = b.expected_change_pct || {}, pr = b.expected_price_range || {};
    if (ch.low == null && pr.low == null) return "";
    return `<div class="ai-range" id="ai-range" hidden><div class="fw-h">AI 예상 범위 ${EST}</div>
      <div class="air-kv"><span class="k">Expected Change</span><span class="num">${pctTxt(ch.low)} – ${pctTxt(ch.high)}</span>
      <span class="k">Expected Price Range</span><span class="num">$${fmtU(pr.low)} – $${fmtU(pr.high)}</span></div></div>`;
  }
  function renderAiBrief() {
    const v = V4(), s = board.symbols.find((x) => x.symbol === selected) || board.symbols[0];
    const node = s && v && v.ai && v.ai[s.symbol], a = node && node.latest;
    $("#ai-brief-meta").textContent = a ? `${s.short} · ${KIND[a.kind] || "분석"} ${a.created_kst}` : (s ? s.short : "");
    if (!a) {
      $("#ai-brief-body").innerHTML = `<div class="air-kv"><span class="k">Core Condition</span><span>${coreTxt(s.symbol)}</span></div><p class="muted">${esc(s.short)} AI 분석은 아직 없습니다. 하루 2번(09·21시)과 Core Condition이 켜질 때 만듭니다.</p>`;
      return;
    }
    const b = a.body || {}, nb = V5.newsBias(b);
    const dv = V5.divergenceText(V5.divergence(CF(s.symbol), b));
    $("#ai-brief-body").innerHTML = `<div class="air-kv">
        <span class="k">Trend Direction</span><b class="${cls(DIR_OF_TREND[b.trend_direction])}">${esc(b.trend_direction)}</b>
        ${nb ? `<span class="k">뉴스 방향</span><span>${nb.none ? `<span class="muted">${esc(nb.text)}</span>` : `<b class="${nb.cls}">${esc(nb.text)}</b> <span class="muted">· 기사 ${esc(nb.n)}건</span>`}</span>` : ""}
        <span class="k">Core Condition</span><span>${coreTxt(s.symbol)}</span>
      </div><p class="brief-text">${esc(b.summary_reasoning)}</p>${factorBars(b.factor_weights)}${dv ? `<p class="diverge">${esc(dv)}</p>` : ""}${rangeCard(b)}`;
  }
  $("#ai-brief-more").addEventListener("click", () => { window.scrollTo({ top: 0 }); goSection(1); });
  // 근거 카드가 AI 카드보다 120px 넘게 길고 두 카드가 나란히 놓였을 때만 'AI 예상 범위'를 보인다. 먼저 숨긴 채 카드 자연 높이를 잰다
  function fitAiRange() {
    const box = $("#ai-range"), br = $("#ai-brief"), ev = $("#evidence");
    if (!box || !br || !ev || $("#view-now").hidden) return;
    box.hidden = true;
    if (Math.abs(ev.getBoundingClientRect().top - br.getBoundingClientRect().top) > 40) return;   // 한 열(위아래로 쌓임)
    const prev = br.style.alignSelf;
    br.style.alignSelf = "start";
    const natural = br.offsetHeight;
    br.style.alignSelf = prev;
    box.hidden = !(ev.offsetHeight - natural > 120);
  }
  let fitTimer = null;
  window.addEventListener("resize", () => { clearTimeout(fitTimer); fitTimer = setTimeout(fitAiRange, 150); });

  // 근거 신호 줄(홈 근거 카드 · AI 분석 2절 공통): 묶음(기술 지표 · 시장 자료)별로 모아 낸다. signals 에 group 이 없는 옛 자료·간략 응답은 한 묶음처럼 평평하게
  const GROUPS = [["tech", "기술 지표"], ["market", "시장 자료"]];
  function groupRows(c, rowFn, headFn) {
    const sg = (c && c.signals) || [];
    if (!sg.length) return "";
    if (!sg.some((r) => r.group)) return sg.map((r) => rowFn(r)).join("");
    let out = "";
    GROUPS.forEach(([key, name]) => {
      const rows = sg.filter((r) => r.group === key);
      if (!rows.length) return;
      out += headFn(key, name, (c.groups && c.groups[key]) || null) + rows.map((r) => rowFn(r)).join("");
    });
    return out;
  }
  // 묶음 제목 오른쪽 글: +86.5(방향 색) / 점수에 안 쓴 묶음은 '자료 부족'
  function groupScoreHtml(g) {
    if (!g) return "";
    if (g.used === false || g.score == null) return `<span class="muted">${g.coverage_pct != null ? `자료 ${esc(g.coverage_pct)}% · ` : ""}점수에 안 씀</span>`;
    const d = V5.groupDir(g.score);
    return `<span class="${V5.dirCls(d)}">${esc(V5.fmt1(g.score))}</span>`;
  }
  // 뉴스 줄의 값: 쓴 뉴스 방향(AI 분석의 news_bias) · 그 밖은 신호의 읽기 글
  function sigNote(r, a) {
    if (r.key === "news" && r.used) {
      const nb = V5.newsBias(a && a.body);
      return nb && !nb.none ? `${nb.text} · 기사 ${nb.n}건` : (r.value || r.note || "");   // 엔진 값에는 '긍정 +1 · 기사 5건 · 분석 시각'이 들어 있음
    }
    return r.note || "";
  }
  // "Long 77%": 큰 숫자 꼴(중립은 방향 없이 "50%"). 옛 자료는 "+24"
  const confBigHtml = (cv) => `${cv.side && !cv.held && cv.dir !== 0 ? `${esc(cv.side)} ` : ""}${esc(cv.big)}${cv.unit ? `<small>${cv.unit}</small>` : ""}`;

  // 홈 근거 카드(10-14 V5 7절 5): 확신도(Long 77%) · note → 묶음 두 줄 → 신호 줄(무게 · 읽기 · 방향 · 'AI 25%') → AI 근거 → 계산식
  function renderEvidence() {
    const s = board.symbols.find((x) => x.symbol === selected), c = CF(selected);
    const v = V4(), a = v && v.ai && v.ai[selected] && v.ai[selected].latest;
    $("#ev-meta").textContent = c ? `${s ? s.short + " · " : ""}${String(c.ref_kst || "").slice(5)} 자료` : "";
    if (!c) { $("#ev-body").innerHTML = `<p class="muted">확신도를 계산할 자료가 아직 없습니다.</p>`; fitAiRange(); return; }
    const cv = V5.confView(c), fw = a && a.body && a.body.factor_weights;
    const row = (r) => {
      const [t, k] = ARW(r.used ? r.x : null), ap = V5.aiPct(fw, r.key);
      return `<tr class="${r.used ? "" : "off"}"><td class="nm">${esc(r.name)}<span class="w">×${esc(r.w)}</span></td><td class="nt">${esc(sigNote(r, a))}</td><td class="dx ${k}">${t}</td><td class="aw">${ap == null ? "" : `AI ${esc(ap)}%`}</td></tr>`;
    };
    const head = (key, name, g) => `<tr class="grp"><td colspan="3">${esc(name)}</td><td class="gs num">${groupScoreHtml(g)}</td></tr>`;
    const rows = groupRows(c, row, head);
    const ai = a ? `<div class="ev-ai"><div class="ev-ai-h">AI 근거 <span class="fine">Confidence ${esc(a.body.confidence_level)}, ${esc(a.body.confidence_pct)}% · ${esc(a.created_kst)} 분석</span></div>
        <ul>${(a.body.key_signals || []).slice(0, 2).map((x) => `<li class="ks">${esc(x)}</li>`).join("")}${(a.body.risks || []).slice(0, 2).map((x) => `<li class="rk">${esc(x)}</li>`).join("")}</ul></div>` : "";
    $("#ev-body").innerHTML = `<div class="ev-top"><span class="ev-score num ${cv.cls}">${confBigHtml(cv)}</span><span class="ev-lab">${esc(cv.label)}</span>${cv.held && c.coverage_pct != null && !c.note ? `<span class="fine">자료 ${esc(c.coverage_pct)}%</span>` : ""}</div>
      ${c.note ? `<p class="ev-note">${esc(c.note)}</p>` : ""}
      ${rows ? `<table class="evt">${rows}</table>` : ""}${ai}${c.formula ? `<div class="formula num">${esc(c.formula)}</div>` : ""}`;
    fitAiRange();
  }
  $("#ev-more").addEventListener("click", () => { window.scrollTo({ top: 0 }); goSection(2); });

  // 검증 화면 › 지표별 값(2차 회의 기술 점수의 근거). 홈 근거 카드는 renderEvidence(확신도)
  // 검증 화면 칸들(renderOldEvidence·renderIndStatus·renderScoring·renderTrack)은 켜져 있을 때만 그린다. 켜는 순간 설정 버튼이 다시 그림
  function renderOldEvidence() {
    if (!verifyOn()) return;
    const s = board.symbols.find((x) => x.symbol === selected);
    $("#ev-old-title").textContent = s ? s.short : "";
    if (!s || s.score == null) {
      $("#ev-old-body").innerHTML = `<p class="muted">${esc(s ? s.label : "")} · 이 종목은 이번 분석에서 점수를 내지 않았습니다.</p>`;
      return;
    }
    const row = (i, id) => {
      const [w, ar, c] = dirOf(i.dir);
      const vals = Object.entries(i.values).map(([k, v]) => `${esc(k)} ${k.startsWith("%") ? (v == null ? "-" : Number(v).toFixed(1)) : fmtNum(v)}`).join(" · ");
      return `<tr class="ind-row"><td><span class="sw c-${id}"></span>${esc(i.name)} <span class="v">${esc(i.tf)}</span><div class="v">${vals}</div><div class="v">${esc(i.rule)}${i.last_kst ? ` · <span class="nw">${esc(i.last_word)} ${esc(i.last_kst)}</span>` : ""}</div></td>
        <td class="d ${c}">${ar} ${w}</td></tr>`;
    };
    const [m, sto, srsi, vp] = s.indicators;
    const pair = dirOf(s.pair_dir);
    const held = s.pair_dir === 0 && sto.dir === 1 && srsi.dir === 1;   // 10-06 조건서 가짜 신호 거르기
    const pairNote = held
      ? `<tr><td colspan="2" class="ind-note">${esc(VT("held_note"))}</td></tr>`
      : s.pair_dir === 0
      ? `<tr><td colspan="2" class="ind-note">1시간 조건 비어 있음 · Stochastic과 StochRSI 방향이 같지 않음(둘이 같을 때만 성립)</td></tr>`
      : `<tr><td colspan="2" class="ind-note">1시간 조건 성립 · Stochastic·StochRSI 둘 다 ${pair[0]}</td></tr>`;
    let hint = "";
    if (!s.strong && s.score !== 0 && m.dir === s.pair_dir && s.pair_dir === vp.dir && m.dir !== 0) {
      hint += `<p class="hint">${esc(VT("seq_hint"))}</p>`;
    }
    if (s.history_hint) {
      const h = s.history_hint;
      hint = `<p class="hint">참고 기간(${esc(h.period)})에 같은 점수(${sign(h.score)})였을 때 4시간 뒤 ${esc(h.dir_word)} 비율 ${h.match_pct}% (n=${h.n}, 보합 제외). 과거 재현이며 예측이 아닙니다.</p>`;
    }
    if (s.strong && s.chase) {
      const c = s.chase, b = c.bucket;
      const mv = c.move_pct >= 0 ? `신호 방향으로 ${c.move_pct}%` : `신호 반대 방향으로 ${Math.abs(c.move_pct)}%`;
      const past = b && b.n ? ` 참고 기간(${esc(b.period)})에 같은 구간(${esc(b.label)})에서 켜진 확실한 신호는 4시간 뒤 ${b.hit4_pct ?? "-"}%(n=${b.n4 ?? "-"}), 24시간 뒤 ${b.hit24_pct ?? "-"}%(n=${b.n24 ?? "-"})가 신호 방향대로 갔습니다(보합 제외).` : "";
      hint += `<p class="hint">확실한 신호가 켜지기 전 24시간 동안 가격이 ${mv} 움직였습니다${c.warn ? `(${c.warn_pct}% 이상이라 '추격 주의')` : ""}.${past} 확실한 신호는 대부분 이미 움직인 뒤에 켜지고, 같은 방향으로 많이 움직인 뒤 켜진 신호는 반대로 움직인 뒤 켜진 신호보다 과거 성적이 낮았습니다. 과거 재현이며 예측이 아닙니다.</p>`;
    }
    $("#ev-old-body").innerHTML = `<table class="ind">${row(m, "macd")}${row(sto, "sto")}${row(srsi, "srsi")}${pairNote}${row(vp, "vpci")}</table>
      <div class="formula num">${esc(s.formula || "")}</div>${hint}`;
  }

  // ---------- AI 분석 탭(10-13 v4): 정미님 프롬프트·출력 예시(10-11)의 6대 분류를 그 이름·순서로. 목차로 절 이동 ----------
  const EST = `<span class="est">AI 추정</span>`;
  const DIR_OF_TREND = { Long: 1, Short: -1, Neutral: 0 };
  const FNG_KO = { "Extreme Fear": "극단적 공포", Fear: "공포", Neutral: "중립", Greed: "탐욕", "Extreme Greed": "극단적 탐욕" };
  // 공포탐욕 4절(10-14 V5 7절 7): 숫자는 절 제목 크기 · 그래프 최대 560×140(50 점선) · 7일마다 날짜 · 크게 움직인 날 점과 번호 · 그 아래 목록 · 지수 설명 한 줄
  function fngSVG5(L) {
    const dots = L.dots.map((d) => `<g class="fng-ev-dot"><circle cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="7.5"/><text x="${d.x.toFixed(1)}" y="${(d.y + 3.4).toFixed(1)}" text-anchor="middle">${d.n}</text></g>`).join("");
    const ticks = L.ticks.map((t) => `<line class="tick" x1="${t.x.toFixed(1)}" x2="${t.x.toFixed(1)}" y1="${L.yb}" y2="${L.yb + 4}"/><text class="ax" x="${t.x.toFixed(1)}" y="${L.H - 6}" text-anchor="${t.x < 20 ? "start" : "middle"}">${esc(t.label)}</text>`).join("");
    return `<svg class="fng-chart" viewBox="0 0 ${L.W} ${L.H}" width="${L.W}" height="${L.H}" role="img" aria-label="공포탐욕지수 최근 30일">
      <line class="grid50" x1="${L.gx1}" x2="${L.gx2}" y1="${L.y50.toFixed(1)}" y2="${L.y50.toFixed(1)}"/>
      <text class="ax" x="${L.W - 2}" y="${(L.y50 + 3.5).toFixed(1)}" text-anchor="end">50</text>
      <path class="line" d="${L.d}"/><circle class="last" cx="${L.last.x.toFixed(1)}" cy="${L.last.y.toFixed(1)}" r="3"/>${ticks}${dots}</svg>`;
  }
  function fngEventList(evs) {
    if (!evs.length) return "";
    return `<ol class="fng-evs">${evs.map((e) => {
      const move = e.prev != null && e.value != null ? `<span class="num">${esc(e.prev)} → ${esc(e.value)}</span> <span class="num ${e.cls}">(${esc(e.deltaText)})</span>` : e.value != null ? `<span class="num">${esc(e.value)}</span>` : "";
      const news = e.news.length ? `<div class="fe-news">${e.news.map((n, i) => `${i ? "" : "뉴스: "}<a href="${safeUrl(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>${n.publisher ? ` <span class="muted">(${esc(n.publisher)})</span>` : ""}`).join("</div><div class=\"fe-news\">")}</div>` : e.note ? `<div class="fe-news muted">${esc(e.note)}</div>` : "";
      return `<li><span class="evn">${e.n}</span><div><div class="fe-main"><span class="num">${esc(e.md)}</span> ${move}${e.btc ? ` · <span class="num">${esc(e.btc)}</span>` : ""}</div>${news}</div></li>`;
    }).join("")}</ol>`;
  }
  function fngBlock() {
    const f = (board && board.fng) || {};
    if (f.value == null) return `<p class="muted">공포탐욕지수 없음</p>`;
    const box = $("#ai-report-body"), w = box && box.clientWidth ? box.clientWidth - 6 : 560;
    const L = V5.fngLayout(f, w), evs = V5.fngEvents(f);
    return `<div class="fng-now"><span class="n num">${Math.round(f.value)}</span><span class="fng-cls">${esc(FNG_KO[f.classification] || f.classification || "")}</span>
      <span class="src">공포탐욕지수 · 출처 <a href="https://alternative.me/crypto/fear-and-greed-index/" target="_blank" rel="noopener noreferrer">alternative.me</a>${f.date ? ` · ${esc(f.date.slice(5))} 값 · 매일 09:00 KST 갱신` : ""}</span></div>
      ${L ? fngSVG5(L) : ""}<p class="fine">최근 30일. 점선은 50(중립).${evs.length ? " 번호 점은 크게 움직인 날이고, BTC 등락과 뉴스는 그 지수가 반영한 전날(UTC 하루) 것입니다." : ""}</p>${fngEventList(evs)}
      <p class="fine">alternative.me 지수(비트코인 중심): 변동성 25% · 거래량과 모멘텀 25% · 소셜 15% · 도미넌스 10% · 검색 10%, 설문 15%는 중단.</p>`;
  }
  // 2절 아래: 대시보드 확신도 계산 전체(지금 값까지). 홈 근거 카드의 '자세히'
  function confTable(c, a) {
    if (!c) return `<p class="muted">확신도를 계산할 자료가 아직 없습니다.</p>`;
    const cv = V5.confView(c), fw = a && a.body && a.body.factor_weights, hasFw = V5.topFactors(fw, 1).length > 0;   // 옛 AI 분석(비중 없음)이면 'AI 비중' 열을 뺀다
    const row = (r) => {
      const [t, k] = ARW(r.used ? r.x : null), ap = V5.aiPct(fw, r.key);
      return `<tr class="${r.used ? "" : "off"}"><td>${esc(r.name)}</td><td class="num">${esc(r.w)}</td><td class="num">${esc(r.value)}</td><td>${esc(sigNote(r, a))}</td><td class="dx ${k}">${t}</td>${hasFw ? `<td class="aw num">${ap == null ? "" : `${esc(ap)}%`}</td>` : ""}</tr>`;
    };
    const head = (key, name, g) => `<tr class="grp"><td colspan="${hasFw ? 5 : 4}">${esc(name)}</td><td class="gs num">${groupScoreHtml(g)}</td></tr>`;
    const rows = groupRows(c, row, head);
    const how = cv.v === 2
      ? `확신도는 기술 지표와 시장 자료 두 묶음의 신호가 같은 방향을 가리키는 정도입니다. 묶음마다 신호의 가중치는 8·7·6·5, 신호는 Long +1 · Short −1(힘이 약해지면 ±0.5)로 읽어 −100–+100 점수를 내고, 두 묶음 점수를 평균한 D로 50 + 0.4 × D(10–90%)를 계산합니다. 자료가 묶음 무게의 절반에 못 미치면 그 묶음은 빼고, 둘 다 못 미치면 '자료 부족'으로 보류합니다. 뉴스 방향은 12시간 안의 AI 분석에서 읽습니다.${hasFw ? " 'AI 비중' 열은 AI가 추세를 판단하며 실제로 둔 비중이고 확신도 계산에는 쓰지 않습니다." : ""} 확률이 아니며, 가중치와 읽는 법은 팀이 정한 가정입니다.`
      : `정미님 프롬프트의 Confidence 정의("신호들의 일치 정도")와 판단 순서를 따르고, 가중치·읽는 법은 팀이 정한 v1입니다. 힘이 약해지는 신호(히스토그램 축소, 과매수·과매도, OI 감소 등)는 절반으로 셉니다. 자료가 50%에 못 미치면 숫자를 보류합니다. 확률이 아닙니다.`;
    return `<div class="ev-top"><span class="ev-score num ${cv.cls}">${confBigHtml(cv)}</span><span class="ev-lab">${esc(cv.label)}</span></div>
      ${c.note ? `<p class="ev-note">${esc(c.note)}</p>` : ""}
      ${rows ? `<div class="tbl"><table class="t evt-full"><tr><th>신호(판단 순서)</th><th>가중치</th><th>지금 값</th><th>읽기</th><th>방향</th>${hasFw ? "<th>AI 비중</th>" : ""}</tr>${rows}</table></div>` : ""}
      ${c.formula ? `<div class="formula num">${esc(c.formula)}</div>` : ""}
      <p class="fine">${esc(String(c.ref_kst || "").slice(5))} 자료로 15분마다 계산. ${esc(how)}</p>`;
  }
  // AI 분석 3절(10-14 V5 7절 6): 맨 위 한 줄 "뉴스 방향 긍정 +1 · 기사 n건" · 기사별 표지 목록(news_items + news_ref 를 id 로 짝). 옛 분석(키 없음)은 둘 다 빠짐
  function newsHead(b) {
    const nb = V5.newsBias(b);
    if (!nb) return "";
    return `<p class="nb-line">뉴스 방향 ${nb.none ? `<span class="muted">${esc(nb.text)}</span>` : `<b class="${nb.cls}">${esc(nb.text)}</b> · 기사 ${esc(nb.n)}건`}</p>`;
  }
  function newsList(b) {
    const rows = V5.newsRows(b);
    if (!rows.length) return "";
    return `<ul class="news5">${rows.map((r) => `<li class="${r.rel === "none" ? "off" : ""}"><div class="n5-chips"><span class="n5-chip ${r.cls}">${esc(r.dirText)}</span><span class="n5-chip">${esc(r.relText)}</span><span class="imp" role="img" aria-label="중요도 ${r.imp} / 3">${"●".repeat(r.imp)}<i>${"●".repeat(3 - r.imp)}</i></span></div>
      <div class="n5-t">${esc(r.title || "(제목 없음)")}${r.publisher || r.time ? ` <span class="muted">${esc([r.publisher, r.time].filter(Boolean).join(" · "))}</span>` : ""}${r.rel === "none" ? ` <span class="muted">· 점수에 안 씀</span>` : ""}</div></li>`).join("")}</ul>`;
  }
  function renderAiReport() {
    const ae = document.activeElement, fid = ae && ae.classList && ae.classList.contains("air-h") ? ae.id : null;
    try { renderAiReportBody(); } finally {
      if (fid) { const h = document.getElementById(fid); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); } }
    }
  }
  function renderAiReportBody() {
    const v = V4();
    document.querySelectorAll("#ai-coin button").forEach((x) => x.classList.toggle("on", x.dataset.sym === selected));
    const s = board && board.symbols.find((x) => x.symbol === selected);
    const node = v && v.ai && v.ai[selected], a = node && node.latest;
    const lt = node && node.last_try, fwd = V5.failWord(lt);
    const fail = lt && !lt.ok ? ` · <span class="warn">마지막 시도(${esc(lt.created_kst)}) ${fwd === "실패" ? "실패" : `실패(${esc(fwd)})`}, 이전 분석</span>` : "";
    const sec = (n, h, body) => `<section class="air-sec"><h2 class="air-h" id="ai-sec-${n}"><span class="sec-n">${n}</span>${h}</h2>${body}</section>`;
    const p = (t) => `<p>${esc(t)}</p>`;
    const ul = (xs) => `<ul>${(xs || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const kv = (pairs) => `<div class="air-kv">${pairs.map(([k, val]) => `<span class="k">${k}</span><span>${val}</span>`).join("")}</div>`;
    if (!a) {
      $("#ai-report-meta").innerHTML = `${esc(s ? s.short : "")} · AI 분석 없음${fail}`;
      $("#ai-report-body").innerHTML = sec(1, "AI Strategy", kv([["Core Condition", coreTxt(selected)]]) + `<p class="muted">이 코인의 AI 분석이 아직 없습니다. 하루 2번(09·21시)과 Core Condition이 켜질 때 만듭니다.</p>`)
        + sec(2, "Confidence", `<h5>확신도(대시보드 KPI) 계산</h5>${confTable(CF(selected), null)}`)
        + sec(3, "News Analysis", `<p class="muted">AI 분석이 만들어지면 보입니다.</p>`)
        + sec(4, "Fear &amp; Greed Analysis", fngBlock())
        + sec(5, "Market Flow &amp; Derivatives", `<p class="muted">AI 분석이 만들어지면 보입니다.</p>`)
        + sec(6, "Technical Analysis", `<p class="muted">AI 분석이 만들어지면 보입니다.</p>`);
      return;
    }
    const b = a.body;
    // 시각: 분석을 만든 때(정기 09·21시 / 트리거 확인) · AI가 읽은 자료의 마지막 15분봉 · 모델
    $("#ai-report-meta").innerHTML = `<b>${esc(s ? s.short : "")}</b> · ${KIND[a.kind] || "분석"} ${esc(a.created_kst)} · 자료 ${esc(a.ref_kst)} 기준 · ${esc(a.model)}${a.source === "claude" ? " · 대신 분석" : ""}${fail}`;
    const ch = b.expected_change_pct || {}, pr = b.expected_price_range || {};
    const cp = b.coinbase_premium || {}, oi = b.open_interest || {}, te = b.technical || {};
    const num = (x) => (x == null ? "데이터 없음" : esc(String(x)).replace(/^-/, "−"));
    $("#ai-report-body").innerHTML =
      sec(1, "AI Strategy", kv([
        ["Trend Direction", `<b class="${cls(DIR_OF_TREND[b.trend_direction])}">${esc(b.trend_direction)}</b>`],
        ["Expected Change", `<span class="num">${pctTxt(ch.low)} – ${pctTxt(ch.high)}</span> ${EST}`],
        ["Expected Price Range", `<span class="num">$${fmtU(pr.low)} – $${fmtU(pr.high)}</span> ${EST}`],
        ["Core Condition", coreTxt(selected)]]) + `<h5>Summary Reasoning</h5>${p(b.summary_reasoning)}`)
      + sec(2, "Confidence", kv([["Level", `${esc(b.confidence_level)}, <span class="num">${esc(b.confidence_pct)}%</span> ${EST}`]])
        + `<h5>Key Signals</h5>${ul(b.key_signals)}<h5>Risks</h5>${ul(b.risks)}<h5>확신도(대시보드 KPI) 계산</h5>${confTable(CF(selected), a)}`)
      + sec(3, "News Analysis", newsHead(b) + p(b.news_analysis) + newsList(b) + `<p class="fine">AI가 읽은 뉴스: ${esc(a.ref_kst)}까지 24시간의 제목. 그 뒤 기사는 다음 분석에 들어갑니다.${Number(b.news_filtered) > 0 ? ` 지시문처럼 보여 뺀 제목 ${esc(Math.round(Number(b.news_filtered)))}건.` : ""}</p>`)
      + sec(4, "Fear &amp; Greed Analysis", fngBlock() + p(b.fear_greed_analysis))
      + sec(5, "Market Flow &amp; Derivatives",
        `<h5>Coinbase Premium Index</h5>` + kv([["Value/Trend", `<span class="num">${cp.value_pct == null ? "데이터 없음" : `${num(cp.value_pct)}%`}</span> / ${esc(cp.trend || "-")}`]]) + p(cp.interpretation)
        + `<h5>Open Interest (미결제약정)</h5>` + kv([["Trend vs Price", `<span class="num">OI ${pctTxt(oi.oi_change_pct)}, Price ${pctTxt(oi.price_change_pct)}</span>`]]) + p(oi.interpretation))
      + sec(6, "Technical Analysis",
        `<h5>Stochastic</h5>` + kv([["%K · %D", `<span class="num">${num((te.stochastic || {}).k)} · ${num((te.stochastic || {}).d)}</span>`]]) + p((te.stochastic || {}).interpretation)
        + `<h5>MACD</h5>` + kv([["MACD · Signal · Histogram", `<span class="num">${num((te.macd || {}).macd)} · ${num((te.macd || {}).signal)} · ${num((te.macd || {}).histogram)}</span>`]]) + p((te.macd || {}).interpretation)
        + `<h5>StochRSI_K</h5>` + kv([["Value", `<span class="num">${num((te.stochrsi_k || {}).value)}</span>`]]) + p((te.stochrsi_k || {}).interpretation)
        + `<p class="fine">Current Price <span class="num">$${fmtU(b.current_price)}</span></p>`);
  }

  function renderIndStatus() {
    const v = V4(), core = v && v.core;
    if (!$("#ind-body") || !verifyOn()) return;
    if (!core || !core._at) { $("#ind-body").innerHTML = `<p class="muted">아직 계산 전입니다.</p>`; return; }
    const tf = ["h4", "h1", "m15"], tfName = ["4시간", "1시간", "15분"];
    const rows = board.symbols.map((s) => {
      const c = core[s.symbol];
      if (!c) return `<tr><td>${esc(s.short)}</td><td colspan="5" class="muted">-</td></tr>`;
      const st = c.state ? `<span class="${cls(c.state)}">충족 · ${c.state > 0 ? "Long" : "Short"}</span>` : `<span class="muted">미충족</span>`;
      return `<tr class="${s.symbol === selected ? "sel" : ""}"><td><b>${esc(s.short)}</b></td>${tf.map((k) => `<td class="${dirOf(c[k])[2]}">${dirOf(c[k])[1]} ${dirOf(c[k])[0] === "방향 없음" ? "" : dirOf(c[k])[0]}</td>`).join("")}<td>${st}</td>
        <td class="num">${s.score == null ? "-" : sign(s.score)}</td></tr>`;
    }).join("");
    $("#ind-body").innerHTML = `<div class="tbl"><table class="t"><tr><th>코인</th>${tfName.map((n) => `<th>${n}</th>`).join("")}<th>상태</th><th>기술 점수</th></tr>${rows}</table></div>
      <p class="fine">${esc(kstOf(core._at))} KST 계산 · 15분마다. 기술 점수는 2차 회의 정의(기술 지표 4개 가중 점수, 마지막 4시간봉 기준)로 트리거에도 확신도에도 쓰지 않습니다.</p>`;
  }

  function scoreRow(name, x) {
    return `<tr><td>${name}</td><td class="num">${x.n ?? 0}</td><td class="num">${x.closed ?? 0}</td><td class="num">${x.closed ? `${x.success_pct}%` : "-"}</td>
      <td class="num">${x.closed ? `${x.base_success_pct}%` : "-"}</td><td class="num">${x.closed ? `${x.opp_success_pct}%` : "-"}</td><td class="num">${x.closed ? `${x.both_pct}%` : "-"}</td><td class="num">${esc(V5.fix24Cell(x))}</td>
      <td class="num">${x.avg_hours ?? "-"}</td><td class="num">${pctTxt(x.avg_mfe_pct)}</td><td class="num">${x.avg_mae_pct == null ? "-" : `−${x.avg_mae_pct}%`}</td><td class="num">${pctTxt(x.avg_ret_pct)}</td></tr>`;
  }
  const SCORE_HEAD = `<tr><th>구분</th><th>트리거</th><th>끝난 것</th><th>성공률</th><th>같은 구간 항상 Long</th><th>같은 구간 반대 방향</th><th>양쪽 다</th><th>24시간 창</th><th>평균 창(시간)</th><th>평균 최대수익률</th><th>평균 최대 손실</th><th>평균 손익</th></tr>`;
  // 가까운 과거 확신도 점검(기획안 v5 8절, 참고 · 보정 전). 로컬 보드 응답의 conf_replay 만(공개 응답에는 없음)
  function confReplayBlock() {
    const R = board && board.conf_replay;
    const T = R && R.table && R.table.ALL;
    if (!T) return "";
    const cell = (x) => (x && x.n ? `${esc(x.hit_pct)}% <span class="muted">(n ${esc(x.n)})</span>` : "-");
    const rows = Object.entries(T.buckets || {}).map(([b, x]) => `<tr><td>${esc(b)}%</td><td class="num">${cell(x.r4)}</td><td class="num">${cell(x.r24)}</td></tr>`).join("");
    const coin = Object.entries(R.table).filter(([k]) => k !== "ALL").map(([k, x]) => `${esc(k.replace("USDT", ""))} 4시간 ${esc(x.all.r4.hit_pct)}% · 24시간 ${esc(x.all.r24.hit_pct)}%`).join(" · ");
    const a = T.all;
    return `<details><summary>가까운 과거 확신도 점검(참고 · 보정 전)</summary>
      <p class="muted">${esc(R.from)} – ${esc(R.to)} KST · 4시간 마감 하루 ${esc(R.per_day)}번 · 시점 ${esc(R.n_points)}개 · 전체 적중 4시간 ${esc(a.r4.hit_pct)}%(오른 비율 ${esc(a.r4.up_pct)}%) · 24시간 ${esc(a.r24.hit_pct)}%(오른 비율 ${esc(a.r24.up_pct)}%)</p>
      <div class="tbl"><table class="t"><tr><th>Long 확률</th><th>4시간 뒤 방향 적중</th><th>24시간 뒤 방향 적중</th></tr>${rows}</table></div>
      <p class="fine">${coin}</p><p class="fine">${esc(VT("conf_replay_note"))}</p></details>`;
  }

  function renderScoring() {
    const v = V4();
    if (!verifyOn()) return;
    if (!v) { $("#score-body").innerHTML = `<p class="muted">트리거 성적 데이터가 아직 없습니다.</p>`; return; }
    const st = v.stats || {}, c = v.conf || {};
    const live = scoreRow("공식(Core Condition + AI 추세)", st.official || {}) + scoreRow("기술 조건만", st.tech || {});
    const bySym = (arr, label) => (arr || []).map((x) => scoreRow(`${label} · ${esc(x.short)}`, x)).join("");
    let rep = "";
    if (st.replay) {
      const R = st.replay;
      const per = (k, ko) => R[k] ? `<h5>${ko} (${esc(R[k].from)} – ${esc(R[k].to_exclusive || "지금")})</h5><div class="tbl"><table class="t">${SCORE_HEAD}${scoreRow("합계", R[k].all)}${(R[k].rows || []).map((x) => scoreRow(esc(String(x.symbol).replace("USDT", "")), x)).join("")}</table></div>` : "";
      rep = `<details open><summary>과거 재현(기술 조건만, AI 게이트 없음)</summary>${per("reference", "참고 기간")}${per("check", "확인 기간")}
        <p class="fine">${esc(VT("replay_note"))}</p></details>`;
    }
    const recLine = (r) => {
      const [rt, rc] = RES[r.result] || ["-", "muted"];
      return `<li><span class="num">${esc(kstOf(r.issued_at))}</span> <b>${esc(r.short)}</b> <span class="${cls(r.dir)}">${r.dir > 0 ? "Long" : "Short"}</span> · <span class="${rc}">${rt}</span> <span class="muted num">최대 ${pctTxt(r.mfe_net_pct)} · 손실 ${r.mae_pct == null ? "-" : `−${r.mae_pct}%`} · 다음 트리거 때 ${pctTxt(r.ret_net_pct)}${r.thr_pct != null ? ` · 기준 ${esc(r.thr_pct)}%` : ""} · 24시간 창 ${esc(fix24Txt(r))}</span></li>`;
    };
    const offRecent = ((v.recent || {}).official || []).slice(0, 10).map(recLine).join("");
    const checks = ((v.recent || {}).checks || []).slice(0, 10).map((k) => `<li><span class="num">${esc(kstOf(k.t_bar))}</span> <b>${esc(k.short)}</b> <span class="${cls(k.dir)}">${k.dir > 0 ? "Long" : "Short"}</span> · AI ${k.ai_dir == null ? "-" : trendOf(k.ai_dir)}${k.ai_ref_t ? ` <span class="muted">(${esc(kstOf(k.ai_ref_t).slice(6))} 데이터)</span>` : ""} → ${esc(k.label)}</li>`).join("");
    const techRecent = ((v.recent || {}).tech || []).slice(0, 10).map(recLine).join("");
    $("#score-body").innerHTML = `<p class="muted">운영 기록 · ${v.live_start ? `${esc(isoKst(v.live_start))} KST부터` : ""} · 성공 기준 ${esc(V5.thrText(c))} · 재신호 금지 ${esc(c.ban_hours)}시간</p>
      <div class="tbl"><table class="t">${SCORE_HEAD}${live}${bySym(st.official_by_symbol, "공식")}${bySym(st.tech_by_symbol, "기술 조건만")}</table></div>
      <p class="fine">${esc(VT("score_note"))}</p>
      ${rep}
      ${confReplayBlock()}
      <div class="grid g3 mt"><div><h5>최근 공식 트리거 · 결과</h5>${offRecent ? `<ul class="rec-list">${offRecent}</ul>` : `<p class="muted">아직 없음</p>`}</div>
        <div><h5>최근 AI 게이트 확인</h5>${checks ? `<ul class="rec-list">${checks}</ul>` : `<p class="muted">아직 없음</p>`}</div>
        <div><h5>최근 기술 조건 트리거</h5>${techRecent ? `<ul class="rec-list">${techRecent}</ul>` : `<p class="muted">아직 없음</p>`}</div></div>`;
  }

  function renderTrack() {
    if (!verifyOn()) return;
    const t = board.track || {}, rows = t.rows || [];
    const small = rows.some((r) => r.small_sample);
    const body = rows.map((r) => `<tr><td>${esc(r.symbol.replace("USDT", ""))}</td><td class="num">${r.n}</td><td class="num">${r.scored}</td>
      <td class="num">${pct(r.hit, r.called)}</td><td class="num">${pct(r.base_hit, r.base_scored)}</td>
      <td class="num">${r.strong_n ? pct(r.strong_hit, r.strong_scored) : "-"}</td><td class="num">${r.strong_n && r.strong_base_scored != null ? pct(r.strong_base_hit, r.strong_base_scored) : "-"}</td></tr>`).join("");
    let rep = "";
    if (board.replay) {
      const R = board.replay.rows;
      const p = (r) => (r.called ? ((100 * r.hit) / r.called).toFixed(1) : "-");
      const pb = (r) => (r.base_scored ? ((100 * r.base_hit) / r.base_scored).toFixed(1) : "-");
      const nAvg = Math.round(R.reduce((a, r) => a + r.called, 0) / Math.max(1, R.length));
      const line = `방향 적중 ${R.map((r) => `${r.symbol.replace("USDT", "")} ${p(r)}%`).join(" · ")} — 기준 '항상 Long' ${R.map(pb).join(" · ")}%`;
      const rr = R.map((r) => `<tr><td>${esc(r.symbol.replace("USDT", ""))}</td><td class="num">${pct(r.hit, r.called)}</td><td class="num">${pct(r.base_hit, r.base_scored)}</td>
        <td class="num">${pct(r.strong_hit, r.strong_scored)}</td><td class="num">${r.strong_base_scored != null ? pct(r.strong_base_hit, r.strong_base_scored) : "-"}</td></tr>`).join("");
      rep = `<details><summary>과거 재현(${esc(board.replay.from)} – ${esc(board.replay.to_exclusive_kst)} KST 전, 종목당 n 약 ${nAvg.toLocaleString()}) ${line}${board.replay.reused ? " · 확인 기간 재사용" : ""}</summary>
        <div class="tbl"><table class="t"><tr><th>종목</th><th>방향 적중</th><th>기준 '항상 Long'</th><th>확실한 신호 적중</th><th>같은 시점 '항상 Long'</th></tr>${rr}</table></div>
        <p class="fine">확실한 신호의 적중은 그 신호가 난 같은 시점들의 '항상 Long'과 비교합니다(전체 기간 기준과 비교하지 않음).</p>
        <p class="fine">운영 기록과 별개로, 같은 규칙을 과거 4시간봉마다 적용한 결과입니다. 4시간마다의 판정은 서로 독립이 아니고, 세 종목 결과를 코인 전체로 일반화하지 않습니다.</p></details>`;
    }
    const notes = [];
    if (t.late_n) notes.push(`분석 시각에서 1시간 넘게 지나 만든(늦게 복구한) 분석 ${t.late_n}건은 미리 낸 분석이 아니라 성적에서 뺐습니다.`);
    const pv = t.prev_versions;
    if (pv) notes.push(`이전 규칙 기록 ${pv.n}건(${esc(pv.from_kst === pv.to_kst ? pv.from_kst : `${pv.from_kst} – ${pv.to_kst}`)} KST)은 아래 '지난 4시간 분석' 표에 함께 나옵니다.`);
    const al = t.all || {};
    const allLine = al.strong_scored != null ? `<p class="rep-all">운영 전체(${esc(al.since_kst || "")}부터, 규칙 ${al.versions}번 바뀐 기록 합침): 확실한 신호 <b>${al.strong_hit}/${al.strong_scored}</b> 맞음 · 같은 시점 '항상 Long' ${al.strong_base_hit}/${al.strong_base_scored} · 방향 ${al.direction_hit}/${al.direction_scored}</p>` : "";
    $("#track-body").innerHTML = allLine + `<p class="muted">운영 기록 · 현재 규칙 · ${esc(t.since_kst || "-")} KST부터${small ? " · 판정 30건 미만이라 표본 부족" : ""}</p>
      ${notes.length ? `<p class="fine">${notes.join(" ")}</p>` : ""}
      <div class="tbl"><table class="t"><tr><th>종목</th><th>분석</th><th>채점 완료</th><th>방향 적중</th><th>기준 '항상 Long'</th><th>확실한 신호 적중</th><th>같은 시점 '항상 Long'</th></tr>${body}</table></div>
      <p class="fine">확실한 신호 적중은 그 신호가 난 같은 시점들의 '항상 Long'과 나란히 봅니다.</p>${rep}`;
  }



  // ---------- 뉴스 띠(10-13 v4 P5·P6): 10초마다 다음 제목. 마우스를 올리거나 누르면 멈추고 최근 목록이 펼쳐진다.
  // '자세히 ▾'는 그 제목이 가리키는 코인의 AI 분석 3 News Analysis로(코인이 없으면 지금 고른 코인). ?mock=news 는 화면 검토용 예시 ----------
  // 뉴스 출처 표시(2026-10-20): 네이버 검색 API 약관 특약 2.1·2.2 — 네이버 검색결과임을 표시하고 원문 링크를 준다
  const newsSource = (n) => n.source === "naver_news" ? "네이버 뉴스 검색결과" : (n.source_label || "");
  const MOCK_NEWS = query.get("mock") === "news";
  const tk = $("#ticker"), tkLine = $("#ticker-line");
  let tkItems = [], tkIdx = 0, tkPinned = false, tkHover = false;
  const setTicker = () => { const o = tkPinned || tkHover; tk.classList.toggle("open", o); tkLine.setAttribute("aria-expanded", o); };
  function tkShow() {
    const n = tkItems[tkIdx];
    if (!n) return;
    $("#tk-main").innerHTML = `<span class="tk-t">${esc(n.title)}</span><span class="tk-time num">${esc(String(n.published_kst || "").slice(6))}</span>`
      + (newsSource(n) ? `<span class="tk-time"> · ${esc(newsSource(n))}</span>` : "");
  }
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let tkPending = null, tkFocus = false;   // 멈춘 동안 들어온 새 목록(다시 돌 때 바꿈), 키보드 초점이 띠 안에 있는지
  const tkResume = () => { if (!tkPinned && !tkHover && !tkFocus && tkPending) { const it = tkPending; tkPending = null; tkItems = it; tkIdx = 0; tkShow(); tkList(); } };
  function tkList() {
    $("#ticker-list").innerHTML = tkItems.map((n) => `<li><a href="${safeUrl(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>
      <span class="meta">${esc(n.publisher || n.source)} · ${esc(n.published_kst || "")}${newsSource(n) ? ` · ${esc(newsSource(n))}` : ""}</span></li>`).join("");
  }
  setInterval(() => {
    if (tkItems.length < 2 || tkPinned || tkHover || tkFocus || document.hidden || reduceMotion.matches) return;
    tkIdx = (tkIdx + 1) % tkItems.length;
    tkShow();
  }, 10000);
  tk.addEventListener("mouseenter", () => { tkHover = true; setTicker(); });
  tk.addEventListener("mouseleave", () => { tkHover = false; setTicker(); tkResume(); });
  tk.addEventListener("focusin", () => { tkFocus = true; });
  tk.addEventListener("focusout", (e) => { if (!tk.contains(e.relatedTarget)) { tkFocus = false; tkResume(); } });
  tkLine.addEventListener("click", (e) => { if (e.target.closest("#tk-more")) return; tkPinned = !tkPinned; setTicker(); });
  tkLine.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !e.target.closest("#tk-more")) { e.preventDefault(); tkPinned = !tkPinned; setTicker(); }
  });
  document.addEventListener("click", (e) => { if (tkPinned && !tk.contains(e.target)) { tkPinned = false; setTicker(); tkResume(); } });
  $("#tk-more").addEventListener("click", (e) => {
    e.stopPropagation();
    const n = tkItems[tkIdx] || {};
    const codes = String(n.symbols || "").split(",").map((x) => x.trim());
    const hit = ["BTC", "ETH", "XRP"].find((c) => codes.includes(c));
    if (hit) selected = `${hit}USDT`;
    tkPinned = false; tkHover = false; setTicker(); renderRefLine();
    window.scrollTo({ top: 0 });
    goSection(3);
  });
  function renderNews(b) {
    let items = (b.news || []).slice(0, 8);
    if (MOCK_NEWS) {
      const now = Date.now();
      items = [["비트코인, 주말 앞두고 8만4천 달러대 횡보", "example.co.kr", "BTC"], ["Ethereum validators vote on gas limit increase", "example.com", "ETH"],
        ["리플(XRP), 송금 파트너 추가 발표", "example.kr", "XRP"], ["Crypto market volumes fall ahead of US data", "example.org", "CRYPTO"]]
        .map(([title, publisher, symbols], k) => ({ title, publisher, symbols, url: "https://example.com", source_label: "예시", published_kst: new Date(now - (k + 1) * 23 * 60e3 + 9 * 3600e3).toISOString().slice(5, 16).replace("T", " ") }));
    }
    const key = items.map((n) => n.title).join("|");
    if (key !== tk.dataset.key) {
      tk.dataset.key = key;
      if ((tkPinned || tkHover || tkFocus) && tkItems.length) tkPending = items;   // 읽는 중인 제목·목록은 그대로
      else { tkItems = items; tkIdx = 0; tkShow(); tkList(); }
    }
    tk.hidden = !tkItems.length && !items.length;
  }

  // ---------- 지표 그래프 (기획안_지표그래프_2026-10-03) ----------
  function saveChart() {
    try { localStorage.setItem("top3-chart", JSON.stringify({ state: chartState, days: chartDays })); } catch (e) { /* 무시 */ }
  }
  function pickIndicator(id, reset) {
    const before = chartState;
    chartState = reset ? C.SPLIT() : C.nextSelection(chartState, id);
    const added = chartState.mode === "pick" && before.mode === "pick" && chartState.sel.length > before.sel.length ? id : null;
    saveChart();
    renderChartFrame();
    renderEvidence();
    drawChart(added);
  }
  // 그래프 둘레(제목·버튼·간단한 근거·상태 줄). 선택한 코인 카드와 같은 방향 표시를 쓴다
  function renderChartFrame() {
    const s = board && board.symbols.find((x) => x.symbol === selected);
    $("#chart-title").textContent = `지표 그래프 · ${s ? s.short : ""}`;
    const mk = s && s.market;   // 24시간 고가·저가(10-13 v4: 확신도 카드에서 옮김)
    $("#chart-hilo").textContent = mk ? `24시간 고가 ${fmtU(mk.high_24h)} · 저가 ${fmtU(mk.low_24h)}` : "";
    // 지표별 방향 화살표는 4시간 분석의 판정 결과라 맥에서 직접 연 화면에서만(공개 응답에는 indicators 가 없음)
    const dirs = s && s.indicators ? s.indicators.map((i) => i.dir) : [], showDir = isLocal();
    const chips = C.ORDER.map((id, k) => {
      const I = C.IND[id], [, ar, c] = dirOf(dirs[k]);
      const on = chartState.mode === "split" || chartState.sel.includes(id);
      return `<button class="ichip${on ? " on" : " dim"}" data-ind="${id}" aria-pressed="${chartState.mode === "pick" && on}"><span class="sw c-${id}"></span>${esc(I.name)} <span class="v">${esc(I.tf)}</span>${showDir ? ` <span class="${c}">${ar}</span>` : ""}</button>`;
    }).join("");
    $("#chart-chips").innerHTML = chips + `<button class="ichip reset${chartState.mode === "split" ? " on" : ""}" data-reset="1" aria-pressed="${chartState.mode === "split"}">나눠 보기</button>`
      + `<span class="chip-hint">지표를 누르면 그것만 · 더 누르면 겹쳐 보기</span>`;
    document.querySelectorAll("#chart-range button").forEach((b) => b.classList.toggle("on", Number(b.dataset.days) === chartDays));
    $("#chart-note").hidden = !(chartState.mode === "pick" && chartState.sel.length > 1 && chartState.sel.some((id) => C.IND[id].kind === "zero"));
    $("#chart-brief").hidden = true;   // 계산식은 근거 카드에(10-13 v4)
  }
  $("#chart-chips").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.reset) pickIndicator(null, true); else pickIndicator(b.dataset.ind);
  });
  document.querySelectorAll("#chart-range button").forEach((b) => b.addEventListener("click", () => {
    chartDays = Number(b.dataset.days); saveChart(); renderChartFrame(); loadChart(true);
  }));
  $("#chart-brief").addEventListener("click", () => {
    const ev = $("#evidence");
    ev.scrollIntoView({ behavior: "smooth", block: "start" });
    ev.classList.remove("flash"); void ev.offsetWidth; ev.classList.add("flash");
  });

  // 그래프 자료가 멈췄는지(10-13 v4: 상태 줄 대신 '⚠ 상태' 탭). 저장본이면 지금 시각으로 다시 본다
  function chartStatus() {
    if (!chartData) return;
    const last15 = (chartData.last_close || {})["15m"];
    const age = last15 ? Math.round((Date.now() - last15) / 60e3) : null;
    const isStale = snapshotMode() ? (age == null || age > 45) : chartData.stale;
    const note = isStale ? `지표 그래프의 마지막 15분봉이 ${age == null ? "오래" : `${age}분`} 전입니다${snapshotMode() ? "(저장한 화면)" : "(수집·엔진 확인 필요)"}.` : "";
    if (note !== chartStaleNote) { chartStaleNote = note; updateStatusTab(); }
  }
  let chartReq = 0;
  async function loadChart(force) {
    if (!selected) return;
    // 가장 마지막 요청의 응답만 그린다(10-04 GPT-6.1 Sol 재현: BTC→ETH→BTC 에서 옛 BTC 응답이 새 응답을 덮음)
    const my = ++chartReq, sym = selected, days = chartDays;
    let d;
    try { d = await getJSON(`/api/chart/${encodeURIComponent(sym)}?days=${days}`); }
    catch (e) {
      if (my !== chartReq) return;
      if (connFail(e) && CFG) return;   // 연결이 끊긴 것: 저장본으로 화면 전체를 다시 그리는 중
      $("#chart-svg").innerHTML = `<p class="muted">그래프 데이터를 불러오지 못했습니다. 잠시 뒤 다시 시도합니다.</p>`; chartData = null;
      if (!chartErrNote) { chartErrNote = "지표 그래프 자료를 불러오지 못했습니다. 잠시 뒤 다시 시도합니다."; updateStatusTab(); }
      return;
    }
    if (my !== chartReq) return;
    if (chartErrNote) { chartErrNote = ""; updateStatusTab(); }
    const same = chartData && chartSym === selected && chartData.generated_ms === d.generated_ms && chartData.days === d.days;
    chartData = d; chartSym = selected;
    if ((!same || force) && viewNow === "now") drawChart(null);   // 홈이 아닐 때는 그리지 않고 자료만 받아 둔다(홈을 열 때 그림)
    chartStatus();
  }
  function drawChart(added) {
    if (!chartData) return;
    const box = $("#chart-svg");
    if (!box.clientWidth) return;   // 숨은 화면(폭 0)에는 그리지 않는다(10-14 7절 9 D). 홈을 열 때 다시 그림
    const r = C.render(verifyOn() ? chartData : { ...chartData, analyses: [] }, chartState, { width: box.clientWidth || 900, added });
    box.innerHTML = r.svg;
    const svg = box.querySelector("svg");
    svg.querySelectorAll("path.draw").forEach((p) => {   // 새로 더한 지표: 선이 그려지며 겹쳐짐
      const len = p.getTotalLength ? p.getTotalLength() : 0;
      if (!len) return;
      p.style.strokeDasharray = `${len}`; p.style.strokeDashoffset = `${len}`;
      requestAnimationFrame(() => { p.style.transition = "stroke-dashoffset .6s ease-out"; p.style.strokeDashoffset = "0"; });
      p.addEventListener("transitionend", () => { p.style.strokeDasharray = ""; p.style.transition = ""; }, { once: true });
    });
    const tip = $("#chart-tip"), line = svg.querySelector(".hover-line"), dots = svg.querySelector(".hover-dots");
    const ids = chartState.mode === "split" ? C.ORDER : chartState.sel;
    const move = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const px = (clientX - rect.left) * (r.W / rect.width);
      const t = r.t0 + ((px - r.L) / (r.W - r.L - r.R)) * (r.t1 - r.t0);
      if (t < r.t0 || t > r.t1) return hide();
      const vals = C.valuesAt(chartData, ids, t);
      line.setAttribute("x1", px); line.setAttribute("x2", px); line.setAttribute("visibility", "visible");
      let dd = "";
      r.paneInfo.forEach((pn) => pn.ids.forEach((id) => {
        const v = vals.find((x) => x.id === id);
        if (v && v.v != null && !v.gap) dd += `<circle class="hdot c-${id}" cx="${r.x(v.t).toFixed(1)}" cy="${Math.min(pn.y0 + pn.h - 3, Math.max(pn.y0 + 3, pn.scales[id](v.v))).toFixed(1)}" r="3.5"/>`;
      }));
      dots.innerHTML = dd;
      const pv = vals.find((x) => x.id === "price");
      tip.innerHTML = `<b>${esc(C.kst(pv && !pv.gap ? pv.t : t))} KST</b>` + vals.map((v) => v.gap
        ? `<div>${v.id === "price" ? "가격" : `<span class="sw c-${v.id}"></span>${esc(v.label)}`} <span class="warn">봉 누락</span> <span class="muted">(마지막 ${esc(C.kst(v.t, false))} 마감)</span></div>`
        : v.id === "price"
        ? `<div>가격 <span class="num">${fmtPrice(selected, v.v)}</span></div>`
        : `<div><span class="sw c-${v.id}"></span>${esc(v.label)} <span class="num">${esc(C.fmt(v.v))}</span> <span class="muted num">/ ${esc(C.fmt(v.s))}</span> <span class="muted">${esc(C.kst(v.t, false))} 마감</span></div>`).join("");
      tip.hidden = false;
      const left = (px / r.W) * rect.width;
      tip.style.left = `${Math.min(Math.max(0, left + 14), rect.width - tip.offsetWidth - 4)}px`;
    };
    const hide = () => { tip.hidden = true; line.setAttribute("visibility", "hidden"); dots.innerHTML = ""; };
    const hit = svg.querySelector(".hit");
    hit.addEventListener("mousemove", (e) => move(e.clientX));
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("touchstart", (e) => move(e.touches[0].clientX), { passive: true });
    hit.addEventListener("touchmove", (e) => move(e.touches[0].clientX), { passive: true });
    hit.addEventListener("touchend", () => setTimeout(hide, 2000), { passive: true });
    // 키보드: 그래프에 초점을 두고 ←→ 로 1시간(Shift 는 4시간)씩 옮겨 값 보기, Esc 로 닫기(10-04 GPT-6.1 Sol 접근성)
    let kt = null;
    box.onkeydown = (e) => {
      if (!["ArrowLeft", "ArrowRight", "Escape"].includes(e.key)) return;
      e.preventDefault();
      if (e.key === "Escape") { kt = null; hide(); return; }
      const stepMs = e.shiftKey ? 4 * 3600e3 : 3600e3;
      kt = Math.min(r.t1, Math.max(r.t0, (kt == null ? r.t1 : kt) + (e.key === "ArrowRight" ? stepMs : -stepMs)));
      const rect = svg.getBoundingClientRect();
      move(rect.left + ((r.L + ((kt - r.t0) / (r.t1 - r.t0)) * (r.W - r.L - r.R)) / r.W) * rect.width);
    };
    box.onblur = () => { kt = null; hide(); };
  }
  let resizeTimer = null;
  if (window.ResizeObserver) {
    let lastW = 0;
    new ResizeObserver((ents) => {
      const w = Math.round(ents[0].contentRect.width);
      if (!w || Math.abs(w - lastW) < 8) return;   // 폭 0(숨김)이면 그리지 않는다(10-14 7절 9 D)
      lastW = w; clearTimeout(resizeTimer); resizeTimer = setTimeout(() => drawChart(null), 150);
    }).observe($("#chart-svg"));
  }

  // ---------- 지난 분석 ----------
  let histSym = "", histAll = true;   // 10-06 P4: 규칙이 자주 바뀌어 이전 규칙 기록도 기본으로 보여 줌
  document.querySelectorAll("#hist-filter button").forEach((b) => b.addEventListener("click", () => {
    histSym = b.dataset.sym;
    document.querySelectorAll("#hist-filter button").forEach((x) => x.classList.toggle("on", x === b));
    loadHistory();
  }));
  let histReq = 0;
  async function loadHistory() {
    if (!verifyOn()) return;   // 검증 화면 자료(공개 화면에서는 서버도 빈 목록)
    const my = ++histReq;
    let r;
    try { r = await getJSON(`/api/analyses?limit=120${histSym ? `&symbol=${encodeURIComponent(histSym)}` : ""}${histAll ? "&all_versions=true" : ""}`); }
    catch (e) { if (my === histReq && !e.switching) $("#hist-body").innerHTML = `<p class="muted">불러오지 못했습니다.</p>`; return; }
    if (my !== histReq) return;
    if (!r.data || !r.data.length) { $("#hist-body").innerHTML = `<p class="muted">아직 운영 기록이 없습니다.</p>`; return; }
    const rows = r.data.map((a) => {
      let res = a.status === "ok" ? "대기" : "-";
      if (a.ret != null) {
        const ch = `${a.ret > 0 ? "+" : ""}${(100 * a.ret).toFixed(2)}%`;
        res = a.hit == null ? `${ch} · ${a.score === 0 ? "방향 없음" : "보합"}` : `${ch} · ${a.hit ? "적중" : "빗나감"}`;
      }
      const chips = [["MACD", a.macd_dir], ["Sto", a.sto_state], ["SRSI", a.srsi_state], ["VPCI", a.vpci_dir]]
        .map(([n, d]) => `<span class="${dirOf(d)[2]}">${n}${dirOf(d)[1]}</span>`).join(" ");
      return `<tr${a.current_rules ? "" : " class='old'"}><td class="num">${esc(a.t_kst)}</td><td>${esc(a.symbol.replace("USDT", ""))}</td>
        <td class="num ${cls(a.score || 0)}">${a.score == null ? "-" : sign(a.score)}</td><td>${esc(a.label)}${a.current_rules ? "" : " <span class='muted'>(이전 규칙)</span>"}${a.late ? " <span class='muted'>(늦게 복구 · 성적 제외)</span>" : ""}</td>
        <td>${a.status === "ok" ? chips : ""}</td><td class="num">${a.close == null ? "-" : fmtPrice(a.symbol, a.close)}</td><td class="num">${res}</td></tr>`;
    }).join("");
    const toggle = r.other_versions_n
      ? `<p class="fine"><label><input type="checkbox" id="hist-all"${histAll ? " checked" : ""}> 이전 규칙 기록 보기(${r.other_versions_n}건)</label> · 규칙이 바뀌면 같은 시각을 새 규칙으로 다시 계산해 기록이 나뉩니다.</p>`
      : "";
    $("#hist-body").innerHTML = `${toggle}<table class="t"><tr><th>시각(KST)</th><th>종목</th><th>점수</th><th>판정</th><th>지표</th><th>기준가</th><th>4시간 뒤</th></tr>${rows}</table>`;
    const cb = $("#hist-all");
    if (cb) cb.addEventListener("change", () => { histAll = cb.checked; loadHistory(); });
  }

  // ---------- 공부 (01_운영/공부노트) ----------
  // 마크다운을 이스케이프한 뒤 필요한 문법(제목·목록·표·굵게·코드·링크)만 HTML로 바꾼다.
  // 만든 태그는 자리표시(\u0000n\u0000)로 빼 두었다가 마지막에 되돌린다. 뒤 단계가 이미 만든 href 안을 다시 바꾸지 않게 하기 위함.
  function inline(t) {
    const keep = [];
    const hold = (html) => `\u0000${keep.push(html) - 1}\u0000`;
    const bold = (x) => x.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    let s = esc(String(t ?? "").replace(/\u0000/g, ""));
    s = s.replace(/`([^`]+)`/g, (m, c) => hold(`<code>${c}</code>`));
    // 그림(10-13 v4, 공부 8장 사용 방법): 저장소 경로(…/05_프론트/app/img/…)는 화면 경로(img/…)로 바꾸고 img/ 아래 그림만 허용
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => {
      const u = url.replace(/&amp;/g, "&").replace(/^.*05_프론트\/app\//, "");
      if (!/^img\/[\w\-./가-힣]+\.(png|jpe?g|webp)$/i.test(u) || u.includes("..")) return alt;
      return hold(`<img class="doc-img" src="${esc(u)}" alt="${alt}" loading="lazy">`);
    });
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, txt, url) => {
      const u = url.replace(/&amp;/g, "&");
      if (/^https?:\/\//i.test(u)) return hold(`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${bold(txt)}</a>`);
      if (/^[0-9]{2}_[^/]+\.md$/.test(u)) return hold(`<a href="#" data-study="${esc(u)}">${bold(txt)}</a>`);
      return txt;
    });
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)\u0000]+)/g, (m, pre, url) => pre + hold(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`));
    s = bold(s);
    return s.replace(/\u0000(\d+)\u0000/g, (m, i) => keep[+i]);
  }
  function renderMarkdown(md) {
    const lines = md.replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const l = lines[i];
      if (/^```/.test(l)) {
        const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(esc(lines[i++]));
        i++; out.push(`<pre><code>${buf.join("\n")}</code></pre>`); continue;
      }
      const h = l.match(/^(#{1,4})\s+(.*)$/);
      if (h) { const n = Math.min(h[1].length, 3); out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue; }
      if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const head = cells(l); i += 2;
        const body = [];
        while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) body.push(cells(lines[i++]));
        out.push(`<table><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</table>`);
        continue;
      }
      if (/^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l)) {
        const ordered = /^\s*\d+\.\s+/.test(l);
        const items = [];
        while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) {
          items.push(inline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""))); i++;
        }
        out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${x}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
        continue;
      }
      if (!l.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\|)/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) para.push(lines[i++]);
      out.push(`<p>${inline(para.join(" "))}</p>`);
    }
    return out.join("");
  }
  // 공부 탭 속도(10-14 V5 7절 9): 목차와 장을 메모리에 두고 탭을 열면 바로 보여 준다(없으면 '불러오는 중'을 먼저).
  // 첫 보드가 뜬 뒤 쉬는 때(requestIdleCallback) 목차와 첫 장을 미리 받는다. 실시간 ↔ 저장본이 바뀌어도 지우지 않고
  // 다시 받아(studyEpoch) 내용이 달라졌을 때만 바꾼다
  let studyNavBound = false, studyCur = null, studyEpoch = 0, studyIdx = null;   // studyIdx = {data, sig, epoch}
  const studyDocs = new Map();   // 장 이름 → {md, epoch}
  const studyInflight = new Map();
  const once = (key, fn) => { if (!studyInflight.has(key)) studyInflight.set(key, fn().finally(() => studyInflight.delete(key))); return studyInflight.get(key); };
  // 목차를 받아 저장한다. 돌려주는 값: 목차 내용이 바뀌었는지
  function fetchStudyIndex() {
    return once("index", async () => {
      const ep = studyEpoch, r = await getJSON("/api/study");
      const data = r.data || [], sig = JSON.stringify(data.map((d) => [d.name, d.short || d.title]));
      const changed = !studyIdx || studyIdx.sig !== sig;
      studyIdx = { data, sig, epoch: ep };
      return changed;
    });
  }
  // 장 하나. 같은 출처에서 받아 둔 것이 있으면 그대로, 없으면 요청. 돌려주는 값: 글이 바뀌었는지(처음 받으면 true)
  function fetchStudyDoc(name) {
    return once("doc|" + name, async () => {
      const ep = studyEpoch, r = await getJSON(`/api/study/${encodeURIComponent(name)}`);
      const old = studyDocs.get(name);
      studyDocs.set(name, { md: r.markdown, epoch: ep });
      return !old || old.md !== r.markdown;
    });
  }
  const idle = (fn) => (window.requestIdleCallback ? window.requestIdleCallback(fn, { timeout: 4000 }) : setTimeout(fn, 1500));
  let studyPrefetched = false;
  function prefetchStudy() {
    if (studyPrefetched) return;
    studyPrefetched = true;
    idle(async () => {
      try {
        if (!studyIdx) await fetchStudyIndex();
        const first = studyIdx && studyIdx.data[0];
        if (first && !studyDocs.has(first.name)) await fetchStudyDoc(first.name);
      } catch (e) { /* 미리 받기 실패는 무시: 탭을 열 때 다시 요청 */ }
    });
  }
  let navShownSig = null, studyShown = null;   // 지금 화면에 그려진 목차 · 장(같은 내용이면 다시 그리지 않음)
  function paintStudyNav() {
    if (navShownSig !== studyIdx.sig || !$("#study-nav button")) {
      navShownSig = studyIdx.sig;
      $("#study-nav").innerHTML = studyIdx.data.map((d) => `<button data-study="${esc(d.name)}" title="${esc(d.title)}">${esc(d.short || d.title)}</button>`).join("");
    }
    document.querySelectorAll("#study-nav button").forEach((b) => b.classList.toggle("on", b.dataset.study === studyCur));
    if (!studyNavBound) {   // 출처가 바뀌어 목차를 다시 그려도 클릭 처리는 한 번만 붙인다
      studyNavBound = true;
      $("#study-nav").addEventListener("click", (e) => { const b = e.target.closest("[data-study]"); if (b) openStudy(b.dataset.study); });
    }
  }
  async function loadStudyIndex() {
    if (studyIdx) {   // 받아 둔 것을 바로 보여 준다. 출처가 바뀐 뒤면 뒤에서 확인해 달라졌을 때만 다시 그림
      paintStudyNav();
      const keep = studyIdx.data.find((d) => d.name === studyCur) || studyIdx.data[0];
      if (keep) openStudy(keep.name, false);
      if (studyIdx.epoch === studyEpoch) return;
    } else {
      $("#study-nav").innerHTML = `<p class="muted">불러오는 중…</p>`;
      if (!studyDocs.size) { $("#study-doc").innerHTML = `<p class="muted">불러오는 중…</p>`; studyShown = null; }
    }
    let changed;
    try { changed = await fetchStudyIndex(); } catch (e) { if (!studyIdx && !e.switching) $("#study-nav").innerHTML = `<p class="muted">불러오지 못했습니다.</p>`; return; }
    if (changed) paintStudyNav();
    const keep = studyIdx.data.find((d) => d.name === studyCur);
    if (studyIdx.data.length && (changed || !keep)) openStudy(keep ? keep.name : studyIdx.data[0].name, false);
  }
  function paintStudy(name, md) {
    if (studyShown && studyShown.name === name && studyShown.md === md) return;   // 이미 그려진 같은 내용
    studyShown = { name, md };
    $("#study-doc").innerHTML = renderMarkdown(md);
    // 장 안 목차: h2 에 id 를 붙이고 제목 아래에 한 줄 링크로 보여 준다
    const h2s = [...$("#study-doc").querySelectorAll("h2")];
    h2s.forEach((h, i) => { h.id = `sec-${i + 1}`; });
    if (h2s.length > 2) {
      const toc = document.createElement("nav");
      toc.className = "study-toc";
      toc.setAttribute("aria-label", "이 장의 목차");
      toc.innerHTML = h2s.map((h) => `<a href="#${h.id}">${esc(h.textContent)}</a>`).join("");
      toc.addEventListener("click", (e) => { const a = e.target.closest("a"); if (!a) return; e.preventDefault(); document.getElementById(a.getAttribute("href").slice(1)).scrollIntoView({ block: "start" }); });
      const h1 = $("#study-doc").querySelector("h1");
      if (h1) h1.after(toc); else $("#study-doc").prepend(toc);
    }
    $("#study-doc").querySelectorAll("a[data-study]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openStudy(a.dataset.study); }));
  }
  async function openStudy(name, scroll = true) {
    studyCur = name;
    document.querySelectorAll("#study-nav button").forEach((b) => b.classList.toggle("on", b.dataset.study === name));
    const have = studyDocs.get(name);
    if (have) paintStudy(name, have.md); else { $("#study-doc").innerHTML = `<p class="muted">불러오는 중…</p>`; studyShown = null; }
    if (scroll) $("#study-doc").scrollIntoView({ block: "start" });
    if (have && have.epoch === studyEpoch) return;   // 이 출처에서 받은 것: 다시 요청하지 않음
    let changed;
    try { changed = await fetchStudyDoc(name); }
    catch (e) {
      // 공개 화면에서 팀 내부 장(7장 등)은 서버가 404로 답하고 저장본에도 없다(10-13 결정 84-A). 목차의 링크로 들어온 경우 안내
      if (e.status === 404) studyDocs.delete(name);   // 서버가 이 장을 더는 주지 않음(공개 화면 등): 받아 둔 것도 버린다
      if ((!have || e.status === 404) && !e.switching && studyCur === name) {
        studyShown = null;
        $("#study-doc").innerHTML = e.status === 404 && !isLocal()
          ? `<p class="muted">이 장은 공개 화면에서는 볼 수 없습니다.</p>` : `<p class="muted">불러오지 못했습니다.</p>`;
      }
      return;
    }
    if (changed && studyCur === name) paintStudy(name, studyDocs.get(name).md);   // 내용이 달라졌을 때만 다시 그림
  }

  // ---------- 데이터 상태 ----------
  async function loadStatus() {
    let s;
    try { s = await getJSON("/api/engine"); } catch (e) { if (!e.switching) $("#status-body").innerHTML = `<p class="muted">불러오지 못했습니다.</p>`; return; }
    const en = (s.collector && s.collector.enabled) || {};
    const on = Object.entries(en).filter(([, v]) => v).map(([k]) => k).join(", ");
    const off = Object.entries(en).filter(([, v]) => !v).map(([k]) => k).join(", ");
    const cand = (s.candles || []).map((c) => `<tr><td>${esc(c.symbol.replace("USDT", ""))}</td><td>${esc(c.period)}</td><td class="num">${Number(c.n).toLocaleString()}</td><td class="num">${esc(c.from_kst)} – ${esc(c.to_kst)}</td></tr>`).join("");
    const disc = s.discord ? `${esc(s.discord.t_kst)} · ${s.discord.status === "dry_run" ? "저장만(전송 전)" : esc(s.discord.status)}` : "-";
    $("#status-body").innerHTML = `
      <article class="tile"><div class="tile-h"><h3>수집</h3></div><div class="kv">
        <span class="k">마지막 수집</span><span>${esc(s.collector.last_run_kst || "-")} KST · 호출 ${s.collector.ok_calls ?? "-"} · 실패 ${s.collector.failed_calls ?? "-"}</span>
        <span class="k">주기</span><span>${esc(s.collector.schedule)}</span>
        <span class="k">켜짐</span><span>${esc(on)}</span><span class="k">꺼짐</span><span class="muted">${esc(off)}</span>
        <span class="k">공포탐욕지수</span><span>${s.fear_greed.n}일 · ${esc(s.fear_greed.from)} – ${esc(s.fear_greed.to)} · 출처 alternative.me</span></div></article>
      <article class="tile"><div class="tile-h"><h3>분석</h3></div><div class="kv">
        <span class="k">4시간 사이클</span><span>${s.engine.cycle_enabled ? "켜짐" : "꺼짐"} · 마지막 실행 ${esc(s.engine.last_run_kst || "-")} KST</span>
        <span class="k">규칙</span><span>${s.engine.rules_status === "final" ? "확정 규칙" : "임시 규칙(정미님 답 반영 전)"}${"rules_since_kst" in s.engine ? ` · 이 규칙의 첫 분석 ${esc(s.engine.rules_since_kst || "-")} KST` : ""} <span class="fine num">버전 ${esc(s.engine.rules_version || "-")}</span></span>
        <span class="k">운영 시작</span><span>${esc(s.engine.live_start_kst || "-")} KST (이보다 앞은 과거 재현)</span>
        ${"discord" in s ? `<span class="k">디스코드</span><span>${disc}</span>` : ""}
        ${s.scoring_held ? `<span class="k">채점 보류</span><span class="warn">${s.scoring_held}건 · 다음 4시간봉 값이 깨져 채점을 미룸</span>` : ""}
        ${s.snapshot_deploy ? `<span class="k">저장본(Vercel)</span><span>마지막 저장 ${esc(s.snapshot_deploy.last_ok_kst || "없음")}${s.snapshot_deploy.failing ? ` · <span class="warn">최근 실패 ${esc(s.snapshot_deploy.last_fail_kst || "")}: ${esc(s.snapshot_deploy.last_error || "")}</span>` : ""}</span>` : ""}</div></article>
      ${(s.news || []).length ? `<article class="tile"><div class="tile-h"><h3>뉴스 수집</h3></div><div class="kv">${s.news.map((n) =>
        `<span class="k">${esc(n.label)}</span><span>최근 48시간 ${n.n_48h}건 · 마지막 시도 ${esc(n.last_try_kst || "아직 없음")} · 마지막 성공 ${esc(n.last_ok_kst || "없음")}${n.last_error ? ` · <span class="warn">최근 실패: ${esc(n.last_error)}</span>` : ""}${n.name === "naver_news" && !n.last_try_kst ? " (키 등록 전에는 건너뜀)" : ""}</span>`).join("")}</div></article>` : ""}
      <article class="tile" style="grid-column:1/-1"><div class="tile-h"><h3>바이낸스 현물 캔들</h3></div>
        <div class="tbl"><table class="t"><tr><th>종목</th><th>봉</th><th>개수</th><th>범위(KST, 끝은 마지막 봉 마감)</th></tr>${cand}</table></div></article>`;
  }

  // ---------- 불러오기 ----------
  function renderSettings() {
    document.querySelectorAll("[data-set]").forEach((g) => g.querySelectorAll("button").forEach((b) => b.classList.toggle("on", String(settings[g.dataset.set]) === b.dataset.v)));
    const nt = $("#notify-toggle"), on = settings.notify && "Notification" in window && Notification.permission === "granted";
    nt.textContent = on ? "켜짐" : "꺼짐"; nt.setAttribute("aria-pressed", on); nt.classList.toggle("on", on);
    document.querySelectorAll("#notify-coins input").forEach((i) => { i.checked = settings.notifyCoins.includes(i.value); });
    if (!("Notification" in window)) $("#notify-note").textContent = "이 브라우저는 알림을 지원하지 않습니다. 아이폰은 Safari에서 '홈 화면에 추가'한 뒤에 쓸 수 있습니다.";
    $("#set-rule").textContent = board && board.rules ? board.rules.version : "-";
    const vt = $("#verify-toggle");
    if (vt) { vt.textContent = settings.verify ? "켜짐" : "꺼짐"; vt.setAttribute("aria-pressed", settings.verify); vt.classList.toggle("on", settings.verify); }
  }
  document.querySelectorAll("[data-set]").forEach((g) => g.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    const k = g.dataset.set; settings[k] = b.dataset.v; saveSettings();
    if (k === "theme") setTheme(settings.theme);
    if (k === "palette") { document.documentElement.dataset.palette = settings.palette; if (chartData) drawChart(); }
    if (k === "coin") { selected = settings.coin; if (board) renderNow(); chartSym = null; }
    if (k === "days") { chartDays = Number(settings.days); saveChart(); chartSym = null; }
    renderSettings();
  })));
  $("#notify-toggle").addEventListener("click", async () => {
    if (!("Notification" in window)) return;
    if (!settings.notify) {
      const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
      settings.notify = perm === "granted";
      if (settings.notify) markSeen();   // 켜는 순간 이미 켜져 있던 신호로는 알리지 않는다
    } else settings.notify = false;
    saveSettings(); renderSettings();
  });
  $("#verify-toggle").addEventListener("click", () => {
    settings.verify = !settings.verify; saveSettings(); renderSettings(); applyVerify();
    if (board) { renderRecords(); drawChart(null); if (verifyOn()) { renderScoring(); renderIndStatus(); renderOldEvidence(); renderTrack(); loadHistory(); } }
  });
  document.querySelectorAll("#notify-coins input").forEach((i) => i.addEventListener("change", () => {
    settings.notifyCoins = [...document.querySelectorAll("#notify-coins input:checked")].map((x) => x.value); saveSettings();
  }));
  // 매매 트리거 알림(10-12): 공식 트리거(종목·15분봉 시각·방향)마다 한 번
  const trigs = () => ((V4() || {}).recent || {}).official || [];
  const trigKey = (r) => `T|${r.symbol}|${r.t_bar}|${r.dir}`;
  function seenSet() { try { return new Set(JSON.parse(localStorage.getItem("top3-notified") || "[]")); } catch (e) { return new Set(); } }
  function markSeen() {
    if (!board) return;
    const seen = seenSet(); trigs().forEach((r) => seen.add(trigKey(r)));
    try { localStorage.setItem("top3-notified", JSON.stringify([...seen].slice(-80))); } catch (e) { /* 무시 */ }
  }
  function notifyNew() {
    if (!settings.notify || !("Notification" in window) || Notification.permission !== "granted" || !board) return;
    const seen = seenSet();
    trigs().filter((r) => settings.notifyCoins.includes(r.symbol) && !seen.has(trigKey(r))).forEach((r) => {
      try { new Notification(`${r.short} 매매 트리거 ${r.dir > 0 ? "Long" : "Short"}`, { body: `${kstOf(r.issued_at, true)} KST · Open U$ ${fmtU(r.entry)}`, icon: "img/logo_ai.png", tag: trigKey(r) }); } catch (e) { /* 무시 */ }
    });
    markSeen();
  }

  const qSec = query.get("sec");
  let secDone = false, scopeLocal = false;
  async function load() {
    try {
      const p = getJSON("/api/board", true);
      decision = p.catch(() => null);
      board = await p;
      const wasLocal = scopeLocal;
      scopeLocal = isLocal();
      applyVerify();   // 응답의 scope(로컬·공개)에 맞춰 검증 화면·설정 줄을 보이거나 숨김
      renderNow();
      if (scopeLocal && !wasLocal && !$("#view-ai").hidden) loadHistory();   // 처음부터 AI 분석 탭이면 검증 화면 표도 채움
      notifyNew();
      if (!$("#view-settings").hidden) renderSettings();
      if (loadError) { loadError = false; updateStatusTab(); }
      prefetchStudy();   // 첫 보드 뒤 쉬는 때 공부 목차와 첫 장을 미리 받는다(10-14 7절 9 A)
    } catch (e) {
      loadError = true;
      $("#ref-line").textContent = "자료를 불러오지 못했습니다";
      updateStatusTab();
      return;
    }
    if (qSec && !secDone) { secDone = true; setTimeout(() => goSection(+qSec), 300); }
    loadChart();
  }
  load();
  // 1분마다: 보드와 그래프에 새 데이터가 있는지 확인(엔진은 15분마다 씀). 바뀐 게 없으면 그래프를 다시 그리지 않는다
  setInterval(() => { if (!document.hidden || settings.notify) load(); }, 60 * 1000);   // 알림을 켜면 탭이 뒤에 있어도 확인
  const qView = query.get("view"); // 스크린샷용: ?view=study · ?view=guide · ?view=ai&sec=2
  if (qView && (TITLES[qView] || qView === "guide")) showView(qView);
  else if (TITLES[location.hash.slice(1)]) showView(location.hash.slice(1));
})();
