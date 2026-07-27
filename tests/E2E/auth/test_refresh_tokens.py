"""
End-to-end tests for Dual-Token Authentication with Refresh Tokens.
"""

import pytest
import jwt
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient

from app.core.config import Settings
from app.auth.db.models import User, RefreshToken


@pytest.mark.asyncio
async def test_login_sets_both_cookies(
    client: AsyncClient,
):
    """Test that login sets access_token and refresh_token cookies."""
    login_data = {"email": "unique_login_test@example.com", "password": "password123", "confirm_password": "password123"}
    reg_resp = await client.post("/api/v0/auth/register", json=login_data)
    assert reg_resp.status_code == 201

    response = await client.post(
        "/api/v0/auth/login",
        json={"email": login_data["email"], "password": login_data["password"]},
    )
    assert response.status_code == 200
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies
    assert "session_exists" in response.cookies


@pytest.mark.asyncio
async def test_refresh_token_rotation_success(
    client: AsyncClient,
    test_user: dict,
):
    """Test that POST /auth/refresh returns new access and refresh tokens."""
    initial_refresh = test_user["refresh_token"]
    assert initial_refresh is not None

    # Call refresh endpoint with Cookie header
    refresh_resp = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={initial_refresh}"},
    )
    assert refresh_resp.status_code == 200, f"Got status {refresh_resp.status_code}: {refresh_resp.text}"
    new_data = refresh_resp.json()
    assert "access_token" in new_data
    assert "refresh_token" in refresh_resp.cookies
    
    rotated_refresh = refresh_resp.cookies["refresh_token"]
    assert rotated_refresh != initial_refresh  # Refresh token must be rotated!


@pytest.mark.asyncio
async def test_reuse_attack_mitigation(
    client: AsyncClient,
    test_user: dict,
):
    """Test that reusing a revoked refresh token triggers family revocation."""
    r1 = test_user["refresh_token"]

    # 1. Refresh R1 -> get rotated token R2
    refresh1_resp = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={r1}"},
    )
    assert refresh1_resp.status_code == 200
    r2 = refresh1_resp.cookies["refresh_token"]

    # 2. An attacker attempts to reuse R1!
    reuse_resp = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={r1}"},
    )
    assert reuse_resp.status_code == 401  # Rejected!

    # 3. Now the legitimate user tries to use R2 -> should also fail because the family was revoked!
    r2_use_resp = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={r2}"},
    )
    assert r2_use_resp.status_code == 401  # Family revoked!


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(
    client: AsyncClient,
    test_user: dict,
):
    """Test that logging out invalidates the refresh token."""
    access_tok = test_user["access_token"]
    refresh_tok = test_user["refresh_token"]

    # 1. Logout
    logout_resp = await client.post(
        "/api/v0/auth/logout",
        headers={"Cookie": f"access_token={access_tok}; refresh_token={refresh_tok}"},
    )
    assert logout_resp.status_code == 200

    # 2. Attempt to refresh with the revoked refresh token -> fails
    refresh_resp = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_tok}"},
    )
    assert refresh_resp.status_code == 401
