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

