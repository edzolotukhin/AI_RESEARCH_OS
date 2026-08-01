"""Uvicorn deployment entry point."""

from __future__ import annotations

from api.app import create_fastapi_app


def create_app():
    return create_fastapi_app()
