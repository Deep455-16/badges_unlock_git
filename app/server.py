import os
import json
import queue
import threading
import subprocess
import tempfile
import shutil
import time
import uuid
import requests
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__, static_folder="../frontend", static_url_path="/")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
class BotSession:
    def __init__(self):
        self.log_queue = queue.Queue()
        self.confirm_queue = queue.Queue()
        self.is_running = False
        self.worker_thread = None
        self.repo_url = ""
        self.pat = ""
        self.owner = ""
        self.repo = ""
        self.branch = "main"

session = BotSession()

# ---------------------------------------------------------------------------
# Badge definitions (kept in sync with data/badge-definitions.json)
# ---------------------------------------------------------------------------
BADGE_MAP = {
    "first_pr": {
        "label": None,
        "commit": "feat: first contribution via Badge Bot",
        "title": "Badge Bot: First Contribution",
        "pr_body": "This is my first PR — unlocking the 🎉 First Contribution badge!",
    },
    "getting_started": {
        "label": None,
        "commit": "feat: contribution towards Getting Started badge",
        "title": "Badge Bot: Getting Started",
        "pr_body": "Working towards 3 merged PRs to unlock the 🔥 Getting Started badge!",
    },
    "power_contributor": {
        "label": None,
        "commit": "feat: contribution towards Power Contributor badge",
        "title": "Badge Bot: Power Contributor",
        "pr_body": "Working towards 10 merged PRs to unlock the 🚀 Power Contributor badge!",
    },
    "bug_hunter": {
        "label": "bug",
        "commit": "fix: bug fix contribution via Badge Bot",
        "title": "Badge Bot: Bug Hunter Fix",
        "pr_body": "Bug fix PR to unlock the 🐛 Bug Hunter badge!",
    },
    "feature_builder": {
        "label": "feature",
        "commit": "feat: new feature contribution via Badge Bot",
        "title": "Badge Bot: Feature Builder",
        "pr_body": "New feature PR to unlock the ✨ Feature Builder badge!",
    },
    "docs_hero": {
        "label": "documentation",
        "commit": "docs: documentation update via Badge Bot",
        "title": "Badge Bot: Docs Hero",
        "pr_body": "Documentation PR to unlock the 📚 Docs Hero badge!",
    },
    "quick_merge": {
        "label": None,
        "commit": "feat: quick contribution via Badge Bot",
        "title": "Badge Bot: Quick Merge",
        "pr_body": "Quick PR aiming to be merged within 1 hour to unlock the ⚡ Quick Merge badge!",
    },
}

DEFAULT_BADGE_INFO = {
    "label": None,
    "commit": "feat: badge bot automated contribution",
    "title": "Badge Bot: Automated Contribution",
    "pr_body": "Automated PR created by Badge Bot.",
}

# ---------------------------------------------------------------------------
# Helper: broadcast a message to the SSE queue
# ---------------------------------------------------------------------------
def broadcast(msg_type, content, action=None):
    msg = {"type": msg_type, "content": content}
    if action:
        msg["action"] = action
    session.log_queue.put(msg)

# ---------------------------------------------------------------------------
# Core worker: runs git operations on a background thread
# ---------------------------------------------------------------------------
def run_git_operations(repo_url, pat, owner, repo, branch, target_badge):
    temp_dir = tempfile.mkdtemp(prefix="badge_bot_")
    branch_name = f"badge-bot-{uuid.uuid4().hex[:8]}"
    badge_info = BADGE_MAP.get(target_badge, DEFAULT_BADGE_INFO)

    try:
        # Build authenticated clone URL
        if not repo_url.startswith("https://"):
            broadcast("error", "Invalid repo URL — must start with https://")
            return

        auth_url = repo_url.rstrip("/")
        if auth_url.endswith(".git"):
            auth_url = auth_url[:-4]
        auth_url = auth_url.replace("https://", f"https://x-access-token:{pat}@") + ".git"

        # ── CLONE ──────────────────────────────────────────────────────────
        broadcast("log", f"📦 Cloning {owner}/{repo} …")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", auth_url, temp_dir],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            broadcast("error", f"Clone failed:\n{result.stderr}")
            return
        broadcast("log", "✅ Clone successful.")

        # ── NEW BRANCH ─────────────────────────────────────────────────────
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=temp_dir,
                       capture_output=True, text=True)
        broadcast("log", f"🌿 Created branch: {branch_name}")

        # ── WRITE FILE ─────────────────────────────────────────────────────
        log_file = os.path.join(temp_dir, "BADGE_BOT_LOG.md")
        ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n## Badge Bot Entry — {ts}\n")
            f.write(f"- **Goal:** `{target_badge}`\n")
            f.write(f"- **Branch:** `{branch_name}`\n")
        broadcast("log", f"📝 Updated BADGE_BOT_LOG.md  (goal: {target_badge})")

        # ── STAGE ──────────────────────────────────────────────────────────
        broadcast("confirm", "Ready to stage changes (git add). Proceed?", "stage")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at staging.")
            return
        subprocess.run(["git", "add", "BADGE_BOT_LOG.md"], cwd=temp_dir,
                       capture_output=True, text=True)
        broadcast("log", "✅ Changes staged.")

        # ── COMMIT ─────────────────────────────────────────────────────────
        broadcast("confirm", "Ready to commit (git commit). Proceed?", "commit")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at commit.")
            return
        subprocess.run(["git", "config", "user.name", "Badge Bot"], cwd=temp_dir)
        subprocess.run(["git", "config", "user.email", "badgebot@noreply.local"], cwd=temp_dir)
        result = subprocess.run(
            ["git", "commit", "-m", badge_info["commit"]],
            cwd=temp_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            broadcast("error", f"Commit failed:\n{result.stderr}")
            return
        broadcast("log", f"✅ Committed: {badge_info['commit']}")

        # ── PUSH ───────────────────────────────────────────────────────────
        broadcast("confirm", f"Ready to push branch '{branch_name}' to GitHub. Proceed?", "push")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at push.")
            return
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=temp_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            broadcast("error", f"Push failed:\n{result.stderr}")
            return
        broadcast("log", "✅ Branch pushed successfully.")

        # ── OPEN PR ────────────────────────────────────────────────────────
        broadcast("confirm", "Ready to open a Pull Request on GitHub. Proceed?", "pr")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted before opening PR.")
            return

        broadcast("log", "🔗 Opening Pull Request via GitHub API …")
        api_headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Try default branch first, fall back to master
        for base in [branch, "main", "master"]:
            pr_payload = {
                "title": badge_info["title"],
                "head": branch_name,
                "base": base,
                "body": badge_info["pr_body"],
            }
            resp = requests.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=api_headers, json=pr_payload, timeout=30
            )
            if resp.status_code == 201:
                pr_data = resp.json()
                pr_url = pr_data.get("html_url", "")

                # Add label if required
                lbl = badge_info.get("label")
                if lbl:
                    pr_number = pr_data.get("number")
                    requests.post(
                        f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/labels",
                        headers=api_headers, json={"labels": [lbl]}, timeout=30
                    )
                    broadcast("log", f"🏷️  Added label '{lbl}' to PR.")

                broadcast("log", f"🎉 Pull Request opened: {pr_url}")
                broadcast("done",
                    f"All done! PR is live at {pr_url}\n"
                    "Type your GitHub username in the chatbot to check your new badges.")
                return

        broadcast("error", f"Failed to open PR: {resp.status_code}\n{resp.text}")

    except Exception as exc:
        broadcast("error", f"Unexpected error: {exc}")
    finally:
        session.is_running = False
        shutil.rmtree(temp_dir, ignore_errors=True)

# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("../frontend", path)

# ---------------------------------------------------------------------------
# API: Connect — validate credentials + repo, store in session
# ---------------------------------------------------------------------------
@app.route("/api/connect", methods=["POST"])
def connect_bot():
    data = request.json or {}
    repo_url = data.get("repo_url", "").strip()
    pat = data.get("pat", "").strip()

    if not repo_url or not pat:
        return jsonify({"error": "Repo URL and PAT are required."}), 400

    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return jsonify({"error": "Invalid repo URL."}), 400

    repo = parts[-1].removesuffix(".git")
    owner = parts[-2]

    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=15)
    if resp.status_code != 200:
        return jsonify({"error": f"Cannot access repo (HTTP {resp.status_code}). Check URL & PAT."}), 400

    repo_json = resp.json()
    # Persist in session so /api/start doesn't need them re-submitted
    session.repo_url = repo_url
    session.pat = pat
    session.owner = owner
    session.repo = repo
    session.branch = repo_json.get("default_branch", "main")

    return jsonify({
        "owner": owner,
        "repo": repo,
        "branch": session.branch,
        "description": repo_json.get("description", ""),
    })

# ---------------------------------------------------------------------------
# API: Plan — given user's goal text, return the execution plan steps
# ---------------------------------------------------------------------------
@app.route("/api/plan", methods=["POST"])
def plan():
    data = request.json or {}
    goal = data.get("goal", "").lower()

    # Simple keyword matching to pick badge
    badge_id = "first_pr"  # default
    if any(k in goal for k in ["bug", "fix", "hunter"]):
        badge_id = "bug_hunter"
    elif any(k in goal for k in ["feature", "builder"]):
        badge_id = "feature_builder"
    elif any(k in goal for k in ["doc", "documentation", "hero"]):
        badge_id = "docs_hero"
    elif any(k in goal for k in ["quick", "fast", "speed", "merge"]):
        badge_id = "quick_merge"
    elif any(k in goal for k in ["10", "power", "contributor"]):
        badge_id = "power_contributor"
    elif any(k in goal for k in ["3", "getting", "started"]):
        badge_id = "getting_started"
    elif any(k in goal for k in ["first", "1", "initial", "begin"]):
        badge_id = "first_pr"

    info = BADGE_MAP.get(badge_id, DEFAULT_BADGE_INFO)
    label_note = f" (adds label: `{info['label']}`)" if info["label"] else ""

    steps = [
        f"1️⃣  Clone `{session.owner}/{session.repo}` to a temporary directory",
        f"2️⃣  Create a new branch `badge-bot-<uid>`",
        f"3️⃣  Append an entry to `BADGE_BOT_LOG.md`",
        f"4️⃣  Stage the change (`git add`)",
        f"5️⃣  Commit: `{info['commit']}`",
        f"6️⃣  Push branch to GitHub",
        f"7️⃣  Open Pull Request: \"{info['title']}\"{label_note}",
        f"8️⃣  GitHub Actions workflow runs → badge unlocked 🏅",
    ]

    return jsonify({"badge_id": badge_id, "steps": steps})

# ---------------------------------------------------------------------------
# API: Start — kick off the background git worker
# ---------------------------------------------------------------------------
@app.route("/api/start", methods=["POST"])
def start_bot():
    if session.is_running:
        return jsonify({"error": "A session is already running."}), 400

    if not session.pat or not session.owner:
        return jsonify({"error": "Please connect first via the Connect button."}), 400

    data = request.json or {}
    target_badge = data.get("target_badge", "first_pr")

    # Clear queues
    while not session.log_queue.empty():
        try:
            session.log_queue.get_nowait()
        except queue.Empty:
            break
    while not session.confirm_queue.empty():
        try:
            session.confirm_queue.get_nowait()
        except queue.Empty:
            break

    session.is_running = True
    session.worker_thread = threading.Thread(
        target=run_git_operations,
        args=(session.repo_url, session.pat, session.owner, session.repo, session.branch, target_badge),
        daemon=True,
    )
    session.worker_thread.start()
    return jsonify({"status": "started"})

# ---------------------------------------------------------------------------
# API: Confirm — send y/n to the blocked worker thread
# ---------------------------------------------------------------------------
@app.route("/api/confirm", methods=["POST"])
def confirm_action():
    data = request.json or {}
    answer = data.get("answer")
    if answer not in ("yes", "no"):
        return jsonify({"error": "answer must be 'yes' or 'no'"}), 400
    session.confirm_queue.put(answer)
    return jsonify({"status": "ok"})

# ---------------------------------------------------------------------------
# API: Stream — SSE endpoint
# ---------------------------------------------------------------------------
@app.route("/api/stream")
def stream():
    def event_stream():
        while True:
            try:
                msg = session.log_queue.get(timeout=1.0)
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
