"""Internal NLP service entry point."""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.python_services.nlp_service.app:app",
        host=os.getenv("NLP_SERVICE_HOST", "127.0.0.1"),
        port=int(os.getenv("NLP_SERVICE_PORT", "8767")),
        reload=False,
    )
