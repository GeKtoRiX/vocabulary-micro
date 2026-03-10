"""Web entry point: starts the FastAPI/uvicorn server."""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.getenv("LEGACY_BACKEND_HOST", os.getenv("HOST", "127.0.0.1")),
        port=int(os.getenv("LEGACY_BACKEND_PORT", os.getenv("PORT", "8765"))),
        reload=False,
    )
