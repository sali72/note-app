"""
Pytest configuration and fixtures for E2E tests.

This module provides fixtures for setting up a test database,
test client, and authenticated users for end-to-end testing.
"""

import pytest
import pytest_asyncio
import asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.main import create_app
from app.core.config import Settings
from app.core.deps.settings import get_settings
from app.auth.api.config import AuthRoutes
from tests.config import AUTH_PREFIX
from app.auth.db.models import User, RefreshToken
from app.journals.db.models import Journal
from app.journals.db.tag_model import Tag
from app.memory.db.models import UserModel
from app.chat.db.models import Chat
from app.feedback.db.models import Feedback


@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    m = MonkeyPatch()
    yield m
    m.undo()


@pytest.fixture(scope="session", autouse=True)
def test_settings(monkeypatch_session) -> Settings:
    """
    Create test settings with a separate test database (worker-isolated if using xdist).
    
    Returns:
        Settings configured for testing
    """
    import os
    from app.core.deps.settings import get_settings
    from app.core.deps.database import create_motor_client
    
    # Clear the lru_cache on get_settings
    get_settings.cache_clear()
    create_motor_client.cache_clear()
    
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    database_name = f"journaling_app_test_{worker_id}" if worker_id != "master" else "journaling_app_test"

    # Set environment variables for testing
    monkeypatch_session.setenv("DATABASE_NAME", database_name)
    monkeypatch_session.setenv("ENVIRONMENT", "testing")
    monkeypatch_session.setenv("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
    monkeypatch_session.setenv("USE_MOCK_LLM", "true")
    
    test_settings_obj = Settings(
        mongo_url="mongodb://localhost:27017",
        database_name=database_name,
        environment="testing",
        jwt_secret_key="test-secret-key-for-testing-only",
        use_mock_llm=True,  # Always use mock LLM in tests to avoid API costs
    )
    
    return test_settings_obj


@pytest_asyncio.fixture(scope="function")
async def test_db_client(test_settings: Settings) -> AsyncGenerator[AsyncIOMotorClient, None]:
    """
    Create a MongoDB client for the test database.
    
    Clears motor cache per event loop and cleans up collection data after each test.
    
    Args:
        test_settings: Test settings fixture
        
    Yields:
        MongoDB client connected to test database
    """
    # Clear cached motor client to avoid cross-event-loop issues
    from app.core.deps.database import create_motor_client
    create_motor_client.cache_clear()

    # Reset rate limiter state to avoid interference between tests
    from app.core.rate_limit import limiter
    limiter.reset()
    
    client = AsyncIOMotorClient(test_settings.mongo_url)
    db = client[test_settings.database_name]
    
    from app.ai.db.models import LLMProvider

    # Initialize Beanie for current event loop
    await init_beanie(
        database=db,
        document_models=[User, RefreshToken, Journal, Tag, UserModel, Chat, LLMProvider, Feedback]
    )
    
    try:
        yield client
    finally:
        # Fast concurrent cleanup: wipe collection documents while retaining indexes
        collection_names = await db.list_collection_names()
        delete_tasks = [
            db[col].delete_many({})
            for col in collection_names
            if not col.startswith("system.")
        ]
        if delete_tasks:
            await asyncio.gather(*delete_tasks)
        client.close()


@pytest_asyncio.fixture
async def app(test_settings: Settings, test_db_client: AsyncIOMotorClient):
    """
    Create a FastAPI application instance for testing.
    
    Args:
        test_settings: Test settings fixture
        test_db_client: MongoDB client fixture (ensures DB is initialized)
        
    Returns:
        Configured FastAPI application
    """
    from app.core.deps.database import get_client
    from app.auth.config import AuthModuleConfig
    from app.auth.deps import get_auth_config
    
    # Create app using the standard create_app function
    app = create_app()
    
    # Override settings and database client dependencies
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    # Disable email verification in tests — users are auto-verified on register
    app.dependency_overrides[get_auth_config] = lambda: AuthModuleConfig(
        email_verification_required=False
    )
    
    # Override get_client to return our test client
    async def get_test_client():
        return test_db_client
    
    app.dependency_overrides[get_client] = get_test_client
    
    yield app
    
    # Clean up overrides
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an async HTTP client for testing API endpoints.
    
    Args:
        app: FastAPI application fixture
        
    Yields:
        Async HTTP client for making requests
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(client: AsyncClient) -> dict:
    """
    Create a test user and return user data with credentials.
    
    Args:
        client: HTTP client fixture
        
    Returns:
        Dictionary containing user email, password, and ID
    """
    user_data = {
        "email": "testuser@example.com",
        "password": "testpassword123",
        "confirm_password": "testpassword123"
    }
    
    # Register the user
    response = await client.post(f"{AUTH_PREFIX}{AuthRoutes.REGISTER}", json=user_data)
    assert response.status_code == 201
    
    # Login to get user ID
    login_response = await client.post(
        f"{AUTH_PREFIX}{AuthRoutes.LOGIN}",
        json={"email": user_data["email"], "password": user_data["password"]}
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    
    return {
        "email": user_data["email"],
        "password": user_data["password"],
        "user_id": login_data["user"]["id"],
        "access_token": login_data["access_token"],
        "refresh_token": login_response.cookies.get("refresh_token"),
    }


@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient, test_user: dict) -> AsyncClient:
    """
    Create an authenticated HTTP client with access_token and refresh_token cookies.
    """
    if test_user.get("access_token"):
        client.cookies.set("access_token", test_user["access_token"])
    if test_user.get("refresh_token"):
        client.cookies.set("refresh_token", test_user["refresh_token"])
    return client


@pytest_asyncio.fixture
async def another_test_user(client: AsyncClient) -> dict:
    """
    Create another test user for multi-user testing scenarios.
    
    Args:
        client: HTTP client fixture
        
    Returns:
        Dictionary containing user email, password, and ID
    """
    user_data = {
        "email": "anotheruser@example.com",
        "password": "anotherpassword123",
        "confirm_password": "anotherpassword123"
    }
    
    # Register the user
    response = await client.post(f"{AUTH_PREFIX}{AuthRoutes.REGISTER}", json=user_data)
    assert response.status_code == 201
    
    # Login to get user ID
    login_response = await client.post(
        f"{AUTH_PREFIX}{AuthRoutes.LOGIN}",
        json={"email": user_data["email"], "password": user_data["password"]}
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    
    return {
        "email": user_data["email"],
        "password": user_data["password"],
        "user_id": login_data["user"]["id"],
        "access_token": login_data["access_token"]
    }


@pytest_asyncio.fixture
async def admin_user(client: AsyncClient) -> dict:
    """Create an admin user for testing administrative routes."""
    user_data = {
        "email": "admin@example.com",
        "password": "adminpassword123",
        "confirm_password": "adminpassword123"
    }
    
    response = await client.post(f"{AUTH_PREFIX}{AuthRoutes.REGISTER}", json=user_data)
    assert response.status_code == 201
    
    user = await User.find_one({"email": user_data["email"]})
    user.role = "admin"
    await user.save()
    
    login_response = await client.post(
        f"{AUTH_PREFIX}{AuthRoutes.LOGIN}",
        json={"email": user_data["email"], "password": user_data["password"]}
    )
    assert login_response.status_code == 200
    login_data = login_response.json()
    
    return {
        "email": user_data["email"],
        "password": user_data["password"],
        "user_id": login_data["user"]["id"],
        "access_token": login_data["access_token"]
    }


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient, admin_user: dict) -> AsyncClient:
    """Create an authenticated HTTP client for an admin user."""
    client.cookies.set("access_token", admin_user["access_token"])
    return client
