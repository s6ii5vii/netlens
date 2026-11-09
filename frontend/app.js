"use strict";

// Served by the agent, use same-origin URLs. Opened as a file, point at the default agent address.
const API = location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8000";

const $ = (id) => document.getElementById(id);

const READING_ORDER = ["latency_ms", "jitter_ms", "packet_loss", "dns_ms", "download_mbps", "upload_mbps"];
const WHERE_LABEL = { none: "—", local: "Wi-Fi / LAN", isp: "provider", unknown: "unclear" };
const VERDICT_LABEL = { yes: "Yes", shaky: "Shaky", no: "No", unknown: "Untested" };

const state = { scanning: false, source: null, latest: null, history: [] };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  for (const child of children.flat()) {
    if (child) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function fmt(value, unit) {
  if (value === null || value === undefined) return "—";
  if (unit === "%") return `${+value.toFixed(1)}%`;
  if (unit === "Mb/s") return `${value < 10 ? value.toFixed(1) : Math.round(value)} Mb/s`;
  return `${Math.round(value)} ${unit}`;
}

function number(value, unit) {
  if (value === null || value === undefined) return null;
  if (unit === "%") return String(+value.toFixed(1));
  if (unit === "Mb/s") return value < 10 ? value.toFixed(1) : String(Math.round(value));
  return String(Math.round(value));
}

function when(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso || "—";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { cache: "no-store", ...options });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } },
};

// ---------------------------------------------------------------------------
// Agent status
// ---------------------------------------------------------------------------

async function checkAgent() {
  const agent = $("agent");
  try {
    const health = await api("/health");
    agent.dataset.state = "online";
    $("agent-text").textContent = `agent online · v${health.version}`;
    return true;
  } catch (error) {
    agent.dataset.state = "offline";
    // A 403 from a file:// page means the agent IS running but refuses cross-site requests.
    $("agent-text").textContent = error.status === 403 ? "open the dashboard from the agent" : "agent not running";
    return error.status === 403 ? "wrong-origin" : false;
  }
}

function showOffline(reason) {
  const dialog = $("offline");
  if (reason === "wrong-origin") {
    $("offline-title").textContent = "Open NetLens from the agent.";
    $("offline-body").replaceChildren(
      el("p", { text: "The agent is running, but it only talks to the dashboard it serves itself." }),
      el("p", {}, "Open ", el("a", { href: "http://127.0.0.1:8000", text: "http://127.0.0.1:8000" }), "."),
    );
  }
  if (!dialog.open) dialog.showModal();
}

// ---------------------------------------------------------------------------
// Scanning
// ---------------------------------------------------------------------------

const STAGE_TEXT = {
  path: "pinging your router and the internet",
  dns: "timing DNS lookups",
  download: "measuring download speed",
  upload: "measuring upload speed",
};

function logLine(text, className = "") {
  const item = el("li", { class: className, text });
  $("scan-log").append(item);
  return item;
}

function setPending(stage) {
  const pending = $("scan-log").querySelector(".pending");
  if (pending) pending.remove();
  if (stage) logLine(`${STAGE_TEXT[stage]}…`, "pending");
}

function lineClass(rating) {
  return { poor: "fail", fair: "warn", good: "ok" }[rating] || "";
}

function describeStage(stage, metrics) {
  const errors = metrics.errors || {};
  if (stage === "path") {
    const lines = [];
    if (metrics.gateway_ip && errors.gateway) {
      lines.push([`router ${metrics.gateway_ip} · ${errors.gateway}`, "fail"]);
    } else if (metrics.gateway_ip) {
      lines.push([
        `router ${metrics.gateway_ip} · ${fmt(metrics.gateway_ms, "ms")} · ${fmt(metrics.gateway_loss, "%")} lost`,
        lineClass(linkRating(metrics.gateway_ms, metrics.gateway_loss, metrics.gateway_jitter_ms, LOCAL_LIMITS)),
      ]);
    } else {
      lines.push(["router address not found · skipped", "warn"]);
    }
    if (errors.ping) lines.push([`internet · ${errors.ping}`, "fail"]);
    else {
      lines.push([
        `internet ${metrics.ping_host} · ${fmt(metrics.latency_ms, "ms")} · jitter ${fmt(metrics.jitter_ms, "ms")} · ${fmt(metrics.packet_loss, "%")} lost`,
        lineClass(linkRating(metrics.latency_ms, metrics.packet_loss, metrics.jitter_ms, ISP_LIMITS)),
      ]);
    }
    return lines;
  }
  const readings = partialReadings(metrics);
  if (stage === "dns") {
    return [[errors.dns ? `dns · ${errors.dns}` : `dns lookup · ${fmt(metrics.dns_ms, "ms")}`, errors.dns ? "fail" : lineClass(readings.dns_ms.rating)]];
  }
  const key = `${stage}_mbps`;
  const error = errors[stage];
  if (error === "skipped") return [[`${stage} · skipped (data saver)`, ""]];
  if (error) return [[`${stage} · ${error}`, "fail"]];
  return [[`${stage} · ${fmt(metrics[key], "Mb/s")}`, lineClass(readings[key].rating)]];
}

const LOCAL_LIMITS = { ms: [10, 30], loss: [1, 3], jitter: [5, 15] };
const ISP_LIMITS = { ms: [60, 150], loss: [1, 3], jitter: [15, 30] };

const NEXT_STAGE = { path: "dns", dns: "download", download: "upload", upload: null };

function startScan() {
  if (state.scanning) return;
  state.scanning = true;
  const button = $("scan-btn");
  button.disabled = true;
  button.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), "Scanning…");
  $("scan-log").replaceChildren();
  $("ask-answer").hidden = true;
  $("report-no").textContent = "New report";
  $("report-time").textContent = "scanning now";

  setLink("link-local", "testing", "testing…");
  setLink("link-isp", "testing", "testing…");
  $("path-note").textContent = "Sending 8 pings to your router and 8 to the internet, side by side.";
  setPending("path");

  const saver = $("data-saver").checked;
  const source = new EventSource(`${API}/api/v1/scan/stream?throughput=${saver ? "false" : "true"}`);
  state.source = source;

  source.addEventListener("stage", (event) => {
    const { stage, metrics } = JSON.parse(event.data);
    setPending(null);
    for (const [text, className] of describeStage(stage, metrics)) logLine(text, className);
    renderReadings({ metrics }, true);
    if (stage === "path") renderPath({ metrics, location: null });
    const next = NEXT_STAGE[stage];
    if (next && !(saver && (next === "download" || next === "upload"))) setPending(next);
  });

  source.addEventListener("result", (event) => {
    finishScan();
    const result = JSON.parse(event.data);
    logLine(result.saved ? `done · score ${result.score} · saved to log` : "done · not saved, the internet test could not run", result.saved ? "done" : "fail");
    render(result);
    loadHistory();
  });

  source.addEventListener("error", (event) => {
    let message = "Lost contact with the agent during the scan.";
    if (event.data) {
      try { message = JSON.parse(event.data).detail; } catch { /* keep default */ }
    }
    finishScan();
    setPending(null);
    logLine(message, "fail");
    resetLinks();
    checkAgent().then((ok) => { if (ok !== true) showOffline(ok); });
  });
}

function finishScan() {
  state.scanning = false;
  if (state.source) state.source.close();
  state.source = null;
  const button = $("scan-btn");
  button.disabled = false;
  button.textContent = "Scan again";
  if (!state.latest) $("report-time").textContent = "no scan yet";
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function render(result) {
  state.latest = result;
  $("report-no").textContent = result.id ? `Report Nº ${String(result.id).padStart(4, "0")}` : "Report (unsaved)";
  $("report-time").textContent = new Date(result.timestamp).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  setHeadline(result.headline);
  $("subline").textContent = subline(result);

  const scoreBox = $("score-box");
  scoreBox.dataset.status = result.status;
  const scoreEl = $("score");
  scoreEl.classList.remove("bump");
  void scoreEl.offsetWidth; // restart the animation
  scoreEl.textContent = result.score ?? "–";
  scoreEl.classList.add("bump");
  $("status").textContent = result.status;

  renderPath(result);
  renderReadings(result);
  renderTasks(result.tasks);
  renderFixes(result.fixes);
}

// Italicise the closing words, so the verdict reads like a headline.
function setHeadline(text) {
  const words = text.split(" ");
  const tail = words.length > 3 ? 2 : 1;
  $("headline").replaceChildren(`${words.slice(0, -tail).join(" ")} `, el("em", { text: words.slice(-tail).join(" ") }));
}

function subline(result) {
  const ok = result.tasks.filter((task) => task.verdict === "yes").length;
  const untested = result.tasks.filter((task) => task.verdict === "unknown").length;
  if (result.status === "unmeasured") return `${result.location.detail} Nothing was saved to the log.`;
  let text = result.status === "offline" ? "Nothing that needs the internet will work." : (ok === 0 ? `None of the ${result.tasks.length} everyday tasks look safe right now.`
      : ok === result.tasks.length ? "Calls, streaming, gaming and big transfers should all be fine."
      : `${ok} of ${result.tasks.length} everyday tasks look fine right now.`);
  if (untested) text += ` ${untested} untested because speed tests were skipped.`;
  if (result.fixes.length) text += ` Best first step: ${result.fixes[0].title.toLowerCase()}.`;
  return text;
}

function setLink(id, linkState, label, trouble = false) {
  const link = $(id);
  link.dataset.state = linkState;
  if (trouble) link.dataset.trouble = "";
  else delete link.dataset.trouble;
  $(`${id}-label`).textContent = label;
}

function resetLinks() {
  setLink("link-local", "idle", "Wi-Fi / LAN");
  setLink("link-isp", "idle", "Provider");
}

function linkRating(ms, loss, jitter, limits) {
  if (loss === null || loss === undefined) return "unknown";
  if (loss >= 100) return "poor";
  if (loss >= limits.loss[1] || ms > limits.ms[1] || (jitter ?? 0) > limits.jitter[1]) return "poor";
  if (loss >= limits.loss[0] || ms > limits.ms[0] || (jitter ?? 0) > limits.jitter[0]) return "fair";
  return "good";
}

function renderPath(result) {
  const m = result.metrics;
  const where = result.location ? result.location.where : null;
  $("router-ip").textContent = m.gateway_ip || "not found";
  $("internet-host").textContent = m.ping_host || "—";

  if (m.gateway_ip && m.gateway_loss !== null && m.gateway_loss !== undefined) {
    const rating = linkRating(m.gateway_ms, m.gateway_loss, m.gateway_jitter_ms, LOCAL_LIMITS);
    const label = m.gateway_loss === 100 ? "no reply" : `${fmt(m.gateway_ms, "ms")} · ${fmt(m.gateway_loss, "%")} lost`;
    setLink("link-local", rating, label, where === "local");
  } else {
    setLink("link-local", "unknown", "not tested", false);
  }

  if (m.errors && m.errors.ping) {
    setLink("link-isp", "unknown", "not tested", false);
  } else if (m.packet_loss !== null && m.packet_loss !== undefined) {
    // The internet hop includes the router hop; subtract it so the label shows what's beyond the router.
    const beyond = m.latency_ms !== null && m.gateway_ms !== null && m.gateway_ms !== undefined
      ? Math.max(m.latency_ms - m.gateway_ms, 0) : m.latency_ms;
    const rating = linkRating(m.latency_ms, m.packet_loss, m.jitter_ms, ISP_LIMITS);
    const label = m.packet_loss === 100 ? "no reply" : `+${fmt(beyond, "ms")} · ${fmt(m.packet_loss, "%")} lost`;
    setLink("link-isp", rating, label, where === "isp");
  }

  if (result.location) $("path-note").textContent = result.location.detail;
}

function renderReadings(result, partial = false) {
  const metrics = result.metrics;
  const readings = result.readings || partialReadings(metrics);
  const container = $("readings");
  container.replaceChildren(
    ...READING_ORDER.map((key) => {
      const reading = readings[key];
      const error = metrics.errors ? metrics.errors[key.split("_")[0]] : null;
      const value = number(reading.value, reading.unit);
      const ratingText = reading.value === null ? (partial && !error ? "waiting" : "n/a") : reading.rating;
      return el(
        "div",
        { class: "reading" },
        el("div", { class: "reading-top" },
          el("span", { class: "eyebrow", text: reading.label }),
          el("span", { class: `pill ${reading.rating}`, text: ratingText })),
        value === null
          ? el("div", { class: "reading-value na", text: error === "skipped" ? "skipped" : error ? "failed" : "—" })
          : el("div", { class: "reading-value" }, value, el("small", { text: reading.unit })),
        scale(reading),
        key === "latency_ms" && metrics.rtts && metrics.rtts.length ? trace(metrics.rtts, metrics.packet_loss) : null,
        error && error !== "skipped" ? el("p", { class: "reading-note", text: error }) : null,
      );
    }),
  );
}

// Before the final analysis arrives, show raw values without ratings.
const PARTIAL_META = {
  latency_ms: ["latency", "ms", 60, 150, true],
  jitter_ms: ["jitter", "ms", 15, 40, true],
  packet_loss: ["packet loss", "%", 1, 5, true],
  dns_ms: ["DNS lookup", "ms", 60, 150, true],
  download_mbps: ["download", "Mb/s", 25, 5, false],
  upload_mbps: ["upload", "Mb/s", 10, 2, false],
};

function partialReadings(metrics) {
  const out = {};
  for (const [key, [label, unit, good, poor, lower]] of Object.entries(PARTIAL_META)) {
    const value = metrics[key] ?? null;
    let rating = "unknown";
    if (value !== null) {
      rating = lower ? (value <= good ? "good" : value <= poor ? "fair" : "poor")
        : (value >= good ? "good" : value >= poor ? "fair" : "poor");
    }
    out[key] = { label, unit, value, rating, good, poor, lower_is_better: lower };
  }
  return out;
}

function scale(reading) {
  const { good, poor, lower_is_better: lower, value } = reading;
  const max = (lower ? poor : good) * 1.6;
  const pct = (v) => Math.min(Math.max((v / max) * 100, 0), 100);
  const zones = lower
    ? [["z-good", pct(good)], ["z-fair", pct(poor) - pct(good)], ["z-poor", 100 - pct(poor)]]
    : [["z-poor", pct(poor)], ["z-fair", pct(good) - pct(poor)], ["z-good", 100 - pct(good)]];
  return el(
    "div",
    {},
    el("div", { class: "scale-bar", role: "img", "aria-label": `${reading.label}: ${fmt(value, reading.unit)} on a scale where ${lower ? "under" : "over"} ${fmt(good, reading.unit)} is good` },
      zones.map(([cls, width]) => el("i", { class: cls, style: `width:${width}%` })),
      value === null ? null : el("span", { class: "scale-mark", style: `left:${pct(value)}%` })),
    el("div", { class: "scale-legend" },
      el("span", { text: "0" }),
      el("span", { text: `${lower ? "under" : "over"} ${fmt(good, reading.unit)} is good` }),
      el("span", { text: `${fmt(max, reading.unit)}+` })),
  );
}

function trace(rtts, loss) {
  if (!rtts.length) return null;
  const width = 100;
  const height = 30;
  const max = Math.max(...rtts) * 1.15 || 1;
  const step = rtts.length > 1 ? width / (rtts.length - 1) : 0;
  const points = rtts.map((rtt, i) => `${(i * step).toFixed(1)},${(height - (rtt / max) * height).toFixed(1)}`).join(" ");
  return svg(
    "svg",
    { class: "spark", viewBox: `0 -2 ${width} ${height + 4}`, preserveAspectRatio: "none", role: "img", "aria-label": `${rtts.length} ping round trips` },
    svg("title", {}, `Each ping: ${rtts.map((r) => `${Math.round(r)} ms`).join(", ")}${loss ? ` (${fmt(loss, "%")} lost)` : ""}`),
    svg("polyline", { points }),
  );
}

function renderTasks(tasks) {
  $("tasks").replaceChildren(
    ...tasks.map((task) =>
      el("li", { class: "task" },
        el("span", { class: "task-name", text: task.label }),
        el("span", { class: `pill ${task.verdict}`, text: VERDICT_LABEL[task.verdict] }),
        el("span", { class: "task-reason" },
          task.reason,
          task.untested.length && task.verdict !== "unknown" ? el("em", { text: ` (${task.untested.join(", ")} not tested)` }) : null),
      ),
    ),
  );
}

function renderFixes(fixes) {
  const list = $("fixes");
  if (!fixes.length) {
    list.replaceChildren(el("li", { class: "empty", text: "Nothing to fix. The connection is in good shape." }));
    return;
  }
  list.replaceChildren(
    ...fixes.map((fix, index) =>
      el("li", { class: "fix", style: `animation-delay:${index * 60}ms` },
        el("div", { class: "fix-top" },
          el("b", { text: index === 0 ? "Start here" : `Step ${String(index + 1).padStart(2, "0")}` }),
          el("span", { text: fix.time })),
        el("h3", { text: fix.title }),
        el("p", { class: "fix-why", text: fix.why }),
        el("details", { open: index === 0 },
          el("summary", { text: "How to do it" }),
          el("ol", {}, fix.steps.map((step) => el("li", { text: step }))),
          fix.note ? el("p", { class: "fix-note", text: fix.note }) : null)),
    ),
  );
}

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------

async function ask(event) {
  event.preventDefault();
  const question = $("ask-input").value.trim().replace(/^can i\s+/i, "").replace(/\s*(right now)?\s*\?*$/i, "");
  if (!question) return;
  const box = $("ask-answer");
  box.hidden = false;
  try {
    const answer = await api("/api/v1/check-task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: question }),
    });
    box.className = `answer ${answer.verdict}`;
    box.replaceChildren(
      el("div", { class: "answer-top" },
        el("span", { class: `pill ${answer.verdict}`, text: answer.matched ? VERDICT_LABEL[answer.verdict] : "Not sure" }),
        el("span", { class: "eyebrow", text: answer.matched ? `judged as ${answer.label}` : "no matching task" })),
      el("h3", { text: `Can I ${question}?` }),
      el("p", { text: answer.reason }),
    );
  } catch (error) {
    box.className = "answer";
    box.replaceChildren(
      el("h3", { text: `Can I ${question}?` }),
      el("p", { text: error.status === 409 ? "Run a scan first, then ask again." : error.message }),
    );
  }
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

async function loadHistory() {
  try {
    const rows = await api("/api/v1/history?limit=60");
    state.history = rows;
    renderChart(rows);
    renderLog(rows);
  } catch {
    $("chart").replaceChildren(el("div", { class: "chart-empty", text: "Log unavailable." }));
  }
}

function renderChart(rows) {
  const chart = $("chart");
  if (rows.length < 2) {
    chart.replaceChildren(el("div", { class: "chart-empty", text: rows.length ? "One scan so far. The trend appears after the next." : "No scans logged yet." }));
    return;
  }
  const width = Math.max(chart.clientWidth, 280);
  const height = chart.clientHeight || 180;
  const left = 28;
  const top = 10;
  const bottom = 10;
  const x = (i) => left + (i / (rows.length - 1)) * (width - left - 8);
  const y = (score) => top + (1 - score / 100) * (height - top - bottom);
  const grid = [0, 55, 80, 100].map((value) =>
    svg("g", {},
      svg("line", { x1: left, x2: width, y1: y(value), y2: y(value) }),
      svg("text", { x: 0, y: y(value) + 3 }, String(value))));
  const points = rows.map((row, i) => `${x(i).toFixed(1)},${y(row.score).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${y(0)} ${points} ${x(rows.length - 1).toFixed(1)},${y(0)}`;
  chart.replaceChildren(
    svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `Score over the last ${rows.length} scans` },
      svg("g", { class: "grid" }, grid),
      svg("polygon", { class: "area", points: area }),
      svg("polyline", { class: "line", points }),
      rows.map((row, i) =>
        svg("circle", { class: `dot-${row.status}`, cx: x(i), cy: y(row.score), r: 4.5 },
          svg("title", {}, `${when(row.timestamp)}: ${row.score} (${row.status})`)))),
  );
}

function renderLog(rows) {
  const body = $("log").tBodies[0];
  const recent = rows.slice(-15).reverse();
  if (!recent.length) {
    body.replaceChildren(el("tr", {}, el("td", { colspan: "7", text: "No scans yet." })));
    return;
  }
  body.replaceChildren(
    ...recent.map((row) =>
      el("tr", {},
        el("td", { text: when(row.timestamp) }),
        el("td", { class: `score r-${row.status === "offline" ? "poor" : row.status}`, text: row.score }),
        el("td", { text: fmt(row.latency_ms, "ms") }),
        el("td", { text: fmt(row.packet_loss, "%") }),
        el("td", { text: fmt(row.download_mbps, "Mb/s") }),
        el("td", { text: fmt(row.upload_mbps, "Mb/s") }),
        el("td", { text: WHERE_LABEL[row.where_problem] || "—" }))),
  );
}

async function clearLog() {
  if (!confirm("Delete every scan in the log? This can't be undone.")) return;
  try {
    await api("/api/v1/history", { method: "DELETE" });
  } finally {
    loadHistory();
  }
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

async function init() {
  $("export-btn").href = `${API}/api/v1/history.csv`;
  const saver = $("data-saver");
  saver.checked = storage.get("netlens.dataSaver") === "1";
  saver.addEventListener("change", () => storage.set("netlens.dataSaver", saver.checked ? "1" : "0"));

  $("scan-btn").addEventListener("click", startScan);
  $("theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    storage.set("netlens.theme", next);
  });
  document.querySelectorAll("#suggestions button").forEach((button) =>
    button.addEventListener("click", () => {
      $("ask-input").value = button.textContent;
      $("ask-form").requestSubmit();
    }));
  $("ask-form").addEventListener("submit", ask);
  $("clear-btn").addEventListener("click", clearLog);
  $("offline-retry").addEventListener("click", () => setTimeout(() => location.reload(), 50));

  renderReadings({ metrics: { errors: {} } }, false);

  const agent = await checkAgent();
  if (agent !== true) {
    $("scan-btn").disabled = true;
    showOffline(agent);
    return;
  }

  try {
    const latest = await api("/api/v1/scan/latest");
    if (latest) render(latest);
  } catch { /* shown again after the next scan */ }
  loadHistory();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => renderChart(state.history), 150);
  });

  setInterval(async () => {
    if (!state.scanning) {
      const ok = await checkAgent();
      $("scan-btn").disabled = ok !== true;
    }
  }, 15000);
}

init();
