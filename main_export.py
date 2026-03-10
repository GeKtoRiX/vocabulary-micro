"""Internal export service entry point."""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "python_services.export_app:app",
        host=os.getenv("EXPORT_SERVICE_HOST", "127.0.0.1"),
        port=int(os.getenv("EXPORT_SERVICE_PORT", "8768")),
        reload=False,
    )
