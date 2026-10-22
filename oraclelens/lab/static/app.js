/* OracleLens dashboard: results explorer + live lab. No dependencies. */
(() => {
  "use strict";

  const BOOT = window.OL_BOOT || { live: false, data: null };
  const SVG = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------------ labels
  const AGG = {
    median: { label: "Median", c: "--s1" },
    trimmed_mean: { label: "Trimmed mean", c: "--s2" },
    weighted: { label: "Inverse-error weighted", c: "--s3" },
    quorum_median: { label: "Quorum median", c: "--s4" },
    reputation: { label: "Reputation-weighted", c: "--s5" },
  };
  const DET = {
    mad: "MAD", hampel: "Hampel", rolling: "Rolling baseline",
    cusum: "CUSUM", vol_mad: "Volatility-aware MAD",
  };
  const CAUSE = {
    none: { label: "No fault", c: null },
    stale: { label: "Stale", c: "--s4" },
    delayed: { label: "Delayed", c: "--s7" },
    offline: { label: "Offline", c: "--missing" },
    isolated_outlier: { label: "Isolated outlier", c: "--s2" },
    correlated_source: { label: "Correlated source", c: "--s3" },
    gradual_drift: { label: "Gradual drift", c: "--s5" },
    coordinated_manipulation: { label: "Coordinated manipulation", c: "--s8" },
    insufficient_evidence: { label: "Insufficient evidence", c: null },
  };
  const DEFENSE_C = {
    "spot median (no defense)": "--s1", "node-consensus alarm": "--s2", "TWAP 60 min": "--s3",
    "rate limit 2%/min": "--s4", "volatility circuit breaker": "--s5", "TWAP + breaker": "--s6",
    "per-account borrow cap": "--s7",
  };
  const FAULTS = {
    outlier: { label: "Random outliers", fields: { count: 2, start: 60, end: 500, prob: 0.2 } },
    collusion: { label: "Collusion", fields: { count: 4, start: 100, end: 300, bias: 0.04 } },
    slow_burn: { label: "Slow-burn adversary", fields: { count: 3, start: 150, growth: 0.0005, max_bias: 0.05 } },
    drift: { label: "Gradual drift", fields: { count: 1, start: 100, rate: 0.0003, max_bias: 0.05 } },
    stale: { label: "Stale data", fields: { count: 1, start: 120, end: 220 } },
    replay: { label: "Replay old data", fields: { count: 1, start: 140, end: 240, age: 20 } },
    offline: { label: "Nodes offline", fields: { count: 3, start: 250, end: 300 } },
    partition: { label: "Network partition", fields: { count: 7, start: 250, end: 300 } },
    delay: { label: "Delayed reports", fields: { count: 2, start: 100, end: 200, extra_ms: 1500 } },
    source_fault: { label: "Failing exchange", fields: { source: 2, start: 350, end: 380, bias: 0.03 } },
    flash_spike: { label: "Flash spike", fields: { source: 1, start: 200, bias: 0.2 } },
    market_shock: { label: "Legitimate market move", fields: { start: 300, size: -0.15, duration: 3 } },
  };
  const FIELD_LABEL = {
    count: "Nodes", source: "Exchange #", start: "Start round", end: "End round", prob: "Hit rate",
    bias: "Bias", growth: "Growth/round", max_bias: "Max bias", rate: "Rate/round", age: "Age (rounds)",
    extra_ms: "Extra ms", size: "Move", duration: "Rounds",
  };

  // ----------------------------------------------------------------- helpers
  const $ = (sel, el = document) => el.querySelector(sel);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const col = (v) => (v && v.startsWith("--") ? css(v) : v);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") {
        for (const [sk, sv] of Object.entries(v)) {
          if (sv == null) continue;
          if (sk.startsWith("--")) el.style.setProperty(sk, sv); else el.style[sk] = sv;
        }
      }
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false)
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  function s(tag, attrs, ...kids) {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
    for (const kid of kids.flat()) if (kid != null)
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const pct = (v, d = 0) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`);
  const num = (v, d = 3) => (v == null ? "–" : Number(v).toFixed(d));
  const money = (v) => (v == null ? "–" : `$${(v / 1e6).toFixed(1)}M`);
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const finite = (v) => v != null && Number.isFinite(v);
  function legend(items) {
    return h("div", { class: "legend" }, items.map((it) =>
      h("span", {}, h("i", { class: it.kind || "", style: { "--c": col(it.c) } }), it.label)));
  }
  function seg(options, value, onChange, label) {
    const wrap = h("div", { class: "seg", role: "group", "aria-label": label });
    for (const [v, text] of options) {
      wrap.append(h("button", {
        type: "button", "aria-pressed": String(v === value),
        onclick: () => { [...wrap.children].forEach((b) => b.setAttribute("aria-pressed", "false"));
          wrap.querySelector(`[data-v="${v}"]`).setAttribute("aria-pressed", "true"); onChange(v); },
        "data-v": v,
      }, text));
    }
    return wrap;
  }

  // ------------------------------------------------------------------- ticks
  function niceTicks(lo, hi, n = 5) {
    if (!(hi > lo)) { lo -= 1; hi += 1; }
    const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), e = raw / mag;
    const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
    return out;
  }
  function logTicks(lo, hi) {
    const out = [];
    for (let p = Math.floor(Math.log10(lo)); p <= Math.ceil(Math.log10(hi)); p++)
      for (const m of [1, 2, 5]) { const v = m * 10 ** p; if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
    return out;
  }

  // -------------------------------------------------------------- line chart
  /* series: {name, c, x[], y[], lo?, hi?, dash?, width?, markers?}
     opts: height, xfmt, yfmt, xlabel, ylabel, ylog, ydomain, xdomain, hlines, bands, tipTitle */
  function lineChart(box, series, o = {}) {
    box.classList.add("chart");
    box.innerHTML = "";
    const W = Math.max(280, box.clientWidth || 640), H = o.height || 300;
    const m = { l: o.ml || 58, r: 18, t: 14, b: o.xlabel ? 44 : 28 };
    const xs = [], ys = [];
    for (const sr of series) sr.x.forEach((x, i) => {
      if (finite(x) && finite(sr.y[i])) { xs.push(x); ys.push(sr.y[i]); }
      if (sr.lo && finite(sr.lo[i])) ys.push(sr.lo[i]);
      if (sr.hi && finite(sr.hi[i])) ys.push(sr.hi[i]);
    });
    if (!xs.length) { box.append(h("p", { class: "note" }, "No data to plot.")); return null; }
    let [x0, x1] = o.xdomain || [Math.min(...xs), Math.max(...xs)];
    let [y0, y1] = o.ydomain || [Math.min(...ys), Math.max(...ys)];
    if (o.ylog) { y0 = Math.max(y0, 1e-9); }
    else if (!o.ydomain) { const pad = (y1 - y0) * 0.06 || Math.abs(y1) * 0.05 || 1; y0 -= pad; y1 += pad; }
    const ly = (v) => (o.ylog ? Math.log10(v) : v);
    const X = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
    const Y = (v) => H - m.b - ((ly(v) - ly(y0)) / (ly(y1) - ly(y0) || 1)) * (H - m.t - m.b);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.title || "chart" });
    const clipId = `clip${++lineChart.n}`;
    svg.append(s("defs", {}, s("clipPath", { id: clipId },
      s("rect", { x: m.l, y: m.t - 6, width: W - m.l - m.r, height: H - m.t - m.b + 12 }))));
    const plotG = s("g", { "clip-path": `url(#${clipId})` });

    const yt = o.ylog ? logTicks(y0, y1) : niceTicks(y0, y1, o.yticks || 5);
    for (const t of yt) {
      if (t < y0 - 1e-12 || t > y1 + 1e-12) continue;
      svg.append(s("line", { class: "grid", x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t) }));
      svg.append(s("text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, (o.yfmt || String)(t)));
    }
    for (const t of niceTicks(x0, x1, Math.max(3, Math.floor((W - m.l) / 90)))) {
      if (t < x0 - 1e-12 || t > x1 + 1e-12) continue;
      svg.append(s("text", { x: X(t), y: H - m.b + 18, "text-anchor": "middle" }, (o.xfmt || String)(t)));
    }
    svg.append(s("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
    if (o.xlabel) svg.append(s("text", { class: "axis-title", x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle" }, o.xlabel));
    if (o.ylabel) svg.append(s("text", { class: "axis-title", transform: `translate(14 ${(m.t + H - m.b) / 2}) rotate(-90)`, "text-anchor": "middle" }, o.ylabel));

    for (const b of o.bands || []) {
      svg.append(s("rect", { x: X(b.x0), width: Math.max(1, X(b.x1) - X(b.x0)), y: m.t, height: H - m.t - m.b,
        fill: col(b.c || "--accent"), "fill-opacity": b.opacity || 0.08 }));
      if (b.label) svg.append(s("text", { x: X(b.x1) + 6, y: m.t + 14, class: "ref-label" }, b.label));
    }
    for (const r of o.hlines || []) {
      svg.append(s("line", { class: "ref", x1: m.l, x2: W - m.r, y1: Y(r.y), y2: Y(r.y) }));
      if (r.label) svg.append(s("text", { class: "ref-label", x: m.l + 6, y: Y(r.y) - 6 }, r.label));
    }
    if (o.diagonal) svg.append(s("line", { class: "ref", x1: X(x0), y1: Y(x0), x2: X(x1), y2: Y(x1) }));

    const path = (xa, ya) => {
      let d = "", pen = false;
      xa.forEach((x, i) => {
        const y = ya[i];
        if (!finite(x) || !finite(y) || (o.ylog && y <= 0)) { pen = false; return; }
        d += `${pen ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`; pen = true;
      });
      return d;
    };
    svg.append(plotG);
    for (const sr of series) if (sr.lo && sr.hi) {
      const idx = sr.x.map((_, i) => i).filter((i) => finite(sr.lo[i]) && finite(sr.hi[i]));
      if (idx.length > 1) {
        const d = idx.map((i, k) => `${k ? "L" : "M"}${X(sr.x[i])},${Y(sr.hi[i])}`).join("") +
          idx.slice().reverse().map((i) => `L${X(sr.x[i])},${Y(sr.lo[i])}`).join("") + "Z";
        plotG.append(s("path", { d, fill: col(sr.c), "fill-opacity": 0.14, stroke: "none" }));
      }
    }
    for (const sr of series) {
      plotG.append(s("path", { d: path(sr.x, sr.y), fill: "none", stroke: col(sr.c), "stroke-width": sr.width || 2,
        "stroke-dasharray": sr.dash ? "6 4" : null, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (sr.markers) sr.x.forEach((x, i) => { if (finite(sr.y[i]))
        plotG.append(s("circle", { cx: X(x), cy: Y(sr.y[i]), r: 3.2, fill: col(sr.c), stroke: col("--panel"), "stroke-width": 1.5 })); });
    }
    for (const a of o.annotations || []) {
      svg.append(s("text", { x: X(a.x) + (a.dx || 6), y: Y(a.y) + (a.dy || -8), class: "ref-label",
        "font-weight": 600, "text-anchor": a.anchor || "start" }, a.text));
    }

    // cursor + hover
    const cursor = s("line", { class: "cursor", y1: m.t, y2: H - m.b, visibility: "hidden" });
    const dots = s("g", {});
    svg.append(cursor, dots);
    const tip = h("div", { class: "tip" });
    const hit = s("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    svg.append(hit);
    const nearest = (arr, v) => {
      let best = -1, bd = Infinity;
      arr.forEach((x, i) => { const d = Math.abs(x - v); if (finite(x) && d < bd) { bd = d; best = i; } });
      return best;
    };
    function show(xv, withTip, evt) {
      cursor.setAttribute("x1", X(xv)); cursor.setAttribute("x2", X(xv)); cursor.setAttribute("visibility", "visible");
      dots.innerHTML = "";
      if (!withTip) { tip.style.display = "none"; return; }
      const rows = [];
      for (const sr of series) {
        if (sr.noTip) continue;
        const i = nearest(sr.x, xv);
        if (i < 0 || !finite(sr.y[i])) continue;
        dots.append(s("circle", { cx: X(sr.x[i]), cy: Y(sr.y[i]), r: 4, fill: col(sr.c), stroke: col("--panel"), "stroke-width": 2 }));
        rows.push(`<div class="row" style="--c:${col(sr.c)}"><span><i></i>${esc(sr.name)}</span><span>${esc((o.yfmtTip || o.yfmt || String)(sr.y[i]))}</span></div>`);
      }
      tip.innerHTML = `<b>${esc((o.tipTitle || o.xfmt || String)(xv))}</b>${rows.join("")}`;
      tip.style.display = "block";
      const bx = box.getBoundingClientRect(), px = evt.clientX - bx.left;
      const left = px + 16 + tip.offsetWidth > bx.width ? px - tip.offsetWidth - 16 : px + 16;
      tip.style.left = `${Math.max(0, left)}px`;
      tip.style.top = `${Math.max(0, evt.clientY - bx.top - 20)}px`;
    }
    let fixed = null;
    const xFromEvt = (evt) => {
      const r = svg.getBoundingClientRect(), px = ((evt.clientX - r.left) / r.width) * W;
      return x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0);
    };
    hit.addEventListener("pointermove", (e) => {
      let xv = xFromEvt(e);
      if (o.snap) xv = o.snap(xv);
      show(xv, true, e);
    });
    hit.addEventListener("pointerleave", () => {
      tip.style.display = "none"; dots.innerHTML = "";
      if (fixed == null) cursor.setAttribute("visibility", "hidden"); else setCursor(fixed);
    });
    if (o.onPick) hit.addEventListener("click", (e) => o.onPick(xFromEvt(e)));
    function setCursor(xv) {
      fixed = xv;
      if (xv == null) { cursor.setAttribute("visibility", "hidden"); return; }
      cursor.setAttribute("x1", X(xv)); cursor.setAttribute("x2", X(xv)); cursor.setAttribute("visibility", "visible");
    }
    box.append(svg, tip);
    return { setCursor, X, Y, svg };
  }

  lineChart.n = 0;

  // keep charts sized to their containers
  const redraws = new Set();
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => redraws.forEach((f) => f()), 120);
  });
  function responsive(draw) { redraws.add(draw); draw(); return draw; }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => redraws.forEach((f) => f()));

  // ------------------------------------------------------------------- data
  let DATA = BOOT.data;
  async function loadData() {
    if (DATA) return DATA;
    const r = await fetch("api/results");
    if (!r.ok) throw new Error(`Could not load results (HTTP ${r.status}).`);
    DATA = await r.json();
    return DATA;
  }
  const sweep = (name) => DATA.sweeps.find((x) => x.name === name);
  const bp = (sw, tol, agg) => ((sw && sw.breaking_points[tol]) || {})[agg] || {};
  function bpText(b) {
    if (!b || b.breaking_point == null) return "never";
    const p = pct(b.breaking_point);
    if (b.ci_low == null || (Math.abs(b.ci_low - b.breaking_point) < 1e-9 && Math.abs(b.ci_high - b.breaking_point) < 1e-9)) return p;
    return `${p} (${pct(b.ci_low)}–${pct(b.ci_high)})`;
  }
  const sweepLabel = (sw) => sw.title.replace(/\s*\(.*\)$/, "");

  function curveSeries(sw, tol) {
    const curves = sw.curves[tol] || {};
    const seen = new Map();
    return Object.entries(curves).map(([agg, c]) => {
      const key = c.fail_prob.map((v) => (v == null ? "n" : v.toFixed(5))).join(",");
      const dup = seen.get(key);
      if (!dup) seen.set(key, AGG[agg] ? AGG[agg].label : agg);
      return { key: agg, name: (AGG[agg] ? AGG[agg].label : agg) + (dup ? ` (same as ${dup.toLowerCase()})` : ""),
        c: AGG[agg] ? AGG[agg].c : "--s8", x: c.fraction, y: c.fail_prob, lo: c.ci_low, hi: c.ci_high,
        markers: true, dash: !!dup };
    });
  }
  function breakingChart(box, sw, tol, height) {
    const series = curveSeries(sw, tol);
    const ann = [], used = new Set();
    for (const sr of series) {
      const b = bp(sw, tol, sr.key).breaking_point;
      if (b == null || sr.dash || used.has(b.toFixed(4))) continue;
      used.add(b.toFixed(4));
      const i = sr.x.findIndex((x) => Math.abs(x - b) < 1e-6);
      if (i >= 0) ann.push({ x: b, y: sr.y[i], text: pct(b) });
    }
    box.innerHTML = "";
    const leg = legend(series.map((sr) => ({ c: sr.c, label: sr.name, kind: sr.dash ? "dash" : "" })));
    const plot = h("div");
    box.append(leg, plot);
    lineChart(plot, series, {
      height: height || 320, ydomain: [-0.02, 1.02], yfmt: (v) => pct(v), xfmt: (v) => pct(v),
      xlabel: sw.by_source ? "Nodes reading a failed exchange" : "Faulty nodes",
      ylabel: `P(round error > ${pct(+tol, 1)})`, hlines: [{ y: sw.threshold, label: `failure threshold ${pct(sw.threshold)}` }],
      annotations: ann, tipTitle: (v) => `${pct(v)} faulty`, snap: (v) => {
        const xs = series[0].x; let best = xs[0];
        xs.forEach((x) => { if (Math.abs(x - v) < Math.abs(best - v)) best = x; }); return best;
      }, title: sw.title,
    });
  }

  // ------------------------------------------------------------ view: findings
  function viewFindings(root) {
    const tol = "0.01";
    const sw = sweep("bp_collusion_random") || DATA.sweeps[0];
    const rep = bp(sw, tol, "reputation").breaking_point, med = bp(sw, tol, "median").breaking_point;
    const cal = DATA.calibration && DATA.calibration.splits["holdout-family"];
    const slow = sweep("bp_slow_burn_random");
    const mango = DATA.mango;
    const breaker = mango && mango.loss_prevented_across_seeds.find((r) => r.defense === "volatility circuit breaker");
    const both = mango && mango.loss_prevented_across_seeds.find((r) => r.defense === "TWAP + breaker");

    const fig = h("div", { class: "figure" });
    root.append(
      h("section", { class: "hero" },
        h("div", { class: "stack" },
          h("h1", {}, `Trust scores made the oracle easier to break, not harder.`),
          h("p", { class: "lede" },
            `When colluding nodes reported a wrong price, an aggregator that weights nodes by long-term reputation failed with ${pct(rep)} of nodes compromised. A plain median held until ${pct(med)}.`),
          h("div", { class: "hero-numbers" },
            h("div", { style: { "--c": col(AGG.reputation.c) } }, h("strong", {}, pct(rep)), h("span", {}, "Reputation-weighted")),
            h("div", { style: { "--c": col(AGG.median.c) } }, h("strong", {}, pct(med)), h("span", {}, "Median"))),
          h("p", { class: "note" }, `${sw.nodes} simulated nodes, ${sw.seeds} random seeds per point, attack size and direction randomized. A method "breaks" when more than ${pct(sw.threshold)} of rounds miss the true price by over 1%.`)),
        fig),
      h("section", { class: "section" },
        h("div", { class: "claims" },
          h("div", { class: "claim" },
            h("p", { class: "q" }, "Which aggregators tolerate faulty nodes?"),
            h("h3", {}, "Median and inverse-error weighting hold to a majority"),
            h("p", {}, `Trimmed mean broke at ${pct(bp(sw, tol, "trimmed_mean").breaking_point)} and reputation weighting at ${pct(rep)}. Trusted attackers keep their weight for many rounds after they start lying.`),
            h("a", { href: "#breaking" }, "Explore all sweeps")),
          h("div", { class: "claim" },
            h("p", { class: "q" }, "Can slow, patient attacks evade defenses?"),
            h("h3", {}, "Slow attacks cost reputation weighting the most"),
            h("p", {}, slow ? `Attackers who build trust first and then drift slowly broke reputation weighting at ${bpText(bp(slow, tol, "reputation"))}, against ${pct(bp(slow, tol, "median").breaking_point)} for the median.` : "Run the slow-burn sweep to see this result."),
            h("a", { href: "#lab" }, "Try it in the live lab")),
          h("div", { class: "claim" },
            h("p", { class: "q" }, "Does the diagnosis know when it is unsure?"),
            h("h3", {}, cal ? `Confidence was off by ${num(cal.raw.ece, 2)}; calibrated, ${num(cal.calibrated.ece, 2)}` : "Calibration"),
            h("p", {}, cal ? `On attack types it never saw in training, calibrated confidence matched real accuracy, and the engine said "insufficient evidence" for ${pct(1 - cal.calibrated.coverage)} of incidents instead of guessing.` : ""),
            h("a", { href: "#diagnosis" }, "See calibration")))),
      mango ? h("section", { class: "section" },
        h("div", { class: "claims" },
          h("div", { class: "claim", style: { gridColumn: "span 2" } },
            h("p", { class: "q" }, "Case study: a Mango Markets–style price pump"),
            h("h3", {}, "Every node reported the pumped price honestly, so consensus checks saw nothing"),
            h("p", {}, `A volatility circuit breaker stopped ${pct(breaker && breaker.mean, 1)} of the modeled loss but froze honest borrowing after a legitimate jump. Adding a time-weighted average made it worse: ${pct(both && both.mean)} stopped, because the average still remembered the pump when borrowing reopened.`),
            h("a", { href: "#mango" }, "Read the case study"))))
        : null);
    responsive(() => breakingChart(fig, sw, tol, 300));
  }

  // ---------------------------------------------------------- view: breaking
  function viewBreaking(root) {
    const st = { name: (sweep("bp_collusion_random") || DATA.sweeps[0]).name, tol: "0.01" };
    const pick = h("select", { id: "sweep-pick", onchange: (e) => { st.name = e.target.value; draw(); } },
      DATA.sweeps.map((sw) => h("option", { value: sw.name, selected: sw.name === st.name }, sweepLabel(sw) + (sw.name.endsWith("_random") ? " (randomized)" : ""))));
    const tols = Object.keys(DATA.sweeps[0].breaking_points);
    const fig = h("div"), avail = h("div"), table = h("div"), matrix = h("div"), desc = h("p", { class: "note" });
    root.append(
      h("div", { class: "stack" },
        h("h2", {}, "Where each aggregator breaks"),
        h("p", { class: "lede" }, "Each curve shows how often an aggregator misses the true price as more nodes turn faulty. The shaded band is a 95% interval over random seeds; the labelled point is the breaking point.")),
      h("div", { class: "section panel", style: { marginTop: "24px" } },
        h("div", { class: "controls" },
          h("label", { class: "field", for: "sweep-pick" }, "Attack scenario", pick),
          h("div", { class: "field" }, h("span", { class: "small" }, "Error tolerance"),
            seg(tols.map((t) => [t, pct(+t, 1)]), st.tol, (v) => { st.tol = v; draw(); }, "Error tolerance"))),
        desc, fig),
      h("div", { class: "section grid-2" },
        h("div", { class: "panel" }, h("h3", {}, "Breaking points in this scenario"), table),
        h("div", { class: "panel" }, h("h3", {}, "Rounds with an answer"),
          h("p", { class: "note" }, "Quorum median refuses to answer when too few nodes report, trading availability for accuracy."), avail)),
      h("div", { class: "section panel" },
        h("div", { class: "section-head" }, h("h3", {}, "All scenarios at this tolerance"),
          h("span", { class: "small" }, "Select a row to plot it")), matrix));

    function draw() {
      const sw = sweep(st.name);
      desc.textContent = `${sw.title}. ${sw.seeds} seeds per point, ${sw.nodes} nodes.`;
      responsive(() => breakingChart(fig, sw, st.tol, 340));
      table.innerHTML = "";
      table.append(h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Aggregator"), h("th", {}, "Breaks at"), h("th", { class: "num" }, "Resamples never breaking"))),
        h("tbody", {}, Object.keys(sw.breaking_points[st.tol]).map((agg) => {
          const b = bp(sw, st.tol, agg);
          return h("tr", {}, h("td", {}, h("span", { class: "swatch", style: { "--c": col(AGG[agg].c) } }), AGG[agg].label),
            h("td", { class: b.breaking_point == null ? "never" : "" }, bpText(b)),
            h("td", { class: "num" }, pct(b.share_of_resamples_never_breaking)));
        })))));
      responsive(() => {
        avail.innerHTML = "";
        const series = Object.entries(sw.availability).map(([agg, a]) => ({ name: AGG[agg].label, c: AGG[agg].c, x: a.fraction, y: a.availability, markers: true }));
        const plot = h("div");
        avail.append(legend(series.map((x) => ({ c: x.c, label: x.name }))), plot);
        lineChart(plot, series, { height: 220, ydomain: [-0.02, 1.04], yfmt: (v) => pct(v), xfmt: (v) => pct(v), xlabel: "Faulty nodes" });
      });
      matrix.innerHTML = "";
      const aggs = Object.keys(DATA.sweeps[0].breaking_points[st.tol]);
      matrix.append(h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Scenario"), aggs.map((a) => h("th", {}, AGG[a].label)))),
        h("tbody", {}, DATA.sweeps.map((x) => h("tr", {
          class: `pick ${x.name === st.name ? "current" : ""}`, tabindex: 0,
          onclick: () => { st.name = x.name; pick.value = x.name; draw(); window.scrollTo({ top: 0, behavior: "smooth" }); },
          onkeydown: (e) => { if (e.key === "Enter") e.currentTarget.click(); },
        }, h("td", {}, sweepLabel(x) + (x.name.endsWith("_random") ? " (randomized)" : "")),
          aggs.map((a) => { const b = bp(x, st.tol, a); return h("td", { class: b.breaking_point == null ? "never" : "" }, bpText(b)); })))))));
    }
    draw();
  }

  // --------------------------------------------------------- view: diagnosis
  function viewDiagnosis(root) {
    const cal = DATA.calibration;
    if (!cal) { root.append(h("div", { class: "empty" }, "No calibration results yet. Run python -m oraclelens.calibrate.")); return; }
    const st = { split: "holdout-family" };
    const fig = h("div"), stats = h("div"), recall = h("div");
    root.append(
      h("div", { class: "stack" },
        h("h2", {}, "Does the diagnosis know when it is right?"),
        h("p", { class: "lede" }, `Every incident gets a cause and a confidence. We generated ${cal.scenarios} random scenarios, fitted a calibration map on some of them and tested on the rest, splitting by whole scenario so similar incidents could not leak across.`)),
      h("div", { class: "section panel" },
        h("div", { class: "controls" },
          h("div", { class: "field" }, h("span", { class: "small" }, "Test set"),
            seg([["holdout-family", "Unseen attack types"], ["grouped", "Random scenarios"]], st.split, (v) => { st.split = v; draw(); }, "Test set"))),
        h("div", { class: "grid-2" }, h("div", {}, fig), h("div", { class: "stack" }, stats, recall))),
      h("div", { class: "section panel" },
        h("h3", {}, "What the engine said vs what happened"),
        h("p", { class: "note", style: { margin: "6px 0 12px" } }, "Random-scenario test set. Shading is the share of each true cause; counts are incidents."),
        confusion(cal.confusion)));
    function draw() {
      const r = cal.splits[st.split];
      responsive(() => {
        fig.innerHTML = "";
        const pts = (tag) => r[tag].reliability.filter((b) => b.count >= 5);
        const series = [
          { name: "Raw confidence", c: "--s2", x: pts("raw").map((b) => b.mean_confidence), y: pts("raw").map((b) => b.accuracy), markers: true },
          { name: "Calibrated", c: "--s1", x: pts("calibrated").map((b) => b.mean_confidence), y: pts("calibrated").map((b) => b.accuracy), markers: true },
        ];
        const plot = h("div");
        fig.append(legend([...series.map((x) => ({ c: x.c, label: x.name })), { c: "--ink-2", label: "Perfect calibration", kind: "dash" }]), plot);
        lineChart(plot, series, { height: 320, xdomain: [0, 1], ydomain: [0, 1.02], diagonal: true, xfmt: (v) => pct(v), yfmt: (v) => pct(v),
          xlabel: "Stated confidence", ylabel: "Observed accuracy", tipTitle: (v) => `Confidence ≈ ${pct(v)}` });
      });
      stats.innerHTML = "";
      stats.append(h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}), h("th", { class: "num" }, "Raw"), h("th", { class: "num" }, "Calibrated"))),
        h("tbody", {},
          h("tr", {}, h("td", {}, "Calibration error (ECE, lower is better)"), h("td", { class: "num" }, num(r.raw.ece)), h("td", { class: "num" }, num(r.calibrated.ece))),
          h("tr", {}, h("td", {}, "Brier score (lower is better)"), h("td", { class: "num" }, num(r.raw.brier)), h("td", { class: "num" }, num(r.calibrated.brier))),
          h("tr", {}, h("td", {}, "Incidents it commits to"), h("td", { class: "num" }, pct(r.raw.coverage, 1)), h("td", { class: "num" }, pct(r.calibrated.coverage, 1))),
          h("tr", {}, h("td", {}, "Accuracy when it commits"), h("td", { class: "num" }, pct(r.raw.accuracy_when_decided, 1)), h("td", { class: "num" }, pct(r.calibrated.accuracy_when_decided, 1)))))),
        h("p", { class: "small" }, `${r.test_incidents.toLocaleString()} test incidents from ${r.test_scenarios} scenarios.`));
      recall.innerHTML = "";
      if (r.per_class_recall) {
        recall.append(h("h3", {}, "Correct cause, by true cause"),
          h("div", { class: "bars", style: { marginTop: "10px" } }, Object.entries(r.per_class_recall).flatMap(([c, v]) => [
            h("span", {}, CAUSE[c] ? CAUSE[c].label : c), h("div", { class: "track" }, h("div", { class: "fill", style: { width: pct(v, 1) } })), h("span", {}, pct(v))])));
      }
    }
    draw();
  }
  function confusion(cm) {
    const rgb = css("--heat");
    return h("div", { class: "table-wrap" }, h("table", { class: "cm" },
      h("thead", {}, h("tr", {}, h("th", { class: "lab" }, "True cause ↓ / said →"), cm.cols.map((c) => h("th", {}, CAUSE[c] ? CAUSE[c].label : c)))),
      h("tbody", {}, cm.rows.map((r, i) => {
        const tot = cm.counts[i].reduce((a, b) => a + b, 0) || 1;
        return h("tr", {}, h("td", { class: "lab" }, CAUSE[r] ? CAUSE[r].label : r), cm.counts[i].map((n, j) => {
          const share = n / tot;
          return h("td", { title: `${n} incidents (${pct(share)})`,
            style: { background: n ? `rgba(${rgb}, ${0.08 + 0.72 * share})` : "transparent", color: share > 0.55 ? "#fff" : "", fontWeight: cm.cols[j] === r ? 600 : 400 } }, n || "");
        }));
      }))));
  }

  // ------------------------------------------------------------- view: mango
  function viewMango(root) {
    const M = DATA.mango;
    if (!M) { root.append(h("div", { class: "empty" }, "No case-study results yet. Run python -m oraclelens.casestudies.mango.")); return; }
    const C = M.curves, doc = M.documented, a = M.assumptions;
    const jump = (d) => M.controls.find((c) => c.control.startsWith("legit jump") && c.defense === d) || {};
    const priceBox = h("div"), borrowBox = h("div");
    root.append(
      h("div", { class: "stack" },
        h("h2", {}, "Case study: a Mango Markets–style pump"),
        h("p", { class: "lede" }, "In October 2022 an attacker pumped the MNGO token on thin markets and borrowed against the inflated collateral. Every price source reported the pumped price faithfully, so the oracle was not wrong. Which defenses outside price consensus would have helped, and what would they cost honest users?")),
      h("div", { class: "section grid-2" },
        h("div", { class: "panel stack" }, h("h3", {}, "Documented"),
          h("ul", {}, h("li", {}, `${doc.date}: about ${money(doc.reported_loss_usd)} borrowed against inflated collateral.`),
            h("li", {}, `MNGO traded at ${doc.pump_multiple_range[0]}–${doc.pump_multiple_range[1]}x its prior price for about 20 minutes, peaking near $${doc.peak_price}.`),
            h("li", {}, `Oracle behaviour: ${doc.oracle_behaviour}.`))),
        h("div", { class: "panel stack" }, h("h3", {}, "Modeled (assumptions)"),
          h("ul", {}, h("li", {}, `${a.round_length} rounds, ${money(a.attacker_deposit_usd)} attacker deposit, ${pct(a.loan_to_value)} loan-to-value.`),
            h("li", {}, `Pool liquidity ${money(a.pool_liquidity_usd)}, set so the undefended model matches the reported loss.`),
            h("li", {}, "21 honest oracle nodes reading the manipulated market. A simplified model, not a replay.")))),
      h("div", { class: "section panel" }, h("h3", {}, "The price each defense would have used"),
        h("p", { class: "note", style: { margin: "4px 0 10px" } }, "Log scale. The shaded area is the modeled pump."), priceBox),
      h("div", { class: "section panel" }, h("h3", {}, "How much the attacker could borrow"), borrowBox),
      h("div", { class: "section panel" }, h("h3", {}, "Results across 30 random pump paths"),
        h("div", { class: "table-wrap", style: { marginTop: "10px" } }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "Defense"), h("th", { class: "num" }, "Loss prevented"), h("th", { class: "num" }, "Range"),
            h("th", { class: "num" }, "Paused after a legit +25% jump"), h("th", { class: "num" }, "Honest borrowing at that moment"))),
          h("tbody", {}, M.loss_prevented_across_seeds.map((r) => h("tr", {},
            h("td", {}, h("span", { class: "swatch", style: { "--c": col(DEFENSE_C[r.defense]) } }), r.defense),
            h("td", { class: "num" }, pct(r.mean, 1)), h("td", { class: "num" }, `${pct(r.min)}–${pct(r.max)}`),
            h("td", { class: "num" }, jump(r.defense).minutes_paused ? `${jump(r.defense).minutes_paused} min` : "–"),
            h("td", { class: "num" }, pct(jump(r.defense).borrowing_capacity_vs_no_defense_at_move)))))))),
      h("p", { class: "note section" }, "Loss prevented is measured against borrowing above what the account could take at the fair price. All thresholds were set once, not tuned per defense."));
    responsive(() => {
      priceBox.innerHTML = "";
      const names = Object.keys(C.valuation);
      const series = names.map((n, i) => ({ name: n, c: ["--s1", "--s3", "--s4"][i], x: C.minutes, y: C.valuation[n] }));
      const plot = h("div");
      priceBox.append(legend(series.map((x) => ({ c: x.c, label: x.name }))), plot);
      lineChart(plot, series, { height: 300, ylog: true, yfmt: (v) => `$${v < 0.1 ? v.toFixed(2) : v.toFixed(1)}`, yfmtTip: (v) => `$${v.toFixed(4)}`,
        xfmt: (v) => `${v}`, xlabel: "Minutes from pump start", tipTitle: (v) => `Minute ${Math.round(v)}`, snap: Math.round,
        bands: [{ x0: C.pump_window[0], x1: C.pump_window[1], c: "--s8", opacity: 0.1 }] });
    });
    responsive(() => {
      borrowBox.innerHTML = "";
      const series = Object.entries(C.borrowed_usd).map(([n, v]) => ({ name: n, c: DEFENSE_C[n] || "--s8", x: C.minutes, y: v.map((x) => x / 1e6),
        dash: n === "node-consensus alarm" || n === "volatility circuit breaker" }));
      const plot = h("div");
      borrowBox.append(legend(series.map((x) => ({ c: x.c, label: x.name + (x.name === "node-consensus alarm" ? " (same as no defense)" : ""), kind: x.dash ? "dash" : "" }))), plot);
      lineChart(plot, series, { height: 320, xdomain: [-10, 110], ydomain: [0, 125], yfmt: (v) => `$${v}M`, yfmtTip: (v) => `$${v.toFixed(1)}M`,
        xlabel: "Minutes from pump start", tipTitle: (v) => `Minute ${Math.round(v)}`, snap: Math.round });
    });
  }

  // --------------------------------------------------------------- view: lab
  const LAB = { cfg: { nodes: 21, rounds: 500, sources: 5, seed: 7, faults: [
    { type: "collusion", count: 4, start: 150, end: 300, bias: 0.04 },
    { type: "slow_burn", count: 3, start: 200, growth: 0.0005, max_bias: 0.05 },
    { type: "stale", count: 1, start: 100, end: 180 },
    { type: "market_shock", start: 380, size: -0.15, duration: 3 }] }, result: null, round: null, mode: "truth", presets: null };

  function viewLab(root) {
    if (!BOOT.live) {
      root.append(h("div", { class: "static-lab stack" },
        h("h2", {}, "The live lab runs on your computer"),
        h("p", { class: "lede" }, "Design an attack, run it against 21 simulated oracle nodes, and replay what every node, detector and aggregator did round by round. It needs the Python engine, so it is not available on this static page."),
        h("p", {}, "To start it, clone the repository and run:"),
        h("pre", { class: "code" }, "pip install -e \".[dev]\"\npython -m oraclelens.lab"),
        h("p", {}, "Then open http://127.0.0.1:8000 and choose Live lab.")));
      return;
    }
    const side = h("aside", { class: "lab-side panel" });
    const main = h("div", { class: "lab-main" });
    root.append(h("div", { class: "stack", style: { marginBottom: "24px" } },
      h("h2", {}, "Live lab"),
      h("p", { class: "lede" }, "Design an attack, run it, then scrub through the rounds to see which nodes lied, which detectors noticed and how far each aggregator drifted.")),
      h("div", { class: "lab" }, side, main));
    drawSide(side, main);
    if (LAB.result) drawResult(main); else main.append(h("div", { class: "empty" }, "Choose a scenario on the left and select Run simulation."));
  }

  function drawSide(side, main) {
    side.innerHTML = "";
    const c = LAB.cfg;
    const numIn = (key, attrs) => h("input", { type: "number", value: c[key], ...attrs,
      oninput: (e) => { c[key] = e.target.value === "" ? "" : Number(e.target.value); } });
    const presetPick = h("select", { "aria-label": "Load a preset", onchange: (e) => {
      const p = (LAB.presets || []).find((x) => x.name === e.target.value);
      if (p) { c.faults = JSON.parse(JSON.stringify(p.config.faults || [])); drawSide(side, main); }
    } }, h("option", { value: "" }, "Load a saved scenario…"));
    if (LAB.presets) LAB.presets.forEach((p) => presetPick.append(h("option", { value: p.name }, p.name.replace(/_/g, " "))));
    else fetch("api/presets").then((r) => r.json()).then((p) => { LAB.presets = p; drawSide(side, main); }).catch(() => {});

    const faults = h("div", { class: "faults" });
    c.faults.forEach((f, i) => faults.append(faultRow(f, i, () => drawSide(side, main))));
    const status = h("p", { class: "small", "aria-live": "polite" });
    const yaml = h("pre", { class: "code", style: { display: "none" } });
    const runBtn = h("button", { class: "btn", type: "button", onclick: async () => {
      runBtn.disabled = true; status.className = "small"; status.textContent = "Running…";
      try {
        const body = { seed: Number(c.seed) || 0, config: { name: "lab", nodes: Number(c.nodes), rounds: Number(c.rounds), sources: Number(c.sources), faults: c.faults } };
        const r = await fetch("api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
        LAB.result = data; LAB.round = Math.min(data.rounds - 1, Math.max(data.warmup, (c.faults[0] && c.faults[0].start) || data.warmup));
        status.textContent = `Done. Seed ${data.seed}, config ${data.provenance.config_hash.slice(0, 8)}.`;
        drawResult(main);
      } catch (e) {
        status.className = "small error";
        status.textContent = `Simulation failed: ${e.message}`;
      } finally { runBtn.disabled = false; }
    } }, "Run simulation");
    side.append(
      h("h3", {}, "Network"),
      h("div", { class: "row-fields", style: { marginTop: "10px" } },
        h("label", { class: "field" }, "Nodes", numIn("nodes", { min: 3, max: 61 })),
        h("label", { class: "field" }, "Exchanges", numIn("sources", { min: 1, max: 20 })),
        h("label", { class: "field" }, "Rounds", numIn("rounds", { min: 50, max: 2000, step: 50 })),
        h("label", { class: "field" }, "Random seed", numIn("seed", { min: 0 }))),
      h("h3", { style: { marginTop: "22px" } }, "Faults and attacks"),
      h("div", { style: { marginTop: "8px" } }, presetPick),
      faults,
      h("button", { class: "btn quiet", type: "button", onclick: () => { c.faults.push({ type: "outlier", ...FAULTS.outlier.fields }); drawSide(side, main); } }, "Add a fault"),
      h("div", { class: "side-actions" }, runBtn,
        h("button", { class: "icon-btn", type: "button", onclick: () => {
          yaml.textContent = toYaml(c); yaml.style.display = yaml.style.display === "none" ? "block" : "none";
        } }, "Show as YAML")),
      status, yaml);
  }

  function faultRow(f, i, redraw) {
    const spec = FAULTS[f.type] || { fields: {} };
    const typeSel = h("select", { "aria-label": `Fault ${i + 1} type`, onchange: (e) => {
      const t = e.target.value; const nf = { type: t, ...FAULTS[t].fields };
      LAB.cfg.faults[i] = nf; redraw();
    } }, Object.entries(FAULTS).map(([k, v]) => h("option", { value: k, selected: k === f.type }, v.label)));
    const fields = Object.keys(spec.fields).map((k) => h("label", { class: "field" }, FIELD_LABEL[k] || k,
      h("input", { type: "number", step: "any", value: f[k] != null ? f[k] : spec.fields[k],
        oninput: (e) => { f[k] = e.target.value === "" ? undefined : Number(e.target.value); } })));
    return h("div", { class: "fault" },
      h("div", { class: "fault-head" }, typeSel,
        h("button", { class: "icon-btn", type: "button", "aria-label": `Remove fault ${i + 1}`, onclick: () => { LAB.cfg.faults.splice(i, 1); redraw(); } }, "Remove")),
      h("div", { class: "row-fields" }, fields));
  }

  function toYaml(c) {
    const lines = ["name: lab_scenario", `nodes: ${c.nodes}`, `sources: ${c.sources}`, `rounds: ${c.rounds}`, "faults:"];
    for (const f of c.faults) lines.push(`  - {${Object.entries(f).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}: ${v}`).join(", ")}}`);
    lines.push(`# run: python -m oraclelens.run --config this.yaml --seed ${c.seed}`);
    return lines.join("\n");
  }

  function drawResult(main) {
    const R = LAB.result;
    main.innerHTML = "";
    const priceBox = h("div"), heatBox = h("div", { class: "heat-wrap" }), inspect = h("div"), lanes = h("div");
    const slider = h("input", { type: "range", min: 0, max: R.rounds - 1, value: LAB.round, "aria-label": "Round" });
    const roundLbl = h("span", { class: "round" });
    let timer = null;
    const playBtn = h("button", { class: "icon-btn", type: "button", onclick: () => {
      if (timer) { clearInterval(timer); timer = null; playBtn.textContent = "Play"; return; }
      playBtn.textContent = "Pause";
      timer = setInterval(() => {
        if (!document.body.contains(slider)) { clearInterval(timer); timer = null; return; }
        setRound(LAB.round + 1 >= R.rounds ? R.warmup : LAB.round + 1);
      }, 80);
    } }, "Play");
    const modeOpts = [["truth", "Ground truth"], ["dev", "Deviation"], ...R.detectors.map((d) => [d, DET[d] || d])];
    const modeSel = h("select", { "aria-label": "Heatmap view", onchange: (e) => { LAB.mode = e.target.value; drawHeat(); drawInspect(); } },
      modeOpts.map(([v, t]) => h("option", { value: v, selected: v === LAB.mode }, t)));
    const heatLegend = h("div");

    main.append(
      h("div", { class: "panel" },
        h("div", { class: "section-head" }, h("h3", {}, "Price: truth vs what each aggregator reported"),
          h("span", { class: "small" }, "Click the chart to jump to a round")),
        priceBox, lanes),
      h("div", { class: "panel" },
        h("div", { class: "scrub" }, playBtn, slider, roundLbl)),
      h("div", { class: "panel" },
        h("div", { class: "controls", style: { marginBottom: "8px" } },
          h("h3", { style: { marginRight: "auto" } }, "Every node, every round"),
          h("label", { class: "field" }, "Show", modeSel)),
        heatLegend, heatBox),
      h("div", { class: "panel" }, inspect),
      h("div", { class: "panel" }, aggTable(R)),
      h("div", { class: "panel" }, detTable(R)),
      h("div", { class: "panel" }, incidents(R)));

    let price;
    responsive(() => {
      if (!document.body.contains(priceBox)) return;
      priceBox.innerHTML = "";
      const x = R.truth.map((_, i) => i);
      const series = [{ name: "True price", c: "--ink", x, y: R.truth, width: 1.6 },
        ...Object.entries(R.aggregates).map(([k, v]) => ({ name: AGG[k] ? AGG[k].label : k, c: AGG[k] ? AGG[k].c : "--s8", x, y: v, width: 1.6 }))];
      const plot = h("div");
      priceBox.append(legend(series.map((sr) => ({ c: sr.c, label: sr.name }))), plot);
      price = lineChart(plot, series, { height: 280, xfmt: (v) => `${v}`, yfmt: (v) => v.toFixed(0), yfmtTip: (v) => v.toFixed(2),
        tipTitle: (v) => `Round ${Math.round(v)}`, snap: Math.round, xlabel: "Round",
        bands: [{ x0: 0, x1: R.warmup, c: "--ink-2", opacity: 0.05 }], onPick: (v) => setRound(Math.round(v)) });
      if (price) price.setCursor(LAB.round);
      drawLanes();
    });
    function drawLanes() {
      lanes.innerHTML = "";
      const ev = R.events;
      if (!ev.length || !price) return;
      const W = priceBox.querySelector("svg").viewBox.baseVal.width, rowH = 22;
      const svg = s("svg", { viewBox: `0 0 ${W} ${ev.length * rowH + 4}`, height: ev.length * rowH + 4, role: "img", "aria-label": "Injected faults" });
      ev.forEach((e, i) => {
        const c = col((CAUSE[e.cause] && CAUSE[e.cause].c) || "--ink-2");
        const x0 = price.X(e.start), x1 = price.X(Math.min(e.end, R.rounds - 1));
        svg.append(s("rect", { x: x0, y: i * rowH + 5, width: Math.max(3, x1 - x0), height: 12, rx: 3, fill: c, "fill-opacity": 0.85 }));
        const lbl = `${(FAULTS[e.type] || { label: e.type }).label}${e.nodes.length ? ` · ${e.nodes.length} node${e.nodes.length > 1 ? "s" : ""}` : ""}`;
        const right = x1 + 8 + lbl.length * 6.6 < W;
        svg.append(s("text", { x: right ? x1 + 8 : x0 - 8, y: i * rowH + 15, "text-anchor": right ? "start" : "end", style: "fill: var(--ink-2); font-size: 12px" }, lbl));
      });
      lanes.append(h("div", { class: "chart", style: { marginTop: "6px" } }, svg));
    }

    // heatmap
    const canvas = h("canvas", { role: "img", "aria-label": "Node by round heatmap. Use the slider to move between rounds." });
    heatBox.append(canvas);
    let dragging = false;
    const roundAt = (e) => { const r = canvas.getBoundingClientRect(); return Math.max(0, Math.min(R.rounds - 1, Math.floor(((e.clientX - r.left) / r.width) * R.rounds))); };
    canvas.addEventListener("pointerdown", (e) => { dragging = true; canvas.setPointerCapture(e.pointerId); setRound(roundAt(e)); });
    canvas.addEventListener("pointermove", (e) => { if (dragging) setRound(roundAt(e)); });
    canvas.addEventListener("pointerup", () => { dragging = false; });
    function cellColor(r, n) {
      const v = R.obs[r][n], lab = R.labels[r][n];
      if (LAB.mode === "truth") {
        const cause = DATA_CAUSES[lab];
        if (cause === "none") return null;
        return col(CAUSE[cause].c);
      }
      if (v == null) return col("--missing");
      if (LAB.mode === "dev") {
        const d = Math.min(1, Math.abs(v / R.truth[r] - 1) / 0.02);
        return d < 0.03 ? null : `rgba(${css("--heat")}, ${0.12 + 0.88 * d})`;
      }
      const bit = R.detectors.indexOf(LAB.mode), flagged = (R.flags[r][n] >> bit) & 1;
      const valueFault = [1, 4, 5, 6, 7].includes(lab);
      if (flagged && valueFault) return col("--s1");
      if (flagged) return col("--s2");
      if (valueFault) return `rgba(${css("--heat")}, 0.22)`;
      return null;
    }
    function drawHeat() {
      if (!document.body.contains(canvas)) return;
      const dpr = window.devicePixelRatio || 1, W = heatBox.clientWidth || 600;
      const cellH = Math.max(6, Math.min(14, Math.floor(260 / R.nodes))), H = cellH * R.nodes;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); canvas.style.height = `${H}px`;
      const ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      ctx.fillStyle = col("--bg"); ctx.fillRect(0, 0, W, H);
      const cw = W / R.rounds;
      for (let n = 0; n < R.nodes; n++) for (let r = 0; r < R.rounds; r++) {
        const c = cellColor(r, n);
        if (c) { ctx.fillStyle = c; ctx.fillRect(r * cw, n * cellH, Math.ceil(cw), cellH - 1); }
      }
      ctx.fillStyle = col("--ink"); ctx.fillRect(LAB.round * cw, 0, Math.max(1.5, cw), H);
      heatLegend.innerHTML = "";
      let items;
      if (LAB.mode === "truth") items = Object.entries(CAUSE).filter(([k, v]) => v.c && k !== "insufficient_evidence").map(([, v]) => ({ c: v.c, label: v.label, kind: "box" }));
      else if (LAB.mode === "dev") items = [{ c: `rgba(${css("--heat")}, 0.3)`, label: "Small deviation", kind: "box" }, { c: `rgba(${css("--heat")}, 1)`, label: "2% or more from truth", kind: "box" }, { c: "--missing", label: "No report", kind: "box" }];
      else items = [{ c: "--s1", label: "Caught a bad report", kind: "box" }, { c: "--s2", label: "False alarm", kind: "box" }, { c: `rgba(${css("--heat")}, 0.22)`, label: "Missed a bad report", kind: "box" }];
      heatLegend.append(legend(items), h("p", { class: "small", style: { marginBottom: "8px" } }, `Rows are the ${R.nodes} nodes, columns are rounds. Drag across to move through time.`));
    }
    responsive(drawHeat);

    function drawInspect() {
      inspect.innerHTML = "";
      const r = LAB.round, truth = R.truth[r];
      const det = R.detectors.includes(LAB.mode) ? LAB.mode : "mad", bit = R.detectors.indexOf(det);
      const devs = R.obs[r].map((v) => (v == null ? null : v / truth - 1));
      const aggDev = Object.entries(R.aggregates).map(([k, v]) => [k, v[r] == null ? null : v[r] / truth - 1]);
      const span = Math.max(0.01, ...devs.filter(finite).map(Math.abs), ...aggDev.map(([, d]) => (finite(d) ? Math.abs(d) : 0))) * 1.12;
      const W = Math.max(300, inspect.clientWidth || 600), rowH = 13, top = 26, H = top + R.nodes * rowH + 34, ml = 70, mr = 16;
      const X = (d) => ml + ((d + span) / (2 * span)) * (W - ml - mr);
      const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": `Node reports in round ${r}` });
      for (const t of niceTicks(-span, span, 6)) {
        svg.append(s("line", { class: t === 0 ? "baseline" : "grid", x1: X(t), x2: X(t), y1: top - 6, y2: H - 30 }));
        const tv = Math.abs(t) < 1e-12 ? 0 : t;
        svg.append(s("text", { x: X(t), y: H - 12, "text-anchor": "middle" }, `${tv > 0 ? "+" : ""}${(tv * 100).toFixed(1)}%`));
      }
      aggDev.forEach(([k, d], i) => { if (!finite(d)) return;
        svg.append(s("line", { x1: X(d), x2: X(d), y1: top - 10 + i, y2: H - 30, stroke: col(AGG[k].c), "stroke-width": 2, "stroke-dasharray": "3 3" })); });
      devs.forEach((d, n) => {
        const y = top + n * rowH + rowH / 2, lab = DATA_CAUSES[R.labels[r][n]];
        const c = lab === "none" ? col("--ink-2") : col(CAUSE[lab].c);
        svg.append(s("text", { x: ml - 10, y: y + 4, "text-anchor": "end", style: "font-size: 11px" }, `node ${n}`));
        if (d == null) { svg.append(s("text", { x: X(0) + 8, y: y + 4, style: "font-size: 11px; fill: var(--muted)" }, "no report")); return; }
        const flagged = (R.flags[r][n] >> bit) & 1, late = R.late[r][n];
        svg.append(s("circle", { cx: X(d), cy: y, r: 4.5, fill: late ? "none" : c, stroke: c, "stroke-width": 1.5 }));
        if (flagged) svg.append(s("circle", { cx: X(d), cy: y, r: 8, fill: "none", stroke: col("--ink"), "stroke-width": 1.5 }));
        svg.append(s("title", {}, `node ${n}: ${(d * 100).toFixed(3)}% · ${CAUSE[lab].label}${late ? " · late" : ""}${flagged ? ` · flagged by ${DET[det]}` : ""}`));
      });
      const box = h("div", { class: "chart" }, svg);
      inspect.append(
        h("div", { class: "section-head", style: { marginBottom: "6px" } },
          h("h3", {}, `Round ${r}: each node's report vs the true price`),
          h("span", { class: "small" }, `Ring = flagged by ${DET[det]}${LAB.mode === det ? "" : " (choose a detector above to change)"}`)),
        legend([...aggDev.map(([k]) => ({ c: AGG[k].c, label: AGG[k].label, kind: "dash" })), { c: "--ink-2", label: "Honest node", kind: "dot" }]),
        box);
    }

    function setRound(r) {
      LAB.round = Math.max(0, Math.min(R.rounds - 1, r));
      slider.value = LAB.round;
      roundLbl.textContent = `Round ${LAB.round}`;
      if (price) price.setCursor(LAB.round);
      drawHeat(); drawInspect();
    }
    slider.addEventListener("input", (e) => setRound(Number(e.target.value)));
    responsive(() => { if (document.body.contains(inspect)) drawInspect(); });
    setRound(LAB.round);
    LAB.setRound = setRound;
  }

  let DATA_CAUSES = ["none", "stale", "delayed", "offline", "isolated_outlier", "correlated_source", "gradual_drift", "coordinated_manipulation"];

  function aggTable(R) {
    const tol = R.tolerance;
    return h("div", {}, h("h3", {}, "Aggregators"), h("div", { class: "table-wrap", style: { marginTop: "8px" } }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Method"), h("th", { class: "num" }, "Mean error"), h("th", { class: "num" }, `Rounds > ${pct(tol)} off`), h("th", { class: "num" }, "Answered"))),
      h("tbody", {}, Object.entries(R.metrics.aggregation).map(([k, m]) => h("tr", {},
        h("td", {}, h("span", { class: "swatch", style: { "--c": col(AGG[k].c) } }), AGG[k].label),
        h("td", { class: "num" }, pct(m.mean_error, 3)), h("td", { class: "num" }, pct(m[`failure_rate@${tol}`], 1)), h("td", { class: "num" }, pct(m.availability))))))));
  }
  function detTable(R) {
    return h("div", {}, h("h3", {}, "Detectors"), h("div", { class: "table-wrap", style: { marginTop: "8px" } }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Detector"), h("th", { class: "num" }, "Precision"), h("th", { class: "num" }, "Recall"), h("th", { class: "num" }, "False alarms"), h("th", { class: "num" }, "Rounds to detect"))),
      h("tbody", {}, Object.entries(R.metrics.detection).map(([k, m]) => h("tr", {},
        h("td", {}, DET[k] || k), h("td", { class: "num" }, num(m.precision, 2)), h("td", { class: "num" }, num(m.recall, 2)),
        h("td", { class: "num" }, pct(m.false_positive_rate, 1)), h("td", { class: "num" }, m.median_latency_rounds == null ? "–" : m.median_latency_rounds)))))),
      h("p", { class: "small", style: { marginTop: "8px" } }, "Value faults only; missing and late reports are handled by diagnosis."));
  }
  function incidents(R) {
    const list = R.incidents.filter((i) => i.true_cause !== "none" || i.predicted !== "none")
      .sort((a, b) => (b.end - b.start) - (a.end - a.start)).slice(0, 40);
    const a = R.metrics.attribution;
    const wrap = h("div", {},
      h("div", { class: "section-head" }, h("h3", {}, "What the diagnosis engine concluded"),
        a.incidents ? h("span", { class: "small" }, `${a.incidents} incidents · ${pct(a.top1_accuracy)} correct cause · ECE ${num(a.ece, 2)}`) : null));
    if (!list.length) { wrap.append(h("p", { class: "note" }, "No incidents beyond normal noise.")); return wrap; }
    const box = h("div", { class: "inc-list" });
    for (const i of list) {
      const right = i.top_cause === i.true_cause, abstain = i.predicted === "insufficient_evidence";
      box.append(h("div", { class: "inc", tabindex: 0, role: "button",
        onclick: () => { LAB.setRound(i.start); window.scrollTo({ top: 0, behavior: "smooth" }); },
        onkeydown: (e) => { if (e.key === "Enter") e.currentTarget.click(); } },
        h("div", { class: "when" }, `Node ${i.node}`, h("span", {}, `rounds ${i.start}–${i.end}`)),
        h("div", { class: "what" },
          h("span", { class: "verdict" }, `Truth: ${CAUSE[i.true_cause].label}`),
          h("span", { class: `tag ${abstain ? "abs" : right ? "ok" : "bad"}` }, abstain ? "Abstained" : right ? "Correct" : "Wrong"),
          h("div", {}, i.explanation))));
    }
    wrap.append(box, h("p", { class: "small", style: { marginTop: "8px" } }, "Longest 40 incidents. Select one to jump to its first round."));
    return wrap;
  }

  // ------------------------------------------------------------------ router
  const VIEWS = { findings: viewFindings, breaking: viewBreaking, diagnosis: viewDiagnosis, mango: viewMango, lab: viewLab };
  async function route() {
    const name = (location.hash || "#findings").slice(1);
    const key = VIEWS[name] ? name : "findings";
    document.querySelectorAll(".tabs a").forEach((a) => { if (a.dataset.tab === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    const view = document.getElementById("view");
    redraws.clear();
    view.innerHTML = "";
    try {
      await loadData();
      if (DATA.causes) DATA_CAUSES = DATA.causes;
      VIEWS[key](view);
    } catch (e) {
      view.append(h("div", { class: "empty" }, h("p", { class: "error" }, e.message),
        h("p", {}, "Generate results with ./reproduce.sh, then restart the lab.")));
    }
    view.focus({ preventScroll: true });
  }
  window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });
  route();
})();
