"""Smoke / configuration checks for deployment (task 23.4).

Verifies deployment-time invariants from the design:

- TLS is enforced via an HSTS response header (Req 13.4).
- Secrets (notably the encryption key) are sourced only from the environment —
  the settings model bakes in no secret default, and no secret literal appears
  in source (Req 13.6, 21.3).
- The Render blueprint supplies all secrets as environment variables and commits
  none (Req 21.2, 21.3); the Vercel config builds the Next.js frontend (Req 21.1).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = Path(__file__).resolve().parents[1]

@pytest.mark.asyncio
async def test_hsts_header_present(client) -> None:
    """Every response carries an HSTS header so browsers require TLS (Req 13.4)."""
    response = await client.get("/health")
    assert response.status_code == 200
    hsts = response.headers.get("strict-transport-security")
    assert hsts is not None and "max-age=" in hsts

def test_encryption_key_has_no_source_default() -> None:
    """The encryption-key setting has no hard-coded default (Req 13.6, 21.3)."""
    field = Settings.model_fields["emr_encryption_key"]
    assert field.default is None

    assert Settings.model_fields["jwt_secret"].default is None
    assert Settings.model_fields["database_url"].default is None

def test_no_secret_literals_in_config_source() -> None:
    """config.py must not contain hard-coded secret values."""
    source = (_BACKEND / "app" / "core" / "config.py").read_text(encoding="utf-8")

    assert 'alias="EMR_ENCRYPTION_KEY"' in source
    assert "BEGIN PRIVATE KEY" not in source

def test_render_blueprint_uses_env_secrets() -> None:
    """render.yaml wires secrets via env vars and commits none (Req 21.2, 21.3)."""
    render = (_REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "EMR_ENCRYPTION_KEY" in render
    assert "DATABASE_URL" in render
    assert "alembic upgrade head" in render
    assert "app.worker" in render

    assert "sync: false" in render

def test_vercel_config_builds_nextjs() -> None:
    """vercel.json builds the Next.js frontend (Req 21.1)."""
    import json

    vercel = json.loads(
        (_REPO_ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8")
    )
    assert vercel.get("framework") == "nextjs"
