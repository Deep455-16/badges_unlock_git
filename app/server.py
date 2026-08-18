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
        self.log_queue     = queue.Queue()
        self.confirm_queue = queue.Queue()
        self.is_running    = False
        self.worker_thread = None
        self.pat           = ""
        self.owner         = ""
        self.repo          = ""
        self.branch        = "main"

session = BotSession()

# ─────────────────────────────────────────────────────────────────────────────
# Badge definitions
# ─────────────────────────────────────────────────────────────────────────────
BADGE_MAP = {
    "first_pr":          {"label": None,            "commit": "feat: first contribution via Badge Bot",       "title": "Badge Bot: First Contribution",  "pr_body": "First PR to unlock the 🎉 First Contribution badge!"},
    "getting_started":   {"label": None,            "commit": "feat: contribution toward Getting Started",    "title": "Badge Bot: Getting Started",      "pr_body": "Working toward 3 merged PRs — 🔥 Getting Started badge!"},
    "power_contributor": {"label": None,            "commit": "feat: contribution toward Power Contributor",  "title": "Badge Bot: Power Contributor",    "pr_body": "Working toward 10 merged PRs — 🚀 Power Contributor badge!"},
    "bug_hunter":        {"label": "bug",           "commit": "fix: bug fix contribution via Badge Bot",      "title": "Badge Bot: Bug Hunter Fix",       "pr_body": "Bug fix PR to unlock the 🐛 Bug Hunter badge!"},
    "feature_builder":   {"label": "feature",       "commit": "feat: new feature contribution via Badge Bot", "title": "Badge Bot: Feature Builder",      "pr_body": "Feature PR to unlock the ✨ Feature Builder badge!"},
    "docs_hero":         {"label": "documentation", "commit": "docs: documentation update via Badge Bot",     "title": "Badge Bot: Docs Hero",            "pr_body": "Documentation PR to unlock the 📚 Docs Hero badge!"},
    "quick_merge":       {"label": None,            "commit": "feat: quick contribution via Badge Bot",       "title": "Badge Bot: Quick Merge",          "pr_body": "Quick PR — merge within 1 hour for the ⚡ Quick Merge badge!"},
}
DEFAULT_BADGE = {"label": None, "commit": "feat: badge bot contribution", "title": "Badge Bot: Contribution", "pr_body": "Automated PR by Badge Bot."}

# ─────────────────────────────────────────────────────────────────────────────
# GitHub API helpers
# ─────────────────────────────────────────────────────────────────────────────
def gh_headers(pat):
    return {
        "Authorization":       f"Bearer {pat}",
        "Accept":              "application/vnd.github.v3+json",
        "X-GitHub-Api-Version":"2022-11-28",
    }

def gh_get(pat, path, params=None):
    r = requests.get(
        f"https://api.github.com{path}",
        headers=gh_headers(pat), params=params, timeout=20
    )
    r.raise_for_status()
    return r.json()

def gh_post(pat, path, body):
    r = requests.post(
        f"https://api.github.com{path}",
        headers=gh_headers(pat), json=body, timeout=20
    )
    r.raise_for_status()
    return r.json()

def gh_put(pat, path, body):
    r = requests.put(
        f"https://api.github.com{path}",
        headers=gh_headers(pat), json=body, timeout=20
    )
    r.raise_for_status()
    return r.json()

def broadcast(msg_type, content, action=None):
    msg = {"type": msg_type, "content": content}
    if action:
        msg["action"] = action
    session.log_queue.put(msg)

# ─────────────────────────────────────────────────────────────────────────────
# Worker: GitHub Contents API — simpler, single-endpoint file creation/update
# ─────────────────────────────────────────────────────────────────────────────
def run_api_operations(pat, owner, repo, default_branch, target_badge):
    badge_info  = BADGE_MAP.get(target_badge, DEFAULT_BADGE)
    branch_name = f"badge-bot-{uuid.uuid4().hex[:8]}"
    file_path   = "BADGE_BOT_LOG.md"
    ts          = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    try:
        # ── 1. Get latest commit SHA from default branch ────────────────────
        broadcast("log", f"📡 Fetching latest commit on '{default_branch}'…")
        ref = gh_get(pat, f"/repos/{owner}/{repo}/git/refs/heads/{default_branch}")
        base_sha = ref["object"]["sha"]
        broadcast("log", f"✅ Base commit: {base_sha[:7]}")

        # ── 2. Get existing file SHA on default branch (for update) ─────────
        existing_content = ""
        existing_sha_on_default = None
        try:
            file_data = gh_get(pat, f"/repos/{owner}/{repo}/contents/{file_path}",
                               params={"ref": default_branch})
            raw = file_data.get("content", "")
            # GitHub wraps content in base64 with newlines
            existing_content = base64.b64decode(raw.replace("\n", "")).decode("utf-8")
            existing_sha_on_default = file_data["sha"]
        except requests.HTTPError:
            pass  # File doesn't exist yet — will be created fresh

        # ── 3. Stage ────────────────────────────────────────────────────────
        broadcast("confirm", "Ready to stage a BADGE_BOT_LOG.md entry. Proceed?", "stage")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at staging.")
            return

        new_content = (
            existing_content
            + f"\n## Badge Bot Entry — {ts}\n"
            + f"- **Goal:** `{target_badge}`\n"
            + f"- **Branch:** `{branch_name}`\n"
        )
        broadcast("log", f"📝 New entry staged for goal: {target_badge}")

        # ── 4. Commit ────────────────────────────────────────────────────────
        broadcast("confirm", f"Ready to commit: \"{badge_info['commit']}\". Proceed?", "commit")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted at commit.")
            return

        # Create branch first, then commit to it
        broadcast("log", f"🌿 Creating branch '{branch_name}' from {base_sha[:7]}…")
        gh_post(pat, f"/repos/{owner}/{repo}/git/refs", {
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha,
        })
        broadcast("log", f"✅ Branch '{branch_name}' created.")

        # Use Contents API to create/update the file on the new branch
        # If the file existed on default branch, we need its SHA on the new branch
        # (they share history, SHA is the same blob SHA)
        encoded_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
        put_body = {
            "message": badge_info["commit"],
            "content": encoded_content,
            "branch":  branch_name,
        }
        if existing_sha_on_default:
            put_body["sha"] = existing_sha_on_default  # required for updating existing file

        broadcast("log", f"✍️  Committing to '{branch_name}' via Contents API…")
        commit_result = gh_put(pat, f"/repos/{owner}/{repo}/contents/{file_path}", put_body)
        commit_sha = commit_result.get("commit", {}).get("sha", "")[:7]
        broadcast("log", f"✅ Committed: {badge_info['commit']} ({commit_sha})")

        # ── 5. Push confirmation (branch already pushed, just inform user) ──
        broadcast("confirm", f"Branch '{branch_name}' is on GitHub. Ready to open Pull Request. Proceed?", "push")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted before PR creation.")
            return

        # ── 6. Open PR ───────────────────────────────────────────────────────
        broadcast("confirm", f"Open PR: \"{badge_info['title']}\" → {default_branch}. Proceed?", "pr")
        if session.confirm_queue.get() != "yes":
            broadcast("log", "🚫 Aborted before opening PR.")
            return

        broadcast("log", "🔗 Opening Pull Request…")
        pr = gh_post(pat, f"/repos/{owner}/{repo}/pulls", {
            "title": badge_info["title"],
            "head":  branch_name,
            "base":  default_branch,
            "body":  badge_info["pr_body"],
        })
        pr_url    = pr["html_url"]
        pr_number = pr["number"]
        broadcast("log", f"✅ PR #{pr_number} opened: {pr_url}")

        # ── 7. Add label if required ─────────────────────────────────────────
        lbl = badge_info.get("label")
        if lbl:
            try:
                gh_post(pat, f"/repos/{owner}/{repo}/issues/{pr_number}/labels", {"labels": [lbl]})
                broadcast("log", f"🏷️  Label '{lbl}' added to PR.")
            except Exception:
                broadcast("log", f"⚠️  Could not add label '{lbl}'. Create it on GitHub first if needed.")

        broadcast("done",
            f"🎉 All done! PR #{pr_number}: {pr_url}\n"
            "GitHub Actions will run and unlock your badge.\n"
            "Type your GitHub username in the chatbot to check progress.")

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body   = ""
        msg    = ""
        try:
            body = exc.response.json().get("message", exc.response.text[:300])
        except Exception:
            body = exc.response.text[:300] if exc.response else ""

        if status == 403:
            msg = (
                f"GitHub API 403 — Token permission error:\n"
                f"  {body}\n\n"
                "Fix: Go to github.com/settings/tokens and ensure your token has:\n"
                "  • Classic PAT: needs full 'repo' scope (not just public_repo)\n"
                "  • Fine-grained PAT: Repository → Contents → Read and write\n"
                "                      Repository → Pull requests → Read and write\n"
                "Then re-generate and reconnect."
            )
        elif status == 422:
            msg = f"GitHub API 422 — Validation error: {body}"
        else:
            msg = f"GitHub API error {status}: {body}"

        broadcast("error", msg)
    except Exception as exc:
        broadcast("error", f"Unexpected error: {exc}")
    finally:
        session.is_running = False

# ─────────────────────────────────────────────────────────────────────────────
# API: Manual shell command
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/shell", methods=["POST"])
def shell_cmd():
    data = request.json or {}
    cmd  = data.get("cmd", "").strip()
    if not cmd:
        return jsonify({"error": "No command provided."}), 400
    try:
        result = subprocess.run(
            cmd, shell=True,
            capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        return jsonify({"output": output or "(no output)", "returncode": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Command timed out (30s).", "returncode": -1})
    except Exception as exc:
        return jsonify({"output": str(exc), "returncode": -1})

# ─────────────────────────────────────────────────────────────────────────────
# Static serving
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("../frontend", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("../frontend", path)

# ─────────────────────────────────────────────────────────────────────────────
# API: Connect — validate token AND test write capability upfront
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/connect", methods=["POST"])
def connect_bot():
    data     = request.json or {}
    repo_url = data.get("repo_url", "").strip()
    pat      = data.get("pat", "").strip()

    if not repo_url or not pat:
        return jsonify({"error": "Repo URL and PAT are required."}), 400

    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return jsonify({"error": "Invalid repo URL."}), 400

    repo  = parts[-1].replace(".git", "")
    owner = parts[-2]

    # ── Step 1: verify repo exists and token is authenticated ──────────────
    try:
        repo_json = gh_get(pat, f"/repos/{owner}/{repo}")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        if status == 401:
            return jsonify({"error": "Token is invalid or expired. Check your PAT."}), 400
        if status == 404:
            return jsonify({"error": f"Repo '{owner}/{repo}' not found, or token can't access it."}), 400
        return jsonify({"error": f"GitHub API error {status} when accessing repo."}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    default_branch = repo_json.get("default_branch", "main")

    # ── Step 2: Test write access by attempting to read git refs ────────────
    # (If refs endpoint returns 403, the token lacks Contents:read — can't write either)
    try:
        gh_get(pat, f"/repos/{owner}/{repo}/git/refs/heads/{default_branch}")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        if status == 403:
            return jsonify({"error": (
                "Your token cannot access the Git Data API for this repo.\n\n"
                "Fix your token at github.com/settings/tokens:\n"
                "  • Classic PAT → check the full 'repo' scope\n"
                "  • Fine-grained PAT → Repository permissions → Contents → Read and write"
            )}), 403
        # 409 = empty repo, that's OK
        if status != 409:
            return jsonify({"error": f"GitHub refs API error {status}."}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    # ── Store in session ─────────────────────────────────────────────────────
    session.pat    = pat
    session.owner  = owner
    session.repo   = repo
    session.branch = default_branch

    return jsonify({
        "owner":       owner,
        "repo":        repo,
        "branch":      default_branch,
        "description": repo_json.get("description", ""),
    })

# ─────────────────────────────────────────────────────────────────────────────
# API: Plan
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/plan", methods=["POST"])
def plan():
    data = request.json or {}
    goal = data.get("goal", "").lower()

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

    info     = BADGE_MAP.get(badge_id, DEFAULT_BADGE)
    lbl_note = f" + label `{info['label']}`" if info["label"] else ""
    steps    = [
        f"1️⃣  Fetch latest commit SHA on '{session.branch}'",
        f"2️⃣  Prepare new entry in BADGE_BOT_LOG.md",
        f"3️⃣  Create branch `badge-bot-<uid>` on GitHub",
        f"4️⃣  Commit via GitHub Contents API: `{info['commit']}`",
        f"5️⃣  Open Pull Request: \"{info['title']}\"{lbl_note}",
        f"6️⃣  GitHub Actions runs → badge unlocked 🏅",
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
