from neo4j import AsyncGraphDatabase, AsyncDriver
from config import get_settings

_driver: AsyncDriver | None = None


def get_neo4j() -> AsyncDriver:
    global _driver
    if _driver is None:
        settings = get_settings()
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
    return _driver


async def close_neo4j() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
