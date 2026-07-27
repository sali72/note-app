import pytest
from httpx import AsyncClient
from app.auth.db.models import User, RefreshToken


@pytest.mark.asyncio
async def test_get_active_sessions_returns_current_device(
    client: AsyncClient, test_user: dict
):
    """Verify GET /auth/sessions returns active sessions with current device flagged."""
    # Login to create session
    response = await client.post(
        "/api/v0/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
    )
    assert response.status_code == 200

    refresh_token = response.cookies.get("refresh_token")
    access_token = response.cookies.get("access_token")
    assert refresh_token is not None

    # Request session list passing refresh_token cookie
    sessions_response = await client.get(
        "/api/v0/auth/sessions",
        headers={"Cookie": f"access_token={access_token}; refresh_token={refresh_token}"},
    )
    assert sessions_response.status_code == 200
    data = sessions_response.json()
    assert data["total_count"] >= 1
    
    current_session = next((s for s in data["sessions"] if s["is_current"]), None)
    assert current_session is not None
    assert current_session["browser"] == "Chrome"
    assert current_session["os"] == "macOS"


@pytest.mark.asyncio
async def test_revoke_specific_session(
    client: AsyncClient, test_user: dict
):
    """Verify revoking a specific session family revokes its token."""
    # Session 1 (Client A - Firefox)
    res_a = await client.post(
        "/api/v0/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"},
    )
    assert res_a.status_code == 200
    refresh_a = res_a.cookies.get("refresh_token")
    access_a = res_a.cookies.get("access_token")

    # Session 2 (Client B - Safari)
    res_b = await client.post(
        "/api/v0/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"},
    )
    assert res_b.status_code == 200
    refresh_b = res_b.cookies.get("refresh_token")
    access_b = res_b.cookies.get("access_token")

    # Get sessions list from Client B
    sessions_res = await client.get(
        "/api/v0/auth/sessions",
        headers={"Cookie": f"access_token={access_b}; refresh_token={refresh_b}"},
    )
    assert sessions_res.status_code == 200
    sessions = sessions_res.json()["sessions"]
    assert len(sessions) >= 2

    # Identify Client A session family_id
    client_a_session = next(s for s in sessions if not s["is_current"])
    family_a_id = client_a_session["family_id"]

    # Client B revokes Client A's session
    revoke_res = await client.delete(
        f"/api/v0/auth/sessions/{family_a_id}",
        headers={"Cookie": f"access_token={access_b}; refresh_token={refresh_b}"},
    )
    assert revoke_res.status_code == 200

    # Verify Client A can no longer refresh
    refresh_a_res = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_a}"},
    )
    assert refresh_a_res.status_code == 401


@pytest.mark.asyncio
async def test_revoke_all_other_sessions(
    client: AsyncClient, test_user: dict
):
    """Verify POST /auth/sessions/revoke-others revokes all sessions except the current one."""
    # Create Session A
    res_a = await client.post(
        "/api/v0/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"User-Agent": "Device A"},
    )
    refresh_a = res_a.cookies.get("refresh_token")

    # Create Session B (Current)
    res_b = await client.post(
        "/api/v0/auth/login",
        json={"email": test_user["email"], "password": test_user["password"]},
        headers={"User-Agent": "Device B"},
    )
    refresh_b = res_b.cookies.get("refresh_token")
    access_b = res_b.cookies.get("access_token")

    # Client B calls revoke-others
    revoke_others_res = await client.post(
        "/api/v0/auth/sessions/revoke-others",
        headers={"Cookie": f"access_token={access_b}; refresh_token={refresh_b}"},
    )
    assert revoke_others_res.status_code == 200

    # Session A refresh should fail
    ref_a_res = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_a}"},
    )
    assert ref_a_res.status_code == 401

    # Session B refresh should succeed
    ref_b_res = await client.post(
        "/api/v0/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_b}"},
    )
    assert ref_b_res.status_code == 200
