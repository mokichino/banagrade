"""Application entry point for deployments that run `uvicorn app.main:app`."""

from main import app

__all__ = ["app"]
