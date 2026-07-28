import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.auth.db.models import User
from app.journals.db.models import Journal
from app.chat.db.models import Chat
from app.memory.db.models import UserModel


import os

worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
TEST_DB_NAME = f"journaling_app_integration_test_{worker_id}" if worker_id != "master" else "journaling_app_integration_test"

DOCUMENT_MODELS = [User, Journal, Chat, UserModel]

COLLECTION_SPEC = [
    {
        "name": "users",
        "expected_indexes": {"_id_", "email_1", "created_at_1"},
    },
    {
        "name": "journals",
        "expected_indexes": {
            "_id_",
            "user_id_1",
            "created_at_1",
            "tags_1",
            "user_id_1_created_at_-1",
            "user_id_1_tags_1",
        },
    },
    {
        "name": "chats",
        "expected_indexes": {
            "_id_",
            "user_id_1",
            "user_id_1_created_at_-1",
        },
    },
    {
        "name": "user_models",
        "expected_indexes": {
            "_id_",
            "user_id_1",
        },
    },
]


@pytest_asyncio.fixture
async def initted_db(mongo_client: AsyncIOMotorClient):
    db = mongo_client[TEST_DB_NAME]
    await init_beanie(
        database=db,
        document_models=DOCUMENT_MODELS,
    )
    yield db
    await mongo_client.drop_database(TEST_DB_NAME)


@pytest.mark.asyncio
async def test_mongodb_reachable(mongo_client: AsyncIOMotorClient):
    result = await mongo_client.admin.command("ping")
    assert result.get("ok") == 1.0


@pytest.mark.asyncio
async def test_can_create_and_drop_test_database(mongo_client: AsyncIOMotorClient):
    db = mongo_client[TEST_DB_NAME]
    await db["probe"].insert_one({"_id": "probe", "value": 1})
    doc = await db["probe"].find_one({"_id": "probe"})
    assert doc is not None
    assert doc["value"] == 1
    await mongo_client.drop_database(TEST_DB_NAME)


@pytest.mark.asyncio
async def test_beanie_creates_expected_collections(initted_db):
    existing = await initted_db.list_collection_names()
    for spec in COLLECTION_SPEC:
        assert spec["name"] in existing, (
            f"Collection '{spec['name']}' not created by Beanie"
        )


@pytest.mark.asyncio
async def test_beanie_creates_expected_indexes(initted_db):
    for spec in COLLECTION_SPEC:
        indexes = await initted_db[spec["name"]].index_information()
        actual = set(indexes.keys())
        expected = spec["expected_indexes"]
        missing = expected - actual
        assert not missing, (
            f"Collection '{spec['name']}' missing indexes: {missing}. "
            f"Found: {actual}"
        )
