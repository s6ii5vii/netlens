# NetLens

AI-powered network diagnostics for unreliable internet environments.

## Overview

NetLens is a local-first AI-powered network assistant designed for low-quality internet environments. It helps people understand whether their internet connection is ready for real work by analyzing connection health, explaining issues in plain language, recommending practical fixes, and predicting whether common tasks like video calls or uploads will work right now.

The app pairs a lightweight local FastAPI agent with a premium dark dashboard. The backend runs diagnostics from the user's machine, while the frontend turns raw network signals into clear, useful guidance.

## Features

- Live diagnostics from a local agent
- Network health score
- Latency, packet loss, DNS timing, and download estimate
- AI-style recommendations with guided fixes
- Task readiness checker for calls, uploads, streaming, messaging, and more
- History view with recent scans and connection trends
- Premium dashboard built with plain HTML, CSS, and JavaScript

## How It Works

1. The local FastAPI agent runs network diagnostics from the user's device.
2. The frontend displays the latest score, metrics, recommendations, task readiness, and history.
3. A rule engine turns latency, packet loss, DNS timing, and estimated bandwidth into fix recommendations and task predictions.
4. SQLite stores recent diagnostic runs so the dashboard can show connection history over time.

## Tech Stack

- FastAPI
- Python
- HTML/CSS/JavaScript
- SQLite

## Local Setup

NetLens works best when the local NetLens Agent is running.

```bat
git clone <your-repo-url>
cd netlens
python -m venv venv
.\venv\Scripts\activate
pip install -r backend/requirements.txt
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open:

```text
frontend/index.html
```

You can also start the backend on Windows with:

```bat
run_agent.bat
```

## Hackathon Note

Built for the LUMA Hackathon.
