// Top 3 Crypto 지표 그래프. 기획안 01_운영/Plan/기획서/기획안_지표그래프_2026-10-03.md
// 외부 라이브러리 없이 SVG. 데이터는 /api/chart/{symbol} (엔진이 15분마다 쓰는 닫힌 봉 값).
// 고르기 규칙(nextSelection)은 화면과 분리한 순수 함수라 node 로도 시험한다(05_프론트/tests/chart_selection.test.js).
(function (root) {
  "use strict";
  const ORDER = ["macd", "sto", "srsi", "vpci"];
  const IND = {
    macd: { name: "MACD", tf: "4시간", block: "macd", main: "macd", sig: "signal", kind: "zero", step: 4 * 3600e3 },
    sto: { name: "Stochastic", tf: "1시간", block: "sto", main: "k", sig: "d", kind: "pct", step: 3600e3 },
    srsi: { name: "StochRSI", tf: "1시간", block: "srsi", main: "k", sig: "d", kind: "pct", step: 3600e3 },
    vpci: { name: "VPCI", tf: "15분", block: "vpci", main: "v", sig: "s", kind: "zero", step: 900e3 },
  };
  const SPLIT = () => ({ mode: "split", sel: ORDER.slice() });

  // ---------- 고르기 규칙 (기획안 §3) ----------
  // split(처음, 4칸) → 누른 하나만 / pick 상태에서 흐린 것 → 더해서 겹침 / 선택된 것 → 뺌 / 마지막 하나 → split
  function nextSelection(state, id) {
    if (!IND[id]) return state;
    if (!state || state.mode !== "pick") return { mode: "pick", sel: [id] };
    if (state.sel.includes(id)) {
      if (state.sel.length === 1) return SPLIT();
      return { mode: "pick", sel: state.sel.filter((x) => x !== id) };
    }
    return { mode: "pick", sel: ORDER.filter((x) => state.sel.includes(x) || x === id) };
  }
  function normalize(state) {
    if (!state || state.mode !== "pick" || !Array.isArray(state.sel)) return SPLIT();
    const sel = ORDER.filter((x) => state.sel.includes(x));
    return sel.length ? { mode: "pick", sel } : SPLIT();
  }

  // ---------- 그리기 도우미 ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const KST = 9 * 3600e3;
  const pad2 = (n) => String(n).padStart(2, "0");
  function kst(ms, withDate = true) {
    const d = new Date(ms + KST);
    const hm = `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
    return withDate ? `${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())} ${hm}` : hm;
  }
  // 축 숫자는 짧게: 86,900 → 86.9k, 1,014 → 1.01k
  const fmtAx = (v) => { const a = Math.abs(v); return a >= 1e4 ? `${(v / 1e3).toFixed(1)}k` : a >= 1e3 ? `${(v / 1e3).toFixed(2)}k` : a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(2) : v.toPrecision(2); };
  const fmt = (v) => v == null ? "-" : Math.abs(v) >= 1000 ? Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 }) : Math.abs(v) >= 1 ? Number(v).toFixed(2) : Number(v).toFixed(4);
  // 마지막으로 t 이하인 위치(이진 탐색)
  function lastAtOrBefore(ts, t) {
    let lo = 0, hi = ts.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (ts[m] <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  // 값이 없거나(null) 시간 간격이 봉 길이의 1.5배를 넘으면 선을 끊는다(봉 누락)
  function pathOf(ts, vs, x, y, step) {
    let d = "", pen = false, prevT = null;
    for (let i = 0; i < ts.length; i++) {
      const v = vs[i];
      if (v == null || (prevT != null && ts[i] - prevT > step * 1.5)) pen = false;
      if (v != null) { d += `${pen ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`; pen = true; }
      prevT = ts[i];
    }
    return d;
  }
  // 0선 지표의 눈금: 보이는 구간 |값|의 98% 분위수(튀는 값 몇 개가 눈금을 다 차지하지 않게).
  // 최대값이 그보다 1.5배 넘게 크면 그 부분은 칸 밖으로 잘리고 clipped=true. 실제 값은 마우스를 올리면 보인다.
  function robustAbs(block, keys, from) {
    const a = [];
    if (!block || !block.t) return { m: 1, clipped: false };
    for (const k of keys) (block[k] || []).forEach((v, i) => { if (v != null && block.t[i] >= from) a.push(Math.abs(v)); });
    if (!a.length) return { m: 1, clipped: false };
    a.sort((p, q) => p - q);
    const max = a[a.length - 1], q98 = a[Math.min(a.length - 1, Math.floor(a.length * 0.98))];
    if (!q98 || max <= q98 * 1.5) return { m: max || 1, clipped: false };
    return { m: q98, clipped: true };
  }
  let uid = 0;

  // ---------- 그래프 ----------
  // data: /api/chart 응답, state: {mode, sel}, opts: {width, dirs:{macd:1,...}, added:"sto"}
  function render(data, state, opts) {
    const W = Math.max(320, Math.round(opts.width || 900));
    const narrow = W < 600;
    const L = narrow ? 38 : 46, R = narrow ? 44 : 58;
    const priceH = narrow ? 84 : 104, gap = 12;
    const st = normalize(state);
    const panes = st.mode === "split" ? ORDER.map((id) => [id]) : [st.sel];
    const paneH = st.mode === "split" ? (narrow ? 82 : 100) : (narrow ? 180 : 230);
    const H = priceH + panes.length * (paneH + gap) + 24;
    const t0 = data.range.from, t1 = data.range.to;
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const parts = [], above = [];   // above: 선 위에 그릴 것(칸 제목)

    // 시간 눈금
    const days = data.days || 3;
    // 눈금 간격: 글자가 겹치지 않는 가장 촘촘한 간격(3·6·12·24·48시간)
    const plotW = W - L - R;
    const labelOf = (t, step) => step >= 24 * 3600e3 ? kst(t).slice(0, 5) : days <= 1 ? kst(t, false) : kst(t);
    const tickStep = [3, 6, 12, 24, 48].map((h) => h * 3600e3).find((st) => {
      const w = (st >= 24 * 3600e3 ? 36 : days <= 1 ? 34 : 70) + 18;
      return ((t1 - t0) / st) * w <= plotW;
    }) || 48 * 3600e3;
    const firstTick = Math.ceil((t0 + KST) / tickStep) * tickStep - KST;
    for (let t = firstTick; t <= t1; t += tickStep) {
      parts.push(`<line class="vgrid" x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="0" y2="${H - 20}"/>`);
      parts.push(`<text class="ax" x="${x(t).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(labelOf(t, tickStep))}</text>`);
    }
    // 빠진 봉 구간: 그 시간대를 쓰는 칸에만 띠(가격 칸은 15분봉)
    const TF = { macd: "4h", sto: "1h", srsi: "1h", vpci: "15m" };
    const gapBands = (tfs, y0, h) => (data.gaps || []).filter((g) => tfs.includes(g.tf)).map((g) => {
      const a = Math.max(t0, g.from), b = Math.min(t1, g.to);
      return b > a ? `<rect class="gap" x="${x(a).toFixed(1)}" y="${y0}" width="${Math.max(1, x(b) - x(a)).toFixed(1)}" height="${h}"><title>${esc(g.tf)} 봉 누락 ${esc(kst(g.from))} ~ ${esc(kst(g.to))}</title></rect>` : "";
    }).join("");
    parts.push(gapBands(["15m"], 0, priceH));

    // 가격 칸
    const P = data.price || { t: [], c: [] };
    const pv = P.c.filter((v) => v != null);
    const plo = Math.min(...pv), phi = Math.max(...pv);
    const band = 30;   // 위쪽 띠(칸 제목·분석 점수 라벨)는 가격선과 겹치지 않게 비워 둠
    const py = (v) => band + (1 - (v - plo) / Math.max(1e-12, phi - plo)) * (priceH - band - 8);
    above.push(`<text class="pane-t" x="${L}" y="12">가격 · 15분 종가</text>`);
    if (pv.length) {
      parts.push(`<path class="price-line" d="${pathOf(P.t, P.c, x, py, 900e3)}"/>`);
      parts.push(`<text class="ax" x="${W - R + 4}" y="${py(phi) + 4}">${esc(fmtAx(phi))}</text><text class="ax" x="${W - R + 4}" y="${py(plo)}">${esc(fmtAx(plo))}</text>`);
    }
    // 4시간 분석 시각(운영 기록): 세로 점선 + 점수, 확실한 신호 ★
    // 겹치지 않게: 오른쪽(최근)부터 두 줄에 번갈아 놓고, 둘 다 자리가 없으면 글자 없이 선만(마우스를 올리면 제목)
    const rowLast = [Infinity, Infinity];
    (data.analyses || []).filter((a) => a.t >= t0 && a.t <= t1).sort((p, q) => q.t - p.t).forEach((a) => {
      const cls = a.score > 0 ? "up" : a.score < 0 ? "down" : "zero";
      const lab = a.score == null ? "–" : `${a.score > 0 ? "+" : a.score < 0 ? "−" : ""}${Math.abs(a.score)}${a.strong ? "★" : ""}`;
      const ax = x(a.t), title = `<title>${esc(kst(a.t))} 분석 · 점수 ${esc(lab)}${a.strong ? " · 확실한 신호" : ""}</title>`;
      parts.push(`<line class="aline" x1="${ax.toFixed(1)}" x2="${ax.toFixed(1)}" y1="14" y2="${H - 20}">${title}</line>`);
      const row = rowLast.findIndex((lx) => lx - ax >= 40);
      if (row < 0) return;
      rowLast[row] = ax;
      parts.push(`<text class="alab ${cls}" x="${(ax - 3).toFixed(1)}" y="${13 + row * 12}" text-anchor="end">${title}${esc(lab)}</text>`);
    });

    // 지표 칸
    let top = priceH + gap;
    const paneInfo = [];
    panes.forEach((ids) => {
      const y0 = top, h = paneH, mid = y0 + h / 2, pad = 6, clipId = `cp${++uid}`;
      const pctY = (v) => y0 + pad + (1 - v / 100) * (h - 2 * pad);
      const scales = {};
      ids.forEach((id) => {
        const s = IND[id];
        if (s.kind === "pct") scales[id] = pctY;
        else {
          const { m, clipped } = robustAbs(data[s.block], [s.main, s.sig], t0);
          scales[id] = (v) => mid - (v / m) * (h / 2 - pad) * 0.9;
          scales[id].m = m;
          scales[id].clipped = clipped;
        }
      });
      parts.push(`<rect class="pane" x="${L}" y="${y0}" width="${W - L - R}" height="${h}" rx="6"/>`);
      parts.push(gapBands(ids.map((id) => TF[id]), y0, h));
      parts.push(`<clipPath id="${clipId}"><rect x="${L}" y="${y0}" width="${W - L - R}" height="${h}"/></clipPath>`);
      const hasPct = ids.some((id) => IND[id].kind === "pct");
      const zone = data.zone || { upper: 80, lower: 20 };   // 판정 규칙의 기준선(설정값)
      if (hasPct) {
        [zone.upper, zone.lower].forEach((v) => parts.push(`<line class="zone" x1="${L}" x2="${W - R}" y1="${pctY(v).toFixed(1)}" y2="${pctY(v).toFixed(1)}"/><text class="ax" x="${L - 4}" y="${(pctY(v) + 4).toFixed(1)}" text-anchor="end">${v}</text>`));
      }
      parts.push(`<line class="mid" x1="${L}" x2="${W - R}" y1="${mid.toFixed(1)}" y2="${mid.toFixed(1)}"/>`);
      if (!hasPct || ids.length > 1) parts.push(`<text class="ax" x="${L - 4}" y="${(mid + 4).toFixed(1)}" text-anchor="end">${hasPct ? "50·0" : "0"}</text>`);
      // 칸 제목
      // 좁은 화면에서 여러 지표를 겹치면 이름이 오른쪽 눈금과 겹쳐서 짧은 이름만(10-06 호연 P2, 아이폰 15 세로)
      const SHORTN = { macd: "MACD", sto: "Sto", srsi: "SRSI", vpci: "VPCI" };
      const title = narrow && ids.length > 1
        ? ids.map((id) => `<tspan class="c-${id}">${esc(SHORTN[id] || IND[id].name)}</tspan>`).join('<tspan class="ax"> · </tspan>')
        : ids.map((id) => `<tspan class="c-${id}">${esc(IND[id].name)}</tspan> <tspan class="ax">${esc(IND[id].tf)}</tspan>`).join('<tspan class="ax">  +  </tspan>');
      above.push(`<text class="pane-t" x="${L + 8}" y="${y0 + 15}">${title}</text>`);
      // 오른쪽 눈금(0선 지표는 각자): ±최대 절댓값
      let ri = 0;
      ids.forEach((id) => {
        const s = IND[id];
        if (s.kind !== "zero") return;
        const m = scales[id].m;
        const cl = scales[id].clipped ? `<title>튀는 값 일부는 칸 밖으로 잘림. 마우스를 올리면 실제 값</title>` : "";
        const ini = ids.length > 1 ? `${IND[id].name[0]} ` : "";   // 겹칠 때는 어느 지표 눈금인지 머리글자
        parts.push(`<text class="ax c-${id}" x="${W - R + 4}" y="${(y0 + 12 + ri * 12).toFixed(1)}">${cl}${ini}+${esc(fmtAx(m))}${scales[id].clipped ? "↑" : ""}</text><text class="ax c-${id}" x="${W - R + 4}" y="${(y0 + h - 4 - ri * 12).toFixed(1)}">${cl}${ini}−${esc(fmtAx(m))}${scales[id].clipped ? "↓" : ""}</text>`);
        ri += 1;
      });
      if (ids.length === 1 && IND[ids[0]].kind === "pct") parts.push(`<text class="ax" x="${W - R + 4}" y="${(y0 + 12).toFixed(1)}">0~100</text>`);
      // 선: 본선 실선, 신호선 점선
      ids.forEach((id) => {
        const s = IND[id], b = data[s.block];
        if (!b || !b.t || !b.t.length) return;
        const y = scales[id];
        const anim = opts.added === id ? " draw" : "";
        // 셋 이상 겹치면 신호선(점선)은 숨김(선 8개는 읽기 어려움). 값은 마우스를 올리면 보임
        if (ids.length < 3) parts.push(`<path class="sig c-${id}${anim}" clip-path="url(#${clipId})" d="${pathOf(b.t, b[s.sig], x, y, s.step)}"/>`);
        parts.push(`<path class="main c-${id}${anim}" clip-path="url(#${clipId})" d="${pathOf(b.t, b[s.main], x, y, s.step)}"/>`);
        // 교차 사건(판정과 같은 사건): ▲ Long, ▼ Short
        (data.events || []).filter((e) => e.ind === id && e.t >= t0).forEach((e) => {
          const i = b.t.indexOf(e.t);
          const v = i >= 0 ? b[s.main][i] : null;
          if (v == null) return;
          const cx = x(e.t), cy = Math.min(y0 + h - 4, Math.max(y0 + 4, y(v))), up = e.dir > 0, r = narrow || id === "vpci" ? 4 : 5;
          const pts = up ? `${cx},${cy - r - 2} ${cx - r},${cy + r - 2} ${cx + r},${cy + r - 2}` : `${cx},${cy + r + 2} ${cx - r},${cy - r + 2} ${cx + r},${cy - r + 2}`;
          parts.push(`<polygon class="ev ${up ? "up" : "down"}" points="${pts}"><title>${esc(IND[id].name)} ${esc(kst(e.t))} ${up ? "Long" : "Short"} 교차</title></polygon>`);
        });
      });
      paneInfo.push({ ids, y0, h, scales });
      top += h + gap;
    });

    const label = `지표 그래프 ${data.symbol}, 최근 ${days}일. ${st.mode === "split" ? "네 지표를 나눠 보기" : st.sel.map((id) => IND[id].name).join("과 ") + (st.sel.length > 1 ? " 겹쳐 보기" : " 보기")}`;
    const svg = `<svg class="ichart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(label)}">${parts.join("")}${above.join("")}
      <line class="hover-line" x1="0" x2="0" y1="0" y2="${H - 20}" visibility="hidden"/><g class="hover-dots"></g>
      <rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H - 20}"/></svg>`;
    return { svg, W, H, L, R, x, t0, t1, paneInfo, priceY: py };
  }

  // 마우스 위치의 값(보이는 지표, 시간대가 다르면 그 시각 직전에 닫힌 봉)
  // t 가 빠진 봉 구간 안이면(앞 봉과 다음 봉 사이가 한 봉보다 김) 직전 값을 보여 주지 않고 gap 으로 표시
  // (10-04 GPT-6.1 Sol: 누락 구간에서도 오래된 값을 보여 줬음)
  const inGap = (ts, i, step, t) => i < ts.length - 1 && ts[i + 1] - ts[i] > step && t >= ts[i] + step;
  function valuesAt(data, ids, t) {
    const out = [];
    const P = data.price;
    const pi = lastAtOrBefore(P.t, t);
    if (pi >= 0) out.push({ id: "price", t: P.t[pi], label: "가격", v: P.c[pi], gap: inGap(P.t, pi, 900e3, t) });
    ids.forEach((id) => {
      const s = IND[id], b = data[s.block];
      if (!b || !b.t) return;
      const i = lastAtOrBefore(b.t, t);
      if (i < 0) return;
      out.push({ id, t: b.t[i], label: `${s.name} ${s.tf}`, v: b[s.main][i], s: b[s.sig][i], gap: inGap(b.t, i, s.step, t) });
    });
    return out;
  }

  const api = { ORDER, IND, nextSelection, normalize, render, valuesAt, kst, fmt, lastAtOrBefore, SPLIT };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Top3Chart = api;
})(typeof window !== "undefined" ? window : globalThis);
