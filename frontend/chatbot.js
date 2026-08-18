/**
 * chatbot.js
 * Flow: Connect → type goal → chatbot shows plan → Start Execution → live terminal
 * Confirmations: inline Yes/No buttons in terminal log (no popup overlay)
 * Manual shell: type any command in the terminal input bar
 */

// ── DOM refs ─────────────────────────────────────────────────────────────────
const chatLog      = document.getElementById("chat-log");
const chatForm     = document.getElementById("chat-form");
const chatInput    = document.getElementById("chat-input");
const repoLabel    = document.getElementById("repo-label");
const themeToggle  = document.getElementById("theme-toggle");
const connectBtn   = document.getElementById("connect-btn");
const startBtn     = document.getElementById("start-btn");
const terminalLog  = document.getElementById("terminal-log");
const shellForm    = document.getElementById("shell-form");
const shellInput   = document.getElementById("shell-input");

// ── App state ─────────────────────────────────────────────────────────────────
let connected    = false;
let pendingBadge = null;
let definitions  = [];
let badgesData   = {};
let dataLoaded   = false;
let rawBase      = "";
let repoUrlStr   = "";
let repoOwner    = "";
let repoName     = "";
let repoBranch   = "";

// ── Theme ─────────────────────────────────────────────────────────────────────
const savedTheme = localStorage.getItem("theme") || "dark";
document.body.setAttribute("data-theme", savedTheme);
updateThemeLabel(savedTheme);
themeToggle.addEventListener("click", () => {
  const next = document.body.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.body.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  updateThemeLabel(next);
});
function updateThemeLabel(t) {
  themeToggle.textContent = t === "dark" ? "☀️ Light" : "🌙 Dark";
}

// ── Chat helpers ──────────────────────────────────────────────────────────────
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
  const d = document.createElement("div");
  d.className = "term-line";
  d.style.color = color;
  d.textContent = `> ${text}`;
  terminalLog.appendChild(d);
  terminalLog.scrollTop = terminalLog.scrollHeight;
}

/**
 * Show an inline confirmation row inside the terminal log.
 * Returns a Promise that resolves to "yes" or "no".
 */
function termConfirm(msg) {
  return new Promise((resolve) => {
    const row = document.createElement("div");
    row.className = "term-confirm-row";
    row.innerHTML =
      `<span class="term-q">&gt; ${msg}</span>` +
      `<button class="btn-inline btn-yes">✅ Yes</button>` +
      `<button class="btn-inline btn-no">❌ No</button>`;
    terminalLog.appendChild(row);
    terminalLog.scrollTop = terminalLog.scrollHeight;

    row.querySelector(".btn-yes").addEventListener("click", () => {
      row.querySelector(".btn-yes").disabled = true;
      row.querySelector(".btn-no").disabled  = true;
      termLine("You answered: Yes", "#0f0");
      resolve("yes");
    });
    row.querySelector(".btn-no").addEventListener("click", () => {
      row.querySelector(".btn-yes").disabled = true;
      row.querySelector(".btn-no").disabled  = true;
      termLine("You answered: No", "#f55");
      resolve("no");
    });
  });
}

// ── SSE stream ────────────────────────────────────────────────────────────────
const evtSource = new EventSource("/api/stream");
evtSource.onmessage = async (event) => {
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
        startBtn.textContent = "▶ Start Execution";
        break;

      case "done":
        termLine(msg.content, "#58a6ff");
        addMsg(`🎉 ${msg.content}`);
        startBtn.disabled = false;
        startBtn.textContent = "▶ Start Execution";
        pendingBadge = null;
        setTimeout(loadBadgeData, 10000);
        break;

      case "confirm":
        // Show inline confirmation — user clicks Yes/No in terminal
        const answer = await termConfirm(msg.content);
        await fetch("/api/confirm", {
          method:  "POST",
          headers: {"Content-Type": "application/json"},
          body:    JSON.stringify({ answer }),
        });
        break;
    }
  } catch (err) { console.error("SSE error", err); }
};

// ── Connect ───────────────────────────────────────────────────────────────────
connectBtn.addEventListener("click", async () => {
  const repoUrl = document.getElementById("repo-url").value.trim();
  const pat     = document.getElementById("github-pat").value.trim();

  if (!repoUrl || !pat) {
    addMsg("⚠️ Please enter a Repository URL and a GitHub Token.");
    return;
  }

  connectBtn.disabled = true;
  connectBtn.textContent = "Connecting…";
  termLine("Connecting to GitHub…", "#58a6ff");

  const res  = await fetch("/api/connect", {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ repo_url: repoUrl, pat }),
  }).catch(e => null);

  if (!res) {
    addMsg("❌ Network error. Is the server running?");
    connectBtn.disabled = false;
    connectBtn.textContent = "🔌 Connect";
    return;
  }

  const data = await res.json();

  if (!res.ok) {
    addMsg(`❌ ${data.error}`);
    termLine(`Error: ${data.error}`, "#f55");
    connectBtn.disabled = false;
    connectBtn.textContent = "🔌 Connect";
    return;
  }

  repoOwner  = data.owner;
  repoName   = data.repo;
  repoBranch = data.branch;
  rawBase    = `https://raw.githubusercontent.com/${repoOwner}/${repoName}/${repoBranch}/data`;
  repoUrlStr = `https://github.com/${repoOwner}/${repoName}`;

  repoLabel.textContent = `${repoOwner}/${repoName}`;
  connected = true;

  document.getElementById("repo-url").disabled  = true;
  document.getElementById("github-pat").disabled = true;
  connectBtn.textContent = "✅ Connected";

  termLine(`Connected to ${repoOwner}/${repoName}  (branch: ${repoBranch})`, "#0f0");

  await loadBadgeData();

  addMsg(
    `✅ Connected to <strong>${repoOwner}/${repoName}</strong>!<br><br>` +
    `Now tell me what you'd like to do. Examples:<br>` +
    `<em>"I want the Bug Hunter badge"</em><br>` +
    `<em>"earn the First Contribution badge"</em><br>` +
    `<em>"make a feature PR"</em><br><br>` +
    `Or type <strong>help</strong> to list all badges.`
  );
  chatInput.placeholder = "What badge do you want to unlock?";
  chatInput.focus();
});

// ── Start Execution ───────────────────────────────────────────────────────────
document.getElementById("config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!connected || !pendingBadge) return;

  startBtn.disabled = true;
  startBtn.textContent = "Running…";
  termLine("Starting execution…", "#58a6ff");

  const res  = await fetch("/api/start", {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ target_badge: pendingBadge }),
  });
  const data = await res.json();

  if (!res.ok) {
    addMsg(`❌ ${data.error}`);
    termLine(`Error: ${data.error}`, "#f55");
    startBtn.disabled = false;
    startBtn.textContent = "▶ Start Execution";
  }
});

// ── Manual shell input ────────────────────────────────────────────────────────
shellForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const cmd = shellInput.value.trim();
  if (!cmd) return;
  shellInput.value = "";

  termLine(`$ ${cmd}`, "#aaa");

  const res  = await fetch("/api/shell", {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ cmd }),
  });
  const data = await res.json();
  const color = data.returncode === 0 ? "#0f0" : "#f55";
  data.output.split("\n").forEach(line => {
    const d = document.createElement("div");
    d.className = "term-line";
    d.style.color = color;
    d.textContent = `  ${line}`;
    terminalLog.appendChild(d);
  });
  terminalLog.scrollTop = terminalLog.scrollHeight;
});

// ── Chatbot input ─────────────────────────────────────────────────────────────
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  chatInput.value = "";
  if (text) handleUserMessage(text);
});

async function handleUserMessage(text) {
  addMsg(text, "user");
  const lower = text.toLowerCase();

  if (!connected) {
    addMsg("Please connect to a GitHub repository first using the panel on the left.");
    return;
  }

  if (["help", "badges", "list"].includes(lower)) { renderAllBadges(); return; }
  if (["hi", "hello", "hey"].includes(lower)) {
    addMsg("Hey! Tell me which badge you want to unlock, or type <strong>help</strong> to see them all.");
    return;
  }

  // GitHub username lookup (short alphanumeric slug)
  if (/^@?[a-zA-Z0-9_-]{1,39}$/.test(text) && dataLoaded && badgesData[text.replace(/^@/, "")]) {
    renderUserBadges(text.replace(/^@/, ""));
    return;
  }

  // Treat as badge goal → call /api/plan
  addMsg("🤔 Planning the steps…");
  const res  = await fetch("/api/plan", {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ goal: text }),
  });
  const data = await res.json();
  if (!res.ok) { addMsg(`❌ ${data.error}`); return; }

  pendingBadge = data.badge_id;
  const stepsHtml = data.steps.map(s => `<div style="margin:3px 0">${s}</div>`).join("");
  addMsg(
    `Here's the plan to unlock <strong>${pendingBadge.replace(/_/g, " ")}</strong>:<br><br>` +
    stepsHtml +
    `<br>Click <strong>▶ Start Execution</strong> on the left when ready! 🚀`
  );
  startBtn.disabled = false;
}

// ── Badge data ────────────────────────────────────────────────────────────────
async function loadBadgeData() {
  try {
    const [dr, br] = await Promise.all([
      fetch(`${rawBase}/badge-definitions.json?t=${Date.now()}`),
      fetch(`${rawBase}/badges.json?t=${Date.now()}`),
    ]);
    definitions = await dr.json();
    badgesData  = await br.json();
    dataLoaded  = true;
  } catch (e) { console.warn("Badge data not loaded:", e); }
}

function renderAllBadges() {
  if (!dataLoaded) { addMsg("Badge data not loaded yet. Try again in a moment."); return; }
  addMsg("Here are all the badges you can unlock:");
  addBadgeList(definitions.map(d => `${d.emoji} <strong>${d.name}</strong> — ${d.description}`));
  addMsg("Tell me which one you want and I'll plan it out for you!");
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
