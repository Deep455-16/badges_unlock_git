import os
import json
import base64
import queue
import threading
import subprocess
import time
import uuid
import requests
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__, static_folder="../frontend", static_url_path="/")

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
class BotSession:
    def __init__(self):
        self.log_queue    = queue.Queue()
        self.confirm_queue= queue.Queue()
        self.is_running   = False
        self.worker_thread= None
        self.repo_url     = ""
        self.pat          = ""
        self.owner        = ""
        self.repo         = ""
        self.branch       = "main"

session = BotSession()

# ─────────────────────────────────────────────────────────────────────────────
# Badge definitions
# ─────────────────────────────────────────────────────────────────────────────
BADGE_MAP = {
    "first_pr":          {"label": None,            "commit": "feat: first contribution via Badge Bot",         "title": "Badge Bot: First Contribution",  "pr_body": "First PR to unlock the 🎉 First Contribution badge!"},
    "getting_started":   {"label": None,            "commit": "feat: contribution toward Getting Started",      "title": "Badge Bot: Getting Started",      "pr_body": "Working toward 3 merged PRs 🔥 Getting Started badge!"},
    "power_contributor": {"label": None,            "commit": "feat: contribution toward Power Contributor",    "title": "Badge Bot: Power Contributor",    "pr_body": "Working toward 10 merged PRs 🚀 Power Contributor badge!"},
    "bug_hunter":        {"label": "bug",           "commit": "fix: bug fix contribution via Badge Bot",        "title": "Badge Bot: Bug Hunter Fix",       "pr_body": "Bug fix PR to unlock the 🐛 Bug Hunter badge!"},
    "feature_builder":   {"label": "feature",       "commit": "feat: new feature contribution via Badge Bot",   "title": "Badge Bot: Feature Builder",      "pr_body": "New feature PR to unlock the ✨ Feature Builder badge!"},
    "docs_hero":         {"label": "documentation", "commit": "docs: documentation update via Badge Bot",       "title": "Badge Bot: Docs Hero",            "pr_body": "Documentation PR to unlock the 📚 Docs Hero badge!"},
    "quick_merge":       {"label": None,            "commit": "feat: quick contribution via Badge Bot",         "title": "Badge Bot: Quick Merge",          "pr_body": "Quick PR to merge within 1 hour ⚡ Quick Merge badge!"},
}
DEFAULT_BADGE = {"label": None, "commit": "feat: badge bot contribution", "title": "Badge Bot: Contribution", "pr_body": "Automated PR by Badge Bot."}

def broadcast(msg_type, content, action=None):
    msg = {"type": msg_type, "content": content}
    if action:
        msg["action"] = action
    session.log_queue.put(msg)

# ─────────────────────────────────────────────────────────────────────────────
# GitHub REST API helpers (no git CLI – no push auth issues)
# ─────────────────────────────────────────────────────────────────────────────
def gh_headers(pat):
    return {
        "Authorization": f"Bearer {pat}",
        "Accept":        "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def gh_get(pat, path):
    r = requests.get(f"https://api.github.com{path}", headers=gh_headers(pat), timeout=20)
    r.raise_for_status()
    return r.json()

def gh_post(pat, path, body):
    r = requests.post(f"https://api.github.com{path}", headers=gh_headers(pat), json=body, timeout=20)
    r.raise_for_status()
    return r.json()

def gh_put(pat, path, body):
    r = requests.put(f"https://api.github.com{path}", headers=gh_headers(pat), json=body, timeout=20)
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────────────────────────────────────────
# Worker: uses GitHub Contents API — zero local git, zero push errors
# ─────────────────────────────────────────────────────────────────────────────
def run_api_operations(pat, owner, repo, default_branch, target_badge):
    badge_info  = BADGE_MAP.get(target_badge, DEFAULT_BADGE)
    branch_name = f"badge-bot-{uuid.uuid4().hex[:8]}"
    file_path   = "BADGE_BOT_LOG.md"

    try:
        # ── 1. Get latest commit SHA on default branch ─────────────────────
        broadcast("log", f"📡 Fetching latest commit on '{default_branch}'…")
        ref_data   = gh_get(pat, f"/repos/{owner}/{repo}/git/refs/heads/{default_branch}")
        base_sha   = ref_data["object"]["sha"]
        broadcast("log", f"✅ Base commit: {base_sha[:7]}")

        # ── 2. Get tree SHA of that commit ─────────────────────────────────
        commit_data = gh_get(pat, f"/repos/{owner}/{repo}/git/commits/{base_sha}")
        base_tree   = commit_data["tree"]["sha"]

        # ── 3. Get existing file SHA (if any) so we can append ─────────────
        existing_content = ""
        existing_sha     = None
        try:
            file_data = gh_get(pat, f"/repos/{owner}/{repo}/contents/{file_path}?ref={default_branch}")
            existing_content = base64.b64decode(file_data["content"]).decode("utf-8")
            existing_sha     = file_data["sha"]
        except Exception:
            pass  # File doesn't exist yet — will create fresh

        # ── 4. Stage: build new file content ───────────────────────────────
        broadcast("confirm", f"Ready to stage a new BADGE_BOT_LOG.md entry. Proceed?", "stage")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at staging.")
            return

        ts           = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        new_content  = existing_content + (
            f"\n## Badge Bot Entry — {ts}\n"
            f"- **Goal:** `{target_badge}`\n"
            f"- **Branch:** `{branch_name}`\n"
        )
        broadcast("log", f"📝 New log entry prepared for goal: {target_badge}")

        # ── 5. Commit ──────────────────────────────────────────────────────
        broadcast("confirm", f"Ready to commit: \"{badge_info['commit']}\". Proceed?", "commit")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at commit.")
            return

        broadcast("log", "💾 Creating blob…")
        blob = gh_post(pat, f"/repos/{owner}/{repo}/git/blobs", {
            "content":  new_content,
            "encoding": "utf-8",
        })

        broadcast("log", "🌳 Creating tree…")
        tree = gh_post(pat, f"/repos/{owner}/{repo}/git/trees", {
            "base_tree": base_tree,
            "tree": [{"path": file_path, "mode": "100644", "type": "blob", "sha": blob["sha"]}],
        })

        broadcast("log", f"✍️  Committing: {badge_info['commit']}")
        commit = gh_post(pat, f"/repos/{owner}/{repo}/git/commits", {
            "message": badge_info["commit"],
            "tree":    tree["sha"],
            "parents": [base_sha],
        })
        broadcast("log", f"✅ Commit created: {commit['sha'][:7]}")

        # ── 6. Push: create the new branch pointing at the commit ──────────
        broadcast("confirm", f"Ready to create branch '{branch_name}' on GitHub. Proceed?", "push")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted before branch creation.")
            return

        gh_post(pat, f"/repos/{owner}/{repo}/git/refs", {
            "ref": f"refs/heads/{branch_name}",
            "sha": commit["sha"],
        })
        broadcast("log", f"✅ Branch '{branch_name}' pushed to GitHub.")

        # ── 7. Open PR ─────────────────────────────────────────────────────
        broadcast("confirm", f"Ready to open Pull Request: \"{badge_info['title']}\". Proceed?", "pr")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted before PR creation.")
            return

        broadcast("log", "🔗 Opening Pull Request via GitHub API…")
        pr = gh_post(pat, f"/repos/{owner}/{repo}/pulls", {
            "title": badge_info["title"],
            "head":  branch_name,
            "base":  default_branch,
            "body":  badge_info["pr_body"],
        })
        pr_url    = pr["html_url"]
        pr_number = pr["number"]
        broadcast("log", f"✅ PR #{pr_number} opened: {pr_url}")

        # ── 8. Add label if required ────────────────────────────────────────
        lbl = badge_info.get("label")
        if lbl:
            try:
                gh_post(pat, f"/repos/{owner}/{repo}/issues/{pr_number}/labels", {"labels": [lbl]})
                broadcast("log", f"🏷️  Label '{lbl}' added to PR.")
            except Exception:
                broadcast("log", f"⚠️  Could not add label '{lbl}' (label may not exist in repo — create it on GitHub).")

        broadcast("done",
            f"🎉 All done! PR #{pr_number} is live at {pr_url}\n"
            "GitHub Actions will run and unlock your badge. "
            "Type your GitHub username in the chatbot to check progress.")

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body   = exc.response.text[:400] if exc.response is not None else ""
        broadcast("error", f"GitHub API error {status}:\n{body}")
    except Exception as exc:
        broadcast("error", f"Unexpected error: {exc}")
    finally:
        session.is_running = False

# ─────────────────────────────────────────────────────────────────────────────
# API: run a manual shell command (git or otherwise) from the terminal input
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/shell", methods=["POST"])
def shell_cmd():
    data = request.json or {}
    cmd  = data.get("cmd", "").strip()
    cwd  = data.get("cwd", None)
    if not cmd:
        return jsonify({"error": "No command provided."}), 400

    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        return jsonify({"output": output or "(no output)", "returncode": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Command timed out after 30s.", "returncode": -1})
    except Exception as exc:
        return jsonify({"output": str(exc), "returncode": -1})

# ─────────────────────────────────────────────────────────────────────────────
# Static file serving
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("../frontend", path)

# ─────────────────────────────────────────────────────────────────────────────
# API: Connect
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/connect", methods=["POST"])
def connect_bot():
    data    = request.json or {}
    repo_url= data.get("repo_url", "").strip()
    pat     = data.get("pat", "").strip()

    if not repo_url or not pat:
        return jsonify({"error": "Repo URL and PAT are required."}), 400

    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return jsonify({"error": "Invalid repo URL."}), 400

    repo  = parts[-1].replace(".git", "")
    owner = parts[-2]

    try:
        repo_json = gh_get(pat, f"/repos/{owner}/{repo}")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        return jsonify({"error": f"Cannot access repo (HTTP {status}). Check URL & PAT scope (needs 'repo')."}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    # Check push permission
    perms = repo_json.get("permissions", {})
    if not perms.get("push", False):
        return jsonify({"error": "Your PAT doesn't have write/push access to this repo. Ensure it has the 'repo' scope."}), 403

    session.repo_url = repo_url
    session.pat      = pat
    session.owner    = owner
    session.repo     = repo
    session.branch   = repo_json.get("default_branch", "main")

    return jsonify({
        "owner":       owner,
        "repo":        repo,
        "branch":      session.branch,
        "description": repo_json.get("description", ""),
    })

# ─────────────────────────────────────────────────────────────────────────────
# API: Plan
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/plan", methods=["POST"])
def plan():
    data  = request.json or {}
    goal  = data.get("goal", "").lower()

    badge_id = "first_pr"
    if any(k in goal for k in ["bug", "fix", "hunter"]):
        badge_id = "bug_hunter"
    elif any(k in goal for k in ["feature", "builder"]):
        badge_id = "feature_builder"
    elif any(k in goal for k in ["doc", "documentation", "hero"]):
        badge_id = "docs_hero"
    elif any(k in goal for k in ["quick", "fast", "speed"]):
        badge_id = "quick_merge"
    elif any(k in goal for k in ["10", "power", "contributor"]):
        badge_id = "power_contributor"
    elif any(k in goal for k in ["3", "getting", "started"]):
        badge_id = "getting_started"

    info      = BADGE_MAP.get(badge_id, DEFAULT_BADGE)
    lbl_note  = f" (adds label `{info['label']}`)" if info["label"] else ""
    steps = [
        f"1️⃣  Fetch latest commit SHA on branch `{session.branch}`",
        f"2️⃣  Prepare BADGE_BOT_LOG.md entry for goal `{badge_id}`",
        f"3️⃣  Stage: create a blob with updated file",
        f"4️⃣  Commit via GitHub API: `{info['commit']}`",
        f"5️⃣  Create branch `badge-bot-<uid>` pointing at that commit",
        f"6️⃣  Open Pull Request: \"{info['title']}\"{lbl_note}",
        f"7️⃣  GitHub Actions runs → badge unlocked 🏅",
    ]

    return jsonify({"badge_id": badge_id, "steps": steps})

# ─────────────────────────────────────────────────────────────────────────────
# API: Start
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/start", methods=["POST"])
def start_bot():
    if session.is_running:
        return jsonify({"error": "A session is already running."}), 400
    if not session.pat or not session.owner:
        return jsonify({"error": "Please connect first."}), 400

    data         = request.json or {}
    target_badge = data.get("target_badge", "first_pr")

    while not session.log_queue.empty():
        try: session.log_queue.get_nowait()
        except queue.Empty: break
    while not session.confirm_queue.empty():
        try: session.confirm_queue.get_nowait()
        except queue.Empty: break

    session.is_running    = True
    session.worker_thread = threading.Thread(
        target=run_api_operations,
        args=(session.pat, session.owner, session.repo, session.branch, target_badge),
        daemon=True,
    )
    session.worker_thread.start()
    return jsonify({"status": "started"})

# ─────────────────────────────────────────────────────────────────────────────
# API: Confirm
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/confirm", methods=["POST"])
def confirm_action():
    data   = request.json or {}
    answer = data.get("answer")
    if answer not in ("yes", "no"):
        return jsonify({"error": "answer must be 'yes' or 'no'"}), 400
    session.confirm_queue.put(answer)
    return jsonify({"status": "ok"})

# ─────────────────────────────────────────────────────────────────────────────
# API: SSE Stream
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/stream")
def stream():
    def event_stream():
        while True:
            try:
                msg = session.log_queue.get(timeout=1.0)
                yield f"data: {json.dumps(msg)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    return Response(
        event_stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
