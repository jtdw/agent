"""Web-only launcher for the GIS Agent backend API.

This project no longer ships a desktop GUI. Start the Python API with:

    python app.py

Then start the React web client in another terminal:

    cd ui_next
    npm install
    npm run dev

Open http://127.0.0.1:5173 in the browser.
"""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    reload_enabled = str(os.getenv("GIS_AGENT_RELOAD", "")).strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run("api_server:app", host="127.0.0.1", port=8765, reload=reload_enabled)
