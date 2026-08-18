/**
 * chatbot.js
 * ------------------------------------------------------------------
 * Handles terminal SSE streaming, confirmation inputs, theme toggling,
 * and the rule-based chatbot for badge lookup.
 * ------------------------------------------------------------------
 */

const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const repoLabel = document.getElementById("repo-label");
const themeToggle = document.getElementById("theme-toggle");

const configForm = document.getElementById("config-form");
const terminalLog = document.getElementById("terminal-log");
const confirmationPanel = document.getElementById("confirmation-panel");
const confirmationText = document.getElementById("confirmation-text");
const btnYes = document.getElementById("btn-yes");
const btnNo = document.getElementById("btn-no");

let repoOwner = "";
let repoName = "";
let repoBranch = "";
let rawBase = "";
let repoUrlStr = "";

let definitions = [];
let badgesData = {};
let dataLoaded = false;

// Theme Toggle
const savedTheme = localStorage.getItem("theme") || "dark";
document.body.setAttribute("data-theme", savedTheme);
updateThemeButton(savedTheme);

themeToggle.addEventListener("click", () => {
  const current = document.body.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.body.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  updateThemeButton(next);
});

function updateThemeButton(theme) {
  themeToggle.textContent = theme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode";
}

// Terminal Output
function appendTerminal(text, color = "#0f0") {
  const div = document.createElement("div");
  div.style.color = color;
  div.textContent = `> ${text}`;
  terminalLog.appendChild(div);
  terminalLog.scrollTop = terminalLog.scrollHeight;
}

// Config Submission
configForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const repoUrl = document.getElementById("repo-url").value;
  const pat = document.getElementById("github-pat").value;

  appendTerminal("Starting execution...", "#58a6ff");
  
  try {
    const res = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: repoUrl, pat })
    });
    
    const data = await res.json();
    if (!res.ok) {
      appendTerminal(`Error: ${data.error}`, "#f00");
      return;
    }

    repoOwner = data.owner;
    repoName = data.repo;
    repoBranch = data.branch || "main";
    rawBase = `https://raw.githubusercontent.com/${repoOwner}/${repoName}/${repoBranch}/data`;
    repoUrlStr = `https://github.com/${repoOwner}/${repoName}`;

    repoLabel.textContent = `${repoOwner}/${repoName}`;
    loadData();
    
    // Disable form
    document.getElementById("repo-url").disabled = true;
    document.getElementById("github-pat").disabled = true;
    document.getElementById("start-btn").disabled = true;

  } catch (err) {
    appendTerminal(`Error: ${err.message}`, "#f00");
  }
});

// SSE Connection
const eventSource = new EventSource("/api/stream");
eventSource.onmessage = function(event) {
  if (event.data === ": keepalive") return;
  try {
    const msg = JSON.parse(event.data);
    if (msg.type === "log") {
      appendTerminal(msg.content);
    } else if (msg.type === "error") {
      appendTerminal(msg.content, "#f00");
    } else if (msg.type === "done") {
      appendTerminal(msg.content, "#58a6ff");
      loadData(); // reload badges
    } else if (msg.type === "confirm") {
      appendTerminal(msg.content, "#ff0");
      confirmationText.textContent = msg.content;
      confirmationPanel.classList.remove("hidden");
    }
  } catch (e) {
    console.error("Failed to parse SSE data", e);
  }
};

// Confirmation Handling
async function sendConfirm(answer) {
  confirmationPanel.classList.add("hidden");
  appendTerminal(`User answered: ${answer}`);
  await fetch("/api/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer })
  });
}

btnYes.addEventListener("click", () => sendConfirm("yes"));
btnNo.addEventListener("click", () => sendConfirm("no"));


// Chatbot Logic
function addMessage(text, sender = "bot") {
  const el = document.createElement("div");
  el.className = `msg ${sender}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function addBadgeList(lines) {
  const el = document.createElement("div");
  el.className = "msg bot badge-list";
  el.innerHTML = lines.map((l) => `<div>${l}</div>`).join("");
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function loadData() {
  try {
    const [defsRes, badgesRes] = await Promise.all([
      fetch(`${rawBase}/badge-definitions.json`),
      fetch(`${rawBase}/badges.json`),
    ]);
    definitions = await defsRes.json();
    badgesData = await badgesRes.json();
    dataLoaded = true;
    addMessage(
      `Hi! I'm Badge Bot for ${repoOwner}/${repoName}. I just loaded the latest badge data. Type your GitHub username here to check your progress. Type "help" to see all available badges.`
    );
  } catch (err) {
    addMessage(
      `I couldn't load badge data from ${repoOwner}/${repoName}. Make sure it has data/badges.json on the default branch.`
    );
    console.error(err);
  }
}

function renderAllBadges() {
  const lines = definitions.map((d) => `${d.emoji} <strong>${d.name}</strong> — ${d.description}`);
  addMessage("Here are all the badges you can unlock:");
  addBadgeList(lines);
  addMessage(`Open a pull request on ${repoUrlStr} to start earning them.`);
}

function renderUserBadges(username) {
  const record = badgesData[username];

  if (!record || record.badges.length === 0) {
    addMessage(
      `I don't see any badges for "${username}" yet. Open a pull request on ${repoUrlStr} to unlock your first one!`
    );
    return;
  }

  const unlockedIds = new Set(record.badges.map((b) => b.id));
  const lines = definitions.map((d) => {
    const owned = unlockedIds.has(d.id);
    return owned
      ? `✅ ${d.emoji} <strong>${d.name}</strong>`
      : `🔒 <span style="color:#8b949e">${d.name}</span>`;
  });

  addMessage(
    `${username} has unlocked ${record.badges.length}/${definitions.length} badges (opened: ${record.prOpenedCount}, merged: ${record.prMergedCount}):`
  );
  addBadgeList(lines);
}

function handleInput(raw) {
  const text = raw.trim();
  if (!text) return;

  addMessage(text, "user");

  if (!dataLoaded) {
    addMessage("Please configure the bot with a repository URL first!");
    return;
  }

  const lower = text.toLowerCase();

  if (["help", "badges", "list"].includes(lower)) {
    renderAllBadges();
    return;
  }

  if (["hi", "hello", "hey"].includes(lower)) {
    addMessage("Hey! Type a GitHub username to check badge progress, or 'help' to list all badges.");
    return;
  }

  // Treat anything else as a GitHub username lookup.
  const username = text.replace(/^@/, "");
  renderUserBadges(username);
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const value = chatInput.value;
  chatInput.value = "";
  handleInput(value);
});
