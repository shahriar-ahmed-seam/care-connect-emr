"""Tests for the /health endpoint and the consistent error envelope."""

from __future__ import annotations

import pytest

@pytest.mark.asyncio
async def test_health_returns_ok(client) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "service" in body

@pytest.mark.asyncio
async def test_unknown_route_uses_error_envelope(client) -> None:
    resp = await client.get("/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()

    assert "error" in body
    assert body["error"]["code"] == "not-found"
    assert isinstance(body["error"]["message"], str)
