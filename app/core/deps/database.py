"""Database client and initialization."""

from functools import cache
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import Settings
from app.core.deps.settings import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@cache
def create_motor_client(settings: Settings) -> AsyncIOMotorClient:
    """
    Create and cache a MongoDB client - one per process.

    Args:
        settings: Application settings

    Returns:
        Cached MongoDB client
    """
    logger.info("creating_mongodb_client", url=settings.mongo_url)
    return AsyncIOMotorClient(settings.mongo_url)


async def init_database() -> AsyncIOMotorClient:
    """
    Initialize database connection and Beanie models.
    Should be called once during application startup.
    """
    settings = get_settings()
    client = create_motor_client(settings)

    from app.journals.db.models import Journal
    from app.journals.db.tag_model import Tag
    from app.auth.db.models import User, RefreshToken
    from app.memory.db.models import UserModel
    from app.chat.db.models import Chat
    from app.ai.db.models import LLMProvider
    from app.feedback.db.models import Feedback

    logger.info("initializing_beanie", database=settings.database_name)
    await init_beanie(
        database=client[settings.database_name],
        document_models=[Journal, Tag, User, RefreshToken, UserModel, Chat, LLMProvider, Feedback]
    )
    logger.info("beanie_initialized")

    return client


async def get_client() -> AsyncIOMotorClient:
    """
    Get the cached MongoDB client.
    
    Returns:
        MongoDB client
    """
    settings = get_settings()
    return create_motor_client(settings)
