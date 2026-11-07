#!/usr/bin/env python3
"""Compatibility entry point. The application lives in the `app` package."""
import os

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))  # nosec B104
