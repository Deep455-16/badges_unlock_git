"""
unlock_badges.py
------------------------------------------------------------------
Backend for the "Badge Bot" chatbot.

Triggered by the GitHub Actions workflow on every pull_request event
(opened + closed). It:
  1. Reads the PR payload GitHub Actions gives us.
  2. Tracks the author's PR history on this repo.
  3. Compares that history against data/badge-definitions.json.
  4. Unlocks any newly-earned badges into data/badges.json.
  5. Posts a friendly chatbot-style comment on the PR announcing
     any new badges.

The workflow file commits data/badges.json back to the repo after
this script runs, which is what the frontend chatbot reads from.
------------------------------------------------------------------
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
BADGES_PATH = os.path.join(DATA_DIR, "badges.json")
DEFINITIONS_PATH = os.path.join(DATA_DIR, "badge-definitions.json")

GITHUB_API = "https://api.github.com"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def post_pr_comment(owner, repo, pr_number, body, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.post(url, headers=headers, json={"body": body}, timeout=30)
    resp.raise_for_status()


def main():
    token = os.environ.get("GITHUB_TOKEN")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo_full = os.environ.get("REPO")  # "owner/repo"

    if not token or not event_path or not repo_full:
        print("Missing required env vars (GITHUB_TOKEN, GITHUB_EVENT_PATH, REPO).", file=sys.stderr)
        sys.exit(1)

    owner, repo = repo_full.split("/")

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    pr = event.get("pull_request")
    if not pr:
        print("No pull_request in event payload, nothing to do.")
        return

    username = pr["user"]["login"]
    action = event.get("action")
    is_merged = action == "closed" and pr.get("merged") is True
    is_opened = action == "opened"

    print(f"Event: {action} | PR #{pr['number']} | author: {username} | merged: {pr.get('merged')}")

    definitions = load_json(DEFINITIONS_PATH, [])
    badges_data = load_json(BADGES_PATH, {})

    user_record = badges_data.setdefault(
        username, {"badges": [], "prOpenedCount": 0, "prMergedCount": 0}
    )
    already_unlocked = {b["id"] for b in user_record["badges"]}
    newly_unlocked = []

    # --- Update running counters -------------------------------------------------
    if is_opened:
        user_record["prOpenedCount"] += 1
    if is_merged:
        user_record["prMergedCount"] += 1

    # --- Pull the PR's labels (only relevant once merged) ------------------------
    labels = [label["name"].lower() for label in pr.get("labels", [])]

    # --- Evaluate every badge definition against current state -------------------
    for definition in definitions:
        badge_id = definition["id"]
        if badge_id in already_unlocked:
            continue

        earned = False
        badge_type = definition["type"]

        if badge_type == "pr_opened_count":
            earned = user_record["prOpenedCount"] >= definition["threshold"]

        elif badge_type == "pr_merged_count":
            earned = is_merged and user_record["prMergedCount"] >= definition["threshold"]

        elif badge_type == "label_merged":
            earned = is_merged and definition["label"].lower() in labels

        elif badge_type == "speed_merge":
            if is_merged and pr.get("merged_at"):
                opened_at = parse_iso(pr["created_at"])
                merged_at = parse_iso(pr["merged_at"])
                elapsed_seconds = (merged_at - opened_at).total_seconds()
                earned = 0 < elapsed_seconds <= definition["seconds"]

        else:
            print(f"Unknown badge type: {badge_type}", file=sys.stderr)

        if earned:
            record = {
                "id": badge_id,
                "unlockedAt": datetime.now(timezone.utc).isoformat(),
                "prNumber": pr["number"],
            }
            user_record["badges"].append(record)
            already_unlocked.add(badge_id)
            newly_unlocked.append(definition)

    # --- Save updated badge data --------------------------------------------------
    save_json(BADGES_PATH, badges_data)
    unlocked_ids = ", ".join(b["id"] for b in newly_unlocked) or "none"
    print(f"Saved badges.json. New badges this run: {unlocked_ids}")

    # --- Comment on the PR like a chatbot announcing the unlock -------------------
    if newly_unlocked:
        lines = [f"- {b['emoji']} **{b['name']}** — {b['description']}" for b in newly_unlocked]
        plural = "a new badge" if len(newly_unlocked) == 1 else "new badges"
        body = "\n".join(
            [
                "### 🤖 Badge Bot",
                "",
                f"Hey @{username}, congrats! You just unlocked {plural}:",
                "",
                *lines,
                "",
                "Check your full badge collection in the chatbot on the repo's GitHub Pages site.",
            ]
        )
        post_pr_comment(owner, repo, pr["number"], body, token)
        print("Posted badge announcement comment.")
    else:
        print("No new badges unlocked this run.")


if __name__ == "__main__":
    main()
