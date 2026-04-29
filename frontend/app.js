// Constants
const API_BASE_URL = "http://127.0.0.1:8000";
const SCORE_CIRCUMFERENCE = 239;

// State
let latestDiagnostics = null;
let pendingErrorRetry = null;
const currentTaskScores = {
  email: 98,
  video_call: 96,
  upload_1gb: 58,
  music: 96,
  video_4k: 53,
  whatsapp: 98,
};

// Content libraries
const taskMessageLibrary = {
  email: {
    label: "Email",
    icon: "@",
    bands: {
      excellent: {
        verdict: "yes",
        title: "Email is reliable",
        explanation: "Email should send and receive reliably with minimal delay. Inbox refresh, login handshakes, and small attachments have plenty of headroom.",
        fallback: "Send normally. Keep the tab open for large attachments until the sent confirmation appears.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "Email should work",
        explanation: "Text mail, inbox sync, and normal attachments should complete cleanly. Large files may take a little longer if the connection dips.",
        fallback: "Send urgent text first, then attach larger files in a separate message.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "Email is usable",
        explanation: "Text messages should send, but attachment uploads and inbox refreshes may pause during latency spikes.",
        fallback: "Copy important text before sending and keep attachments small.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "Email may stall",
        explanation: "Basic text might move, but sign-in refreshes, outbox sync, and attachments can time out at this level.",
        fallback: "Avoid attachments and wait for a stronger score before sending critical mail.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "Email is not dependable",
        explanation: "Sends may fail, attachments may partially upload, and inbox changes may remain stuck in the outbox.",
        fallback: "Switch networks or wait before sending anything important.",
        confidenceText: "Very low confidence",
      },
    },
  },
  video_call: {
    label: "Video call",
    icon: "VC",
    bands: {
      excellent: {
        verdict: "yes",
        title: "Video call is ready",
        explanation: "Camera, microphone, and screen sharing should stay smooth with minimal lag or audio gaps.",
        fallback: "Join normally. Pause large downloads if the meeting is important.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "Video call should hold",
        explanation: "A call should work well, though the app may briefly lower quality if other devices start using bandwidth.",
        fallback: "Close streaming apps and keep screen share light.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "Video call may wobble",
        explanation: "A call may work, but expect occasional lag or quality drops. Audio is more likely to survive than camera-on video.",
        fallback: "Join with camera off first, then enable video if the first minute stays stable.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "Video will struggle",
        explanation: "Live traffic is exposed to lag, packet recovery, and reconnects. Group calls and screen share are likely to feel unstable.",
        fallback: "Use audio only, move closer to the router, or switch to a wired connection.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "Video call is not reliable",
        explanation: "This score is below the practical floor for live calls. Expect missed speech, frozen video, or repeated reconnects.",
        fallback: "Use phone audio or reschedule until the connection score recovers.",
        confidenceText: "Very low confidence",
      },
    },
  },
  upload_1gb: {
    label: "1 GB upload",
    icon: "UP",
    bands: {
      excellent: {
        verdict: "yes",
        title: "Large upload is safe",
        explanation: "A 1 GB transfer should finish cleanly without repeated retries or long idle stalls.",
        fallback: "Keep the upload tab open and avoid restarting the router mid-transfer.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "Upload should complete",
        explanation: "A 1 GB file should upload, though completion time may stretch if background devices compete for bandwidth.",
        fallback: "Pause streaming and cloud sync until the upload reaches 100%.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "Upload may be slow",
        explanation: "The upload can start, but a 1 GB file may be slow and vulnerable to stalls if the connection drops briefly.",
        fallback: "Use a resumable uploader such as Drive, Dropbox, or OneDrive.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "Upload is high risk",
        explanation: "A large transfer may restart, sit at 0%, or fail near completion because the connection cannot sustain throughput.",
        fallback: "Compress the file, split it into smaller parts, or wait until the score is above 75%.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "Upload is not recommended",
        explanation: "Not recommended right now. The upload may stall or take too long.",
        fallback: "Reconnect to a stronger network before starting the transfer.",
        confidenceText: "Very low confidence",
      },
    },
  },
  music: {
    label: "Music",
    icon: "M",
    bands: {
      excellent: {
        verdict: "yes",
        title: "Music will feel instant",
        explanation: "Audio streaming has plenty of headroom, so track starts, playlist loads, and skipping should feel immediate.",
        fallback: "High-quality audio is safe to leave enabled.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "Music should stay stable",
        explanation: "Music should stream continuously with enough buffer margin for normal browsing at the same time.",
        fallback: "Download a playlist only if you need uninterrupted playback while moving networks.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "Music is mostly okay",
        explanation: "Playback should work, but starting new tracks or switching playlists may buffer when the network briefly dips.",
        fallback: "Use standard audio quality and avoid rapid track skipping.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "Music may buffer",
        explanation: "The player may pause while rebuilding buffer, especially at track changes or when starting a new playlist.",
        fallback: "Use downloaded music or force low-quality streaming.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "Streaming is unreliable",
        explanation: "Even audio may struggle to maintain a buffer. Playback can fail to start or stop repeatedly.",
        fallback: "Use offline playback until the signal recovers.",
        confidenceText: "Very low confidence",
      },
    },
  },
  video_4k: {
    label: "4K video",
    icon: "4K",
    bands: {
      excellent: {
        verdict: "yes",
        title: "4K is ready",
        explanation: "4K playback has enough bandwidth headroom for startup buffer, seeking, and adaptive bitrate without frequent drops.",
        fallback: "Keep downloads paused if you want the stream to stay locked at 4K.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "4K should work",
        explanation: "4K should work, but adaptive players may step down briefly if other devices start heavy traffic.",
        fallback: "Let the video buffer for 10-15 seconds before scrubbing.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "4K may be uneven",
        explanation: "A 4K stream may start, but sustained playback is uncertain. Expect buffering or automatic drops to 1080p.",
        fallback: "Choose 1080p manually for a smoother session.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "4K will likely buffer",
        explanation: "Likely to buffer. Drop to 720p or 1080p.",
        fallback: "Switch to 720p or 1080p before playback starts.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "4K is not realistic",
        explanation: "The connection is too weak for high-bitrate video. Playback will likely stall, downgrade immediately, or fail to load.",
        fallback: "Use standard definition and retry 4K after the score improves.",
        confidenceText: "Very low confidence",
      },
    },
  },
  whatsapp: {
    label: "WhatsApp",
    icon: "WA",
    bands: {
      excellent: {
        verdict: "yes",
        title: "WhatsApp is smooth",
        explanation: "Messaging, voice notes, and light calls should work smoothly.",
        fallback: "Use WhatsApp normally, including media and voice notes.",
        confidenceText: "Very high confidence",
      },
      strong: {
        verdict: "yes",
        title: "WhatsApp should work",
        explanation: "Text, delivery receipts, and voice notes should be reliable. Larger videos may take longer.",
        fallback: "Compress long videos or wait for Wi-Fi before sending them.",
        confidenceText: "High confidence",
      },
      mixed: {
        verdict: "maybe",
        title: "WhatsApp is usable",
        explanation: "Text messages should still deliver, but photos, voice notes, and delivery receipts may lag during network dips.",
        fallback: "Use text for urgent messages and retry media if it stays pending.",
        confidenceText: "Moderate confidence",
      },
      weak: {
        verdict: "no",
        title: "WhatsApp may lag",
        explanation: "Short messages may still pass, but voice notes, images, and reconnecting calls may feel inconsistent.",
        fallback: "Stick to text and avoid sending media until the score improves.",
        confidenceText: "Low confidence",
      },
      poor: {
        verdict: "no",
        title: "WhatsApp is shaky",
        explanation: "Messages may sit unsent, and media uploads may fail before completion.",
        fallback: "Switch networks or move closer to the router before sending anything important.",
        confidenceText: "Very low confidence",
      },
    },
  },
};

const recommendationGuides = {
  "Switch DNS to 8.8.8.8": {
    title: "Switch DNS to 8.8.8.8",
    reason: "DNS response time is elevated, so websites may feel slow to start loading.",
    expectedImpact: "High impact",
    estimatedTime: "30 sec",
    steps: [
      "Open your network settings.",
      "Find your active Wi-Fi or Ethernet connection.",
      "Set DNS server to 8.8.8.8 and backup DNS to 8.8.4.4.",
      "Save changes and rerun NetLens.",
    ],
    bestFor: "Slow page starts, app login delays, and high DNS lookup times.",
    note: "This helps mostly when DNS lookup is the bottleneck, not when the full connection is weak.",
  },
  "Disconnect background devices": {
    title: "Disconnect background devices",
    reason: "Your score suggests shared traffic may be competing with this device and reducing available bandwidth.",
    expectedImpact: "High impact",
    estimatedTime: "1 min",
    steps: [
      "Pause streaming boxes, game consoles, and cloud backup devices.",
      "Stop large downloads on laptops and phones using the same network.",
      "Ask other users to pause video calls or uploads for a minute.",
      "Run NetLens again and compare the download and packet loss values.",
    ],
    bestFor: "Weak bandwidth, upload stalls, and evening congestion.",
    note: "This is most useful when the network is shared and one device is consuming a large slice of available bandwidth.",
  },
  "Move closer to router": {
    title: "Move closer to router",
    reason: "Packet loss or latency can rise when the Wi-Fi signal is weak, blocked, or bouncing through walls.",
    expectedImpact: "Medium impact",
    estimatedTime: "Instant",
    steps: [
      "Move within the same room as the router if possible.",
      "Keep the device above desk height and away from metal surfaces.",
      "Avoid thick walls, microwaves, and crowded power strips between you and the router.",
      "Run another diagnostic and check whether latency and loss improve.",
    ],
    bestFor: "Unstable video calls, gaming lag, and sudden packet loss.",
    note: "This helps Wi-Fi quality. It will not fix a slow internet plan or an upstream provider issue.",
  },
  "Pause downloads": {
    title: "Pause downloads",
    reason: "Large transfers can saturate bandwidth and make real-time tasks feel laggy or unreliable.",
    expectedImpact: "High impact",
    estimatedTime: "Instant",
    steps: [
      "Pause browser downloads, app updates, and cloud sync jobs.",
      "Stop video streams or lower them to standard definition.",
      "Wait 10 seconds for bandwidth to clear.",
      "Run NetLens again before starting calls, uploads, or 4K video.",
    ],
    bestFor: "Video calls, large uploads, gaming, and latency-sensitive work.",
    note: "This is a temporary fix. If downloads restart automatically, the connection may degrade again.",
  },
  "Restart router": {
    title: "Restart router",
    reason: "A router restart can clear stale sessions, memory pressure, and radio issues that cause packet loss.",
    expectedImpact: "High impact",
    estimatedTime: "2 min",
    steps: [
      "Unplug the router power cable.",
      "Wait 20 seconds before plugging it back in.",
      "Give the network one to two minutes to reconnect fully.",
      "Run NetLens again and compare packet loss and latency.",
    ],
    bestFor: "Persistent packet loss, stuck connections, and sudden whole-home network issues.",
    note: "Avoid restarting during active calls, uploads, or downloads because every connected device will briefly disconnect.",
  },
  "Reduce video quality": {
    title: "Reduce video quality",
    reason: "The connection may not have enough stable headroom for high-bitrate video right now.",
    expectedImpact: "Medium impact",
    estimatedTime: "15 sec",
    steps: [
      "Open the video player's quality menu.",
      "Switch from 4K or 1080p to 720p.",
      "Let the video buffer for 10 seconds before scrubbing.",
      "Rerun NetLens if buffering continues.",
    ],
    bestFor: "4K video buffering, unstable streams, and shared networks under load.",
    note: "Lowering quality reduces bandwidth pressure immediately while keeping playback smooth.",
  },
  "Retry later": {
    title: "Retry later",
    reason: "The current network condition looks temporary or congested, so waiting may be the fastest reliable fix.",
    expectedImpact: "Medium impact",
    estimatedTime: "5-15 min",
    steps: [
      "Pause the task you were about to start.",
      "Wait a few minutes for congestion or signal fluctuation to settle.",
      "Avoid starting large downloads while waiting.",
      "Run NetLens again and compare the score before retrying.",
    ],
    bestFor: "Short-lived congestion, unstable scores, and non-urgent uploads or streams.",
    note: "If the score stays weak after multiple retries, use one of the active fixes instead of waiting longer.",
  },
};

const $ = (id) => document.getElementById(id);

// Utilities
function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

// API functions
async function postJson(path, body = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

async function getJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

async function checkAgentHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
    updateAgentStatus(true);
    return true;
  } catch {
    updateAgentStatus(false);
    return false;
  }
}

// UI rendering functions
function updateAgentStatus(isConnected) {
  $("agent-pill")?.classList.toggle("is-offline", !isConnected);
  $("live-pill")?.classList.toggle("is-offline", !isConnected);
  setText("agent-status-text", isConnected ? "Agent connected" : "Agent not detected");
  setText("live-status-text", isConnected ? "live" : "demo mode");
  if (!isConnected) {
    setText("status-chip", "demo mode");
  }
}

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function setFill(id, percent) {
  const element = $(id);
  if (element) element.style.width = `${clamp(percent, 0, 100)}%`;
}

function updateScore(score, status) {
  setText("gauge-n", score);
  setText("status-chip", status || "demo mode");

  const arc = $("score-arc");
  if (arc) {
    arc.style.strokeDashoffset = SCORE_CIRCUMFERENCE * (1 - score / 100);
    arc.style.stroke = status === "good" ? "#6ec896" : status === "poor" ? "#c96e6e" : "#c8a96e";
  }
}

function updateMetrics(result) {
  latestDiagnostics = result;

  updateScore(result.score, result.status);
  document.getElementById("gauge-n").innerText = result.score;
  document.getElementById("latency-val").innerText = result.latency_ms;
  document.getElementById("packet-loss-val").innerText = result.packet_loss;
  document.getElementById("download-val").innerText = result.download_mbps;
  document.getElementById("dns-val").innerText = result.dns_ms;
  setText("last-scan", `last scan ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);

  setFill("latency-fill", 100 - (clamp(result.latency_ms, 0, 250) / 250) * 100);
  setFill("loss-fill", 100 - (clamp(result.packet_loss, 0, 25) / 25) * 100);
  setFill("download-fill", (clamp(result.download_mbps, 0, 25) / 25) * 100);
  setFill("dns-fill", 100 - (clamp(result.dns_ms, 0, 150) / 150) * 100);

  setText("verdict-title", result.verdict_title);
  setText("verdict-sub", result.verdict_subtitle);
  renderAiInsight(result);
  updateTaskPercentages(result.tasks);
  renderRecommendations(result.recommendations);
}

function renderAiInsight(result) {
  const card = $("ai-insight-card");
  if (!card) return;

  const summary = cleanInsightText(result?.ai_summary);
  const mainIssue = cleanInsightText(result?.main_issue);
  const bestNextAction = cleanInsightText(result?.best_next_action);
  const riskLevel = normalizeRiskLevel(result?.risk_level);

  if (!summary && !mainIssue && !bestNextAction && !riskLevel) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  card.classList.remove("risk-low", "risk-medium", "risk-high");
  if (riskLevel) {
    card.classList.add(`risk-${riskLevel}`);
  }

  setText("ai-summary", summary || "NetLens generated a compact rule-based summary for this scan.");
  setText("ai-main-issue", mainIssue || "No major issue detected");
  setText("ai-best-next-action", bestNextAction || "Keep monitoring your connection");
  setText("ai-risk-level", riskLevel ? `${riskLevel} risk` : "risk unknown");
}

function cleanInsightText(value) {
  const text = String(value || "").trim();
  return text.length > 0 ? text : "";
}

function normalizeRiskLevel(value) {
  const risk = String(value || "").trim().toLowerCase();
  return ["low", "medium", "high"].includes(risk) ? risk : "";
}

function updateTaskPercentages(tasks) {
  if (!tasks) return;

  Object.keys(currentTaskScores).forEach((taskKey) => {
    const nextScore = normalizeTaskScore(tasks[taskKey]);
    if (Number.isFinite(nextScore)) {
      currentTaskScores[taskKey] = nextScore;
    }
  });

  renderTaskCards();
}

function normalizeTaskScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return null;
  return Math.round(clamp(score, 0, 100));
}

function renderTaskCards() {
  updateTaskCard("task-email", currentTaskScores.email);
  updateTaskCard("task-video-call", currentTaskScores.video_call);
  updateTaskCard("task-upload", currentTaskScores.upload_1gb);
  updateTaskCard("task-music", currentTaskScores.music);
  updateTaskCard("task-4k", currentTaskScores.video_4k);
  updateTaskCard("task-whatsapp", currentTaskScores.whatsapp);
}

function updateTaskCard(elementId, value) {
  const element = $(elementId);
  if (!element) return;

  const card = element.closest(".task");
  const score = normalizeTaskScore(value);
  if (!Number.isFinite(score)) return;

  element.textContent = `${score}%`;

  if (!card) return;
  card.dataset.score = String(score);
  card.classList.remove("t-y", "t-w", "t-n");
  card.classList.add(score >= 75 ? "t-y" : score >= 55 ? "t-w" : "t-n");
}

// Recommendations
function renderRecommendations(recommendations) {
  const list = $("fix-list");
  if (!list || !Array.isArray(recommendations) || recommendations.length === 0) return;

  list.innerHTML = recommendations
    .slice(0, 3)
    .map((recommendation, index) => {
      const rankClass = index === 0 ? "r1" : index === 1 ? "r2" : "r3";
      const guide = findRecommendationGuide(recommendation.title);
      const impact = recommendation.impact || guide.expectedImpact.replace(" impact", "").toLowerCase();
      const dotColor = impact === "high" ? "#c8a96e" : "#7a7060";
      const time = recommendation.time || guide.estimatedTime;

      return `
        <div class="fix">
          <div class="fix-rank ${rankClass}">${index + 1}</div>
          <div class="fix-body">
            <div class="fix-title">${recommendation.title}</div>
            <div class="fix-meta">
              <span><span class="impact-dot" style="background:${dotColor}"></span>${impact} impact</span>
              <span>${time}</span>
            </div>
            <button class="fix-action" type="button" data-guide-title="${recommendation.title}">guide me &rarr;</button>
          </div>
        </div>
      `;
    })
    .join("");

}

function openRecommendationGuide(title) {
  const guide = findRecommendationGuide(title);
  showRecommendationGuidePopup(guide);
}

function findRecommendationGuide(title = "") {
  if (recommendationGuides[title]) return recommendationGuides[title];

  const normalizedTitle = normalizeGuideTitle(title);
  const directMatch = Object.entries(recommendationGuides).find(([guideTitle]) => normalizeGuideTitle(guideTitle) === normalizedTitle);
  if (directMatch) return directMatch[1];

  const keywordMatches = [
    { key: "Switch DNS to 8.8.8.8", terms: ["dns", "lookup", "8.8.8.8", "8.8.4.4"] },
    { key: "Disconnect background devices", terms: ["background", "device", "devices", "congestion", "shared", "competing"] },
    { key: "Move closer to router", terms: ["router", "closer", "wifi", "wi-fi", "signal", "wireless"] },
    { key: "Pause downloads", terms: ["pause", "download", "downloads", "upload", "cloud sync", "sync"] },
    { key: "Restart router", terms: ["restart", "reboot", "power cycle"] },
    { key: "Reduce video quality", terms: ["video quality", "4k", "1080p", "720p", "buffer", "stream"] },
    { key: "Retry later", terms: ["retry", "later", "wait", "temporary"] },
  ];

  const match = keywordMatches.find(({ terms }) => terms.some((term) => normalizedTitle.includes(term)));
  return match ? recommendationGuides[match.key] : buildFallbackRecommendationGuide(title);
}

function normalizeGuideTitle(title) {
  return String(title).toLowerCase().replace(/[^a-z0-9.]+/g, " ").trim();
}

function buildFallbackRecommendationGuide(title) {
  return {
    title: title || "Recommended fix",
    reason: "NetLens selected this action because it can improve the weakest part of the current connection profile.",
    expectedImpact: "Medium impact",
    estimatedTime: "1 min",
    steps: [
      "Apply the recommendation in your network setup.",
      "Wait a few seconds for the connection to stabilize.",
      "Run NetLens again and compare the score.",
    ],
    bestFor: "Fair or poor scores when you need a quick improvement.",
    note: "Use this as a general fix when NetLens receives a recommendation title that is not in the guide library yet.",
  };
}

// Diagnostics and task analysis
async function runDiagnostics() {
  const button = $("run-diagnostics-btn");

  try {
    if (button) {
      button.classList.add("is-loading");
      button.disabled = true;
      button.querySelector("span").textContent = "Running diagnosis...";
    }
    setDiagnosticsLoading(true);

    const isAgentReady = await checkAgentHealth();
    if (!isAgentReady) {
      showAgentUnavailableModal("NetLens Agent is not running. Start the backend locally to run live diagnostics.");
      return;
    }

    const result = await postJson("/api/v1/diagnostics/run");
    updateMetrics(result);
    await loadDiagnosticsHistory();
    if (!$("history-view")?.hidden) {
      await refreshHistoryView();
    }
  } catch {
    showAgentUnavailableModal();
  } finally {
    setDiagnosticsLoading(false);
    if (button) {
      button.classList.remove("is-loading");
      button.disabled = false;
      button.querySelector("span").textContent = "Run full AI diagnosis";
    }
  }
}

function setDiagnosticsLoading(isLoading) {
  $("metrics-grid")?.classList.toggle("is-loading", isLoading);
}

function showAgentUnavailableModal(message = "Live diagnostics require the local FastAPI agent to be running.", retryAction = runDiagnostics) {
  showErrorModal({
    taskLabel: "NetLens Agent",
    icon: "!",
    severity: "no",
    title: "NetLens Agent not detected",
    explanation: message,
    action: "Start the backend with uvicorn main:app --reload, then try again.",
    retryAction,
  });
}

function showErrorModal({
  title,
  explanation,
  action,
  severity = "no",
  taskLabel = "NetLens",
  icon = "!",
  retryAction = null,
}) {
  pendingErrorRetry = retryAction;
  showTaskResultPopup({
    taskLabel,
    icon,
    verdict: severity,
    title,
    explanation,
    fallback: action,
    confidenceText: severity === "no" ? "Action needed" : "Needs attention",
    isError: true,
    hasRetry: Boolean(retryAction),
  });
}

// Task cards
function getScoreBand(score) {
  if (score >= 90) return "excellent";
  if (score >= 75) return "strong";
  if (score >= 55) return "mixed";
  if (score >= 35) return "weak";
  return "poor";
}

function buildTaskPopupData(taskKey) {
  const task = taskMessageLibrary[taskKey];
  const score = currentTaskScores[taskKey];
  if (!task || !Number.isFinite(score)) return null;

  const band = getScoreBand(score);
  const message = task.bands[band];

  return {
    taskKey,
    taskLabel: task.label,
    icon: task.icon,
    score,
    band,
    ...message,
  };
}

function openTaskCardPopup(card) {
  const data = buildTaskPopupData(card.dataset.taskKey);
  if (!data) return;

  document.querySelectorAll(".task.is-selected").forEach((selectedCard) => {
    selectedCard.classList.remove("is-selected");
  });
  card.classList.add("is-selected");
  window.setTimeout(() => card.classList.remove("is-selected"), 260);
  showTaskResultPopup(data);
}

async function checkTask(task, options = {}) {
  if (!latestDiagnostics) {
    await runDiagnostics();
  }

  if (!latestDiagnostics) {
    await checkAgentHealth();
    throw new Error("NetLens agent unavailable");
  }

  const result = await postJson("/api/v1/assistant/check-task", {
    task,
    latency_ms: latestDiagnostics.latency_ms,
    packet_loss: latestDiagnostics.packet_loss,
    download_mbps: latestDiagnostics.download_mbps,
  });

  if (!options.silent) {
    showTaskResultPopup(result);
  }

  return result;
}

async function analyzeAskNetLens(event) {
  event.preventDefault();

  const input = $("ask-input");
  const form = $("ask-form");
  const button = form?.querySelector("button[type='submit']");
  const task = input?.value.trim() || input?.placeholder;
  if (!task) return;

  try {
    form?.classList.add("is-loading");
    if (button) {
      button.disabled = true;
      button.textContent = "Analyzing...";
    }
    const result = await checkTask(task, { silent: true });
    showTaskResultPopup({
      taskLabel: "Ask NetLens",
      score: Math.round(result.confidence * 100),
      icon: result.verdict === "yes" ? "OK" : result.verdict === "no" ? "!" : "?",
      title: "Task analysis",
      ...result,
    });
  } catch {
    showAgentUnavailableModal();
  } finally {
    form?.classList.remove("is-loading");
    if (button) {
      button.disabled = false;
      button.textContent = "Analyze";
    }
  }
}

// Modal functions
function showTaskResultPopup(data) {
  const overlay = $("task-popup-overlay");
  const popup = $("task-popup");
  const verdict = $("task-popup-verdict");
  const icon = $("task-popup-icon");
  const errorActions = $("error-actions");
  const errorRetry = $("error-retry");

  if (!overlay || !popup || !verdict || !icon) return;

  const verdictValue = data.verdict || "maybe";

  overlay.hidden = false;
  popup.className = `task-popup ${verdictValue}${data.isError ? " error-mode" : ""}`;
  $("guide-steps").hidden = true;
  if (errorActions) errorActions.hidden = !data.hasRetry;
  if (errorRetry) errorRetry.textContent = "Try again";
  setFallbackLabel(data.isError ? "Suggested action" : "Fallback");
  verdict.className = `task-popup-badge ${verdictValue}`;
  verdict.textContent = data.isError ? "ERROR" : verdictValue.toUpperCase();
  icon.textContent = data.icon || (verdictValue === "yes" ? "OK" : verdictValue === "no" ? "!" : "?");
  setText("task-popup-task", data.taskLabel || "Ask NetLens");
  setText("task-popup-score", Number.isFinite(data.score) ? `${data.score}%` : "--");
  setText("task-popup-title", data.title || "Task readiness");
  setText("task-popup-confidence", data.confidenceText || `${Math.round((data.confidence || 0) * 100)}% confidence`);
  setText("task-popup-explanation", data.explanation);
  setText("task-popup-fallback", data.fallback);

  requestAnimationFrame(() => {
    overlay.classList.add("is-open");
  });
}

function showRecommendationGuidePopup(guide) {
  const overlay = $("task-popup-overlay");
  const popup = $("task-popup");
  const verdict = $("task-popup-verdict");
  const icon = $("task-popup-icon");
  const steps = $("guide-steps");
  const stepList = $("guide-step-list");

  if (!overlay || !popup || !verdict || !icon || !steps || !stepList) return;

  overlay.hidden = false;
  popup.className = "task-popup maybe guide-mode";
  $("error-actions").hidden = true;
  verdict.className = "task-popup-badge maybe";
  verdict.textContent = guide.expectedImpact.toUpperCase();
  icon.textContent = "AI";
  setText("task-popup-task", "Recommendation guide");
  setText("task-popup-score", guide.estimatedTime);
  setText("task-popup-title", guide.title);
  setText("task-popup-confidence", `Estimated time: ${guide.estimatedTime}`);
  setText("task-popup-explanation", guide.reason);
  setFallbackLabel("Best for");
  setText("task-popup-fallback", `${guide.bestFor} ${guide.note}`);

  stepList.textContent = "";
  guide.steps.forEach((step) => {
    const item = document.createElement("li");
    item.textContent = step;
    stepList.appendChild(item);
  });
  steps.hidden = false;

  requestAnimationFrame(() => {
    overlay.classList.add("is-open");
  });
}

function setFallbackLabel(label) {
  const fallbackLabel = document.querySelector(".task-popup-fallback span");
  if (fallbackLabel) fallbackLabel.textContent = label;
}

function closeTaskResultPopup() {
  const overlay = $("task-popup-overlay");
  if (!overlay) return;

  overlay.classList.remove("is-open");
  window.setTimeout(() => {
    overlay.hidden = true;
    $("guide-steps").hidden = true;
    $("error-actions").hidden = true;
    pendingErrorRetry = null;
  }, 180);
}

// View and navigation
function switchView(viewName) {
  const nextView = $(`${viewName}-view`);
  if (!nextView) return;

  document.querySelectorAll(".nav-btn[data-view-target]").forEach((button) => {
    button.classList.toggle("act", button.dataset.viewTarget === viewName);
  });

  document.querySelectorAll(".app-view").forEach((view) => {
    if (view === nextView) return;
    view.classList.remove("is-active");
    window.setTimeout(() => {
      if (!view.classList.contains("is-active")) {
        view.hidden = true;
      }
    }, 220);
  });

  nextView.hidden = false;
  requestAnimationFrame(() => {
    nextView.classList.add("is-active");
  });

  if (viewName === "history") {
    refreshHistoryView();
  }
}

function openAskNetLensSection() {
  switchView("dashboard");

  const askNav = $("ask-ai-nav");
  askNav?.classList.add("is-temp-active");
  window.setTimeout(() => askNav?.classList.remove("is-temp-active"), 1400);

  window.setTimeout(() => {
    const section = $("ask-netlens-section");
    const input = $("ask-input");

    section?.scrollIntoView({ behavior: "smooth", block: "center" });
    section?.classList.add("is-highlighted");
    window.setTimeout(() => section?.classList.remove("is-highlighted"), 1600);
    window.setTimeout(() => input?.focus(), 360);
  }, 240);
}

function runAskExample(example) {
  const input = $("ask-input");
  const form = $("ask-form");
  if (!input || !form) return;

  input.value = example;
  input.focus();
  form.requestSubmit();
}

// History
async function loadDiagnosticsHistory() {
  try {
    const payload = await getJson("/api/v1/diagnostics/history");
    const history = getHistoryRecords(payload);
    const scores = history.map((record) => record.score).filter((score) => Number.isFinite(score));

    if (scores.length > 0) {
      renderSparkline(scores);
    }

    return history;
  } catch {
    return null;
  }
}

function getHistoryRecords(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.history)) return payload.history;
  if (Array.isArray(payload?.records)) return payload.records;
  if (Array.isArray(payload?.scans)) return payload.scans;
  return [];
}

async function refreshHistoryView() {
  setHistoryLoading(true);
  setHistoryMessage("Loading history...");
  const isAgentReady = await checkAgentHealth();
  if (!isAgentReady) {
    setHistoryLoading(false);
    renderHistoryUnavailable();
    showErrorModal({
      taskLabel: "History",
      title: "History unavailable",
      explanation: "History cannot load because the NetLens Agent is not running.",
      action: "Start the backend with uvicorn main:app --reload, then refresh history.",
      severity: "maybe",
      icon: "!",
      retryAction: refreshHistoryView,
    });
    return;
  }
  const history = await loadDiagnosticsHistory();

  if (history === null) {
    setHistoryLoading(false);
    renderHistoryUnavailable();
    showErrorModal({
      taskLabel: "History",
      title: "History unavailable",
      explanation: "NetLens could not read diagnostic history right now.",
      action: "Check that the local backend is running and try refreshing history.",
      severity: "maybe",
      icon: "!",
      retryAction: refreshHistoryView,
    });
    return;
  }

  setHistoryLoading(false);
  renderHistoryView(Array.isArray(history) ? history : []);
}

function setHistoryLoading(isLoading) {
  $("history-view")?.classList.toggle("is-loading", isLoading);
  $("history-refresh")?.toggleAttribute("disabled", isLoading);
}

function renderHistoryView(history) {
  const records = history.map(normalizeHistoryRecord).filter(Boolean);
  const state = $("history-state");
  const bars = $("history-bars");
  const list = $("history-list");

  if (!state || !bars || !list) return;

  resetHistorySummary();
  bars.textContent = "";
  list.textContent = "";
  setText("history-count", `${records.length} ${records.length === 1 ? "scan" : "scans"}`);

  if (records.length === 0) {
    setHistoryMessage("No scan history yet. Run a diagnosis to start building your network timeline.");
    return;
  }

  state.hidden = true;
  renderHistorySummary(records);
  renderHistoryBars(records);
  renderHistoryList(records);
}

function normalizeHistoryRecord(record) {
  if (!record || typeof record !== "object") return null;

  const score = Number(record.score);
  const latency = Number(record.latency_ms ?? record.latency ?? record.ping_ms);
  const packetLoss = Number(record.packet_loss ?? record.packet_loss_pct ?? record.loss);

  return {
    timestamp: record.timestamp || record.created_at || record.scanned_at || record.time || record.date,
    score: Number.isFinite(score) ? Math.round(score) : null,
    latency: Number.isFinite(latency) ? Math.round(latency) : null,
    packetLoss: Number.isFinite(packetLoss) ? packetLoss : null,
    status: record.status || inferHistoryStatus(score),
  };
}

function inferHistoryStatus(score) {
  if (!Number.isFinite(score)) return "unknown";
  if (score >= 75) return "good";
  if (score >= 55) return "fair";
  return "poor";
}

function renderHistorySummary(records) {
  const scores = records.map((record) => record.score).filter(Number.isFinite);
  const latencies = records.map((record) => record.latency).filter(Number.isFinite);
  const losses = records.map((record) => record.packetLoss).filter(Number.isFinite);

  setText("history-avg-score", average(scores));
  setText("history-avg-latency", average(latencies));
  setText("history-avg-loss", average(losses, 1));
  setText("history-best-score", scores.length ? Math.max(...scores) : "--");
}

function renderHistoryBars(records) {
  const bars = $("history-bars");
  if (!bars) return;

  const scores = records.map((record) => record.score).filter(Number.isFinite).slice(-24);
  const max = Math.max(...scores, 1);
  bars.textContent = "";

  scores.forEach((score) => {
    const bar = document.createElement("div");
    bar.className = "sbar";
    bar.style.height = `${Math.max(6, Math.round((score / max) * 100))}%`;
    bar.style.background = score >= 75 ? "#6ec896" : score >= 55 ? "#c8a96e" : "#c96e6e";
    bar.title = `${score} score`;
    bars.appendChild(bar);
  });
}

function renderHistoryList(records) {
  const list = $("history-list");
  if (!list) return;

  const header = createHistoryRow(["timestamp", "score", "latency", "packet loss", "status"], true);
  list.appendChild(header);

  records.slice().reverse().slice(0, 12).forEach((record) => {
    const row = createHistoryRow([
      formatHistoryTimestamp(record.timestamp),
      record.score === null ? "--" : `${record.score}`,
      record.latency === null ? "--" : `${record.latency} ms`,
      record.packetLoss === null ? "--" : `${formatNumber(record.packetLoss, 1)} %`,
      record.status,
    ]);
    row.querySelector(".history-score")?.classList.add(scoreClass(record.score));
    row.querySelector(".history-status")?.classList.add(String(record.status).toLowerCase());
    list.appendChild(row);
  });
}

function createHistoryRow(values, isHeader = false) {
  const row = document.createElement("div");
  row.className = `history-row${isHeader ? " is-head" : ""}`;

  values.forEach((value, index) => {
    const cell = document.createElement("span");
    if (index === 1) cell.className = "history-score";
    if (index === 4) cell.className = "history-status";
    cell.textContent = value;
    row.appendChild(cell);
  });

  return row;
}

function renderHistoryUnavailable() {
  resetHistorySummary();
  setText("history-count", "0 scans");
  if ($("history-bars")) $("history-bars").textContent = "";
  if ($("history-list")) $("history-list").textContent = "";
  setHistoryMessage("History is unavailable because the NetLens agent is not running.");
}

function setHistoryMessage(message) {
  const state = $("history-state");
  if (!state) return;

  state.textContent = message;
  state.hidden = false;
}

function resetHistorySummary() {
  setText("history-avg-score", "--");
  setText("history-avg-latency", "--");
  setText("history-avg-loss", "--");
  setText("history-best-score", "--");
}

function average(values, digits = 0) {
  if (!values.length) return "--";
  return formatNumber(values.reduce((sum, value) => sum + value, 0) / values.length, digits);
}

function formatNumber(value, digits = 0) {
  return Number(value).toFixed(digits).replace(/\.0$/, "");
}

function formatHistoryTimestamp(value) {
  if (!value) return "unknown";

  const rawDate = typeof value === "number" && value < 1000000000000 ? value * 1000 : value;
  const date = new Date(rawDate);
  if (Number.isNaN(date.getTime())) return String(value);

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scoreClass(score) {
  if (!Number.isFinite(score)) return "";
  if (score >= 75) return "good";
  if (score >= 55) return "fair";
  return "poor";
}

// Charts
function renderSparkline(vals) {
  const cols = vals.map((value) => (value >= 65 ? "#6ec896" : value >= 45 ? "#c8a96e" : "#c96e6e"));
  const max = Math.max(...vals, 1);
  const spark = $("spark");

  if (!spark) return;
  spark.textContent = "";

  vals.forEach((value, index) => {
    const bar = document.createElement("div");
    bar.className = "sbar";
    bar.style.cssText = `height:${Math.round((value / max) * 100)}%;background:${cols[index]};cursor:pointer;`;
    bar.title = `${value} score`;
    bar.addEventListener("mouseenter", () => {
      bar.style.opacity = "1";
    });
    bar.addEventListener("mouseleave", () => {
      bar.style.opacity = "0.74";
    });
    spark.appendChild(bar);
  });
}

function renderStaticSparkline() {
  renderSparkline([28, 40, 52, 38, 70, 82, 62, 85, 68, 50, 40, 35, 44, 58, 70]);
}

// Event listeners
function attachEventListeners() {
  document.querySelectorAll("[data-task-key]").forEach((card) => {
    card.addEventListener("click", () => openTaskCardPopup(card));
  });

  $("ask-form")?.addEventListener("submit", analyzeAskNetLens);
  $("task-popup-close")?.addEventListener("click", closeTaskResultPopup);
  $("task-popup-overlay")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) {
      closeTaskResultPopup();
    }
  });
  $("error-retry")?.addEventListener("click", () => {
    const retry = pendingErrorRetry;
    closeTaskResultPopup();
    window.setTimeout(() => retry?.(), 220);
  });
  $("fix-list")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-guide-title]");
    if (!button) return;

    event.stopPropagation();
    button.classList.add("is-loading");
    openRecommendationGuide(button.dataset.guideTitle);
    window.setTimeout(() => button.classList.remove("is-loading"), 360);
  });
  $("dashboard-nav")?.addEventListener("click", () => switchView("dashboard"));
  $("history-nav")?.addEventListener("click", () => switchView("history"));
  $("ask-ai-nav")?.addEventListener("click", openAskNetLensSection);
  $("history-refresh")?.addEventListener("click", refreshHistoryView);
  $("ask-netlens-section")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-ask-example]");
    if (!button) return;

    runAskExample(button.dataset.askExample);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeTaskResultPopup();
    }
  });
}

// Initialization
function initApp() {
  attachEventListeners();
  renderTaskCards();
  renderStaticSparkline();
  checkAgentHealth().then((isConnected) => {
    loadDiagnosticsHistory();
    if (isConnected) {
      runDiagnostics();
    }
  });
}

document.addEventListener("DOMContentLoaded", initApp);
