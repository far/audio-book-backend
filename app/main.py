"""Entrypoint. Run with: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"""

from app.api.app import create_app

app = create_app()
