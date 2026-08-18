# 🤖 Badge Bot — Real-Time GitHub Badge-Unlocking Chatbot

![Python](https://img.shields.io/badge/Python-3.x-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Enabled-green.svg)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automation-blueviolet.svg)
![Badges](https://img.shields.io/badge/Badges-Unlocked-orange.svg)

A local, real-time chatbot and terminal tool that allows you to earn and track GitHub contributor badges by automating Git operations (clone, stage, commit, push, PR) directly from a local interface. 

This project consists of:
1. **Local Backend (Flask):** Serves the UI, handles GitHub Personal Access Tokens securely in-memory, automates Git workflows, and streams execution logs to the frontend via Server-Sent Events (SSE).
2. **Local Frontend (HTML/JS):** A dual-pane interface featuring a terminal-style execution log with interactive step-by-step confirmations, and a chatbot for tracking unlocked badges.
3. **Remote Backend (GitHub Actions):** A workflow existing in your target repository that runs on every pull request, evaluates badge rules, updates `data/badges.json`, and comments on the PR when new badges are unlocked.

## 🏗️ Architecture

```
User (Local Browser)
       │
       ▼
Local Flask Server (app/server.py)
       │  ◄── 1. Accept URL & Token
       │  ◄── 2. Stream terminal logs (SSE)
       │  ◄── 3. Step-by-step user confirmations
       ▼
Local Git & GitHub API (Automated Operations)
       │
       ▼
Target GitHub Repository
       │
       ▼
GitHub Actions (scripts/unlock_badges.py)
       │  ◄── Evaluates definitions
       │  ◄── Updates data/badges.json
       │  ◄── Comments on PR
       ▼
Chatbot UI (Fetches data/badges.json live)
```

## 🔑 Setting up your GitHub Token (PAT)

The Badge Bot uses the GitHub API to create files, branches, and Pull Requests automatically. To do this, it needs a Personal Access Token (PAT) with write access to the repository.

### Option 1: Classic PAT (Recommended & Foolproof)
1. Go to **[GitHub Tokens (Classic)](https://github.com/settings/tokens)**.
2. Click **Generate new token** -> **Generate new token (classic)**.
3. Name it `Badge Bot` and set expiration (e.g., 30 days).
4. Under **Select scopes**, check the box next to **`repo`** (Full control of private repositories). This includes all necessary write permissions.
5. Scroll to the bottom and click **Generate token**. Copy the `ghp_...` token.

### Option 2: Fine-grained PAT
If you prefer fine-grained tokens, they default to Read-Only, so you MUST manually enable these:
1. Go to **[Fine-grained Tokens](https://github.com/settings/tokens?type=beta)**.
2. Under **Repository access**, select the repositories you want the bot to access.
3. Click to expand **Repository permissions**.
4. Set **Contents** to **Access: Read and write**.
5. Set **Pull requests** to **Access: Read and write**.
6. Generate and copy the token.

> **⚠️ Important Note on Repository Ownership:**
> Your token can only write to repositories where you have push access. If you are trying to earn badges on someone else's repository (like the main Badge Bot repo), **you must fork the repository first**, and then connect the Bot to your own fork's URL (e.g., `https://github.com/your-username/badges_unlock_git`). You cannot push branches to a repository you don't own!

## 🚀 Quick Start (Windows)

1. **Clone this repository** to your local machine.
2. **Install Dependencies:**
   Run `install.bat`. This will create a Python virtual environment and install the required packages (Flask, requests).
3. **Start the Bot:**
   Run `start_bot.bat`. This will start the Flask server and automatically open `http://localhost:5000` in your default browser.
4. **Execute Workflow:**
   - Enter your target GitHub Repository URL (e.g., `https://github.com/your-username/your-repo`).
   - Enter your **GitHub Personal Access Token (PAT)**. *Note: The token requires repo scopes. It is only kept in-memory for the current session and is never logged or saved to disk.*
   - Follow the interactive prompts in the terminal pane to confirm each Git step (Stage -> Commit -> Push -> PR).
5. **View Badges:**
   Once the PR is created and merged (if applicable), type your GitHub username in the chatbot pane to see your unlocked badges!

## 🔐 Security Notes

- **Token Handling:** The GitHub Personal Access Token is only transmitted to the local Flask server (`127.0.0.1`), stored temporarily in memory, and never logged, printed, or saved to the filesystem.
- **Local Execution:** All Git operations occur in a temporary directory on your local machine which is cleaned up after execution.

## 📦 Project Structure

```
app/
  server.py                           Flask backend + SSE stream + Git operations
  requirements.txt                    Python dependencies
frontend/
  index.html                          Main UI (Config, Terminal, Chatbot)
  style.css                           Styling (Light/Dark themes)
  chatbot.js                          Client logic (SSE, Confirmations, Badges)
scripts/
  unlock_badges.py                    GitHub Action backend logic
data/
  badge-definitions.json              Badge rules
  badges.json                         Scoreboard updated by GitHub Actions
.github/workflows/
  unlock-badges.yml                   GitHub Actions workflow file
install.bat                           Setup script for Windows
start_bot.bat                         Launch script for Windows
```

