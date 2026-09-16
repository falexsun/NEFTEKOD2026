#!/usr/bin/env python3
"""Compatibility launcher for the React operator console.

The former Streamlit dashboard lived in this module. The interface is now a
compiled React application served by the existing FastAPI service, keeping the
operator UI and the multi-agent runtime on one origin.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "dist" / "index.html"


def main() -> None:
    if not FRONTEND_INDEX.exists():
        raise SystemExit(
            "Интерфейс ещё не собран. Выполните: "
            "cd frontend && npm install && npm run build"
        )

    sys.path.insert(0, str(PROJECT_ROOT))
    port = int(os.environ.get("NEFTEKOD_PORT", "8000"))
    uvicorn.run("src.api.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
