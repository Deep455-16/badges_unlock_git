/**
 * chatbot.js
 * ------------------------------------------------------------------
 * Flow:
 *   1. User fills GitHub Profile URL + Repo URL + PAT → clicks Connect
 *   2. On success, chatbot greets and asks what badge/goal they want
 *   3. User types their goal → bot sends to /api/plan → shows step list
 *      and enables "Start Execution" button
 *   4. User clicks Start Execution → /api/start fires
 *   5. Terminal streams live via SSE; confirmation prompts pop up as needed
 * ------------------------------------------------------------------
 */

// ── DOM refs ────────────────────────────────────────────────────────────────
const chatLog        = document.getElementById("chat-log");
const chatForm       = document.getElementById("chat-form");
const chatInput      = document.getElementById("chat-input");
const repoLabel      = document.getElementById("repo-label");
const themeToggle    = document.getElementById("theme-toggle");

const configForm     = document.getElementById("config-form");
const connectBtn     = document.getElementById("connect-btn");
const startBtn       = document.getElementById("start-btn");
const terminalLog    = document.getElementById("terminal-log");
const confirmPanel   = document.getElementById("confirmation-panel");
const confirmText    = document.getElementById("confirmation-text");
const btnYes         = document.getElementById("btn-yes");
const btnNo          = document.getElementById("btn-no");

// ── App state ────────────────────────────────────────────────────────────────
let connected     = false;
let pendingBadge  = null;   // badge_id chosen from /api/plan
let definitions   = [];
let badgesData    = {};
let dataLoaded    = false;
let rawBase       = "";
let repoUrlStr    = "";
let repoOwner     = "";
let repoName      = "";
let repoBranch    = "";

// ── Theme ────────────────────────────────────────────────────────────────────
const savedTheme = localStorage.getItem("theme") || "dark";
document.body.setAttribute("data-theme", savedTheme);
updateThemeLabel(savedTheme);

themeToggle.addEventListener("click", () => {
  const next = document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.body.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  updateThemeLabel(next);
});

function updateThemeLabel(theme) {
  themeToggle.textContent = theme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";
}

// ── Chat helpers ─────────────────────────────────────────────────────────────
function addMsg(html, sender = "bot") {
  const el = document.createElement("div");
  el.className = `msg ${sender}`;
  el.innerHTML = html;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function addBadgeList(lines) {
  const el = document.createElement("div");
  el.className = "msg bot badge-list";
  el.innerHTML = lines.map(l => `<div>${l}</div>`).join("");
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

// ── Terminal helpers ──────────────────────────────────────────────────────────
function termLine(text, color = "#0f0") {
  const div = document.createElement("div");
  div.style.color = color;
  div.textContent = `> ${text}`;
  terminalLog.appendChild(div);
  terminalLog.scrollTop = terminalLog.scrollHeight;
}

// ── Connect button ────────────────────────────────────────────────────────────
connectBtn.addEventListener("click", async () => {
  const repoUrl = document.getElementById("repo-url").value.trim();
  const pat     = document.getElementById("github-pat").value.trim();

  if (!repoUrl || !pat) {
    addMsg("⚠️ Please enter both a Repository URL and a Personal Access Token.");
    return;
  }

  connectBtn.disabled = true;
  connectBtn.textContent = "Connecting…";
  termLine("Connecting to GitHub…", "#58a6ff");

  try {
    const res  = await fetch("/api/connect", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ repo_url: repoUrl, pat }),
    });
    const data = await res.json();

    if (!res.ok) {
      addMsg(`❌ ${data.error}`);
      connectBtn.disabled = false;
      connectBtn.textContent = "Connect";
      termLine(`Error: ${data.error}`, "#f00");
      return;
    }

    // Success — store and lock credentials
    repoOwner  = data.owner;
    repoName   = data.repo;
    repoBranch = data.branch;
    rawBase    = `https://raw.githubusercontent.com/${repoOwner}/${repoName}/${repoBranch}/data`;
    repoUrlStr = `https://github.com/${repoOwner}/${repoName}`;

    repoLabel.textContent = `${repoOwner}/${repoName}`;
    connected = true;

    document.getElementById("repo-url").disabled   = true;
    document.getElementById("github-pat").disabled  = true;
    connectBtn.textContent = "✅ Connected";

    termLine(`Connected to ${repoOwner}/${repoName} (branch: ${repoBranch})`, "#0f0");

    // Load badge data + greet
    await loadBadgeData();
    addMsg(
      `👋 Connected to <strong>${repoOwner}/${repoName}</strong>!<br><br>` +
      `Tell me what you'd like to do — for example:<br>` +
      `<em>"I want to unlock the Bug Hunter badge"</em><br>` +
      `<em>"earn the First Contribution badge"</em><br>` +
      `<em>"make a feature PR"</em><br><br>` +
      `Or type <strong>help</strong> to see all available badges.`
    );
    chatInput.placeholder = "What badge do you want to unlock?";
    chatInput.focus();

  } catch (err) {
    addMsg(`❌ Network error: ${err.message}`);
    connectBtn.disabled = false;
    connectBtn.textContent = "Connect";
    termLine(`Network error: ${err.message}`, "#f00");
  }
});

// ── Start Execution button ─────────────────────────────────────────────────
configForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!connected || !pendingBadge) return;

  startBtn.disabled = true;
  startBtn.textContent = "Running…";
  termLine("Starting execution…", "#58a6ff");

  try {
    const res  = await fetch("/api/start", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ target_badge: pendingBadge }),
    });
    const data = await res.json();
    if (!res.ok) {
      addMsg(`❌ ${data.error}`);
      termLine(`Error: ${data.error}`, "#f00");
      startBtn.disabled = false;
      startBtn.textContent = "Start Execution";
    }
  } catch (err) {
    addMsg(`❌ Network error: ${err.message}`);
    termLine(`Network error: ${err.message}`, "#f00");
    startBtn.disabled = false;
    startBtn.textContent = "Start Execution";
  }
});

// ── SSE stream ────────────────────────────────────────────────────────────────
const evtSource = new EventSource("/api/stream");
evtSource.onmessage = (event) => {
  try {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case "log":
        termLine(msg.content, "#0f0");
        break;
      case "error":
        termLine(msg.content, "#f55");
        addMsg(`⚠️ ${msg.content}`);
        startBtn.disabled = false;
        startBtn.textContent = "Start Execution";
        break;
      case "done":
        termLine(msg.content, "#58a6ff");
        addMsg(`🎉 ${msg.content}`);
        startBtn.disabled = false;
        startBtn.textContent = "Start Execution";
        pendingBadge = null;
        // Refresh badge data after a short delay (Actions may still be running)
        setTimeout(loadBadgeData, 8000);
        break;
      case "confirm":
        termLine(msg.content, "#ff0");
        confirmText.textContent = msg.content;
        confirmPanel.classList.remove("hidden");
        break;
    }
  } catch (err) {
    console.error("SSE parse error", err);
  }
};

// ── Confirmation buttons ──────────────────────────────────────────────────────
async function sendConfirm(answer) {
  confirmPanel.classList.add("hidden");
  termLine(`You answered: ${answer}`, answer === "yes" ? "#0f0" : "#f55");
  await fetch("/api/confirm", {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ answer }),
  });
}
btnYes.addEventListener("click", () => sendConfirm("yes"));
btnNo.addEventListener("click",  () => sendConfirm("no"));

// ── Chatbot input ─────────────────────────────────────────────────────────────
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  chatInput.value = "";
  if (!text) return;
  handleUserMessage(text);
});

async function handleUserMessage(text) {
  addMsg(text, "user");
  const lower = text.toLowerCase();

  if (!connected) {
    addMsg("Please connect to a GitHub repository first using the panel on the left.");
    return;
  }

  // Keywords for badge data commands
  if (["help", "badges", "list"].includes(lower)) {
    renderAllBadges();
    return;
  }
  if (["hi", "hello", "hey"].includes(lower)) {
    addMsg("Hey! Tell me which badge you want to unlock, or type <strong>help</strong> to see them all.");
    return;
  }

  // Try to look up as a GitHub username first (short alphanumeric)
  if (/^[a-zA-Z0-9_-]{1,39}$/.test(text.replace(/^@/, ""))) {
    const username = text.replace(/^@/, "");
    if (dataLoaded && badgesData[username]) {
      renderUserBadges(username);
      return;
    }
  }

  // Otherwise treat as a badge goal — call /api/plan
  if (!dataLoaded) {
    addMsg("Badge data is still loading, one moment…");
  }

  addMsg("🤔 Let me plan the steps for that…");
  try {
    const res  = await fetch("/api/plan", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ goal: text }),
    });
    const data = await res.json();
    if (!res.ok) {
      addMsg(`❌ ${data.error}`);
      return;
    }

    pendingBadge = data.badge_id;
    const stepsHtml = data.steps.map(s => `<div style="margin:3px 0">${s}</div>`).join("");
    addMsg(
      `Here's what I'll do to help you unlock <strong>${pendingBadge.replace(/_/g, " ")}</strong>:<br><br>` +
      stepsHtml +
      `<br>When you're ready, click <strong>Start Execution</strong> on the left! 🚀`
    );
    startBtn.disabled = false;

  } catch (err) {
    addMsg(`❌ Network error: ${err.message}`);
  }
}

// ── Badge data ────────────────────────────────────────────────────────────────
async function loadBadgeData() {
  try {
    const [defsRes, badgesRes] = await Promise.all([
      fetch(`${rawBase}/badge-definitions.json?t=${Date.now()}`),
      fetch(`${rawBase}/badges.json?t=${Date.now()}`),
    ]);
    definitions = await defsRes.json();
    badgesData  = await badgesRes.json();
    dataLoaded  = true;
  } catch (err) {
    console.warn("Could not load badge data:", err);
  }
}

function renderAllBadges() {
  if (!dataLoaded) { addMsg("Badge data not loaded yet."); return; }
  addMsg("Here are all the badges you can unlock:");
  addBadgeList(definitions.map(d => `${d.emoji} <strong>${d.name}</strong> — ${d.description}`));
  addMsg(`Tell me which one you want and I'll plan it out for you!`);
}

function renderUserBadges(username) {
  if (!dataLoaded) { addMsg("Badge data not loaded yet."); return; }
  const record = badgesData[username];
  if (!record || !record.badges.length) {
    addMsg(`No badges found for <strong>${username}</strong> yet. Let's earn your first one!`);
    return;
  }
  const unlocked = new Set(record.badges.map(b => b.id));
  addMsg(`<strong>${username}</strong> has ${record.badges.length}/${definitions.length} badges:`);
  addBadgeList(definitions.map(d =>
    unlocked.has(d.id)
      ? `✅ ${d.emoji} <strong>${d.name}</strong>`
      : `🔒 <span style="color:#8b949e">${d.name}</span>`
  ));
}
