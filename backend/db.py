import asyncio
import logging
from psycopg_pool import AsyncConnectionPool
from config import DATABASE_URL
from psycopg.rows import dict_row

DB_RETRY_ATTEMPTS = 3

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None

async def _create_pool(url: str) -> AsyncConnectionPool | None:
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            pool = AsyncConnectionPool(
                conninfo=f"{url}?sslmode=require",
                open=False,
                min_size=1,
                max_size=10,
                kwargs={"row_factory": dict_row}
            )
            await pool.open()
            logger.info(f"Database pool initialised successfully.")
            return pool
        except Exception as e:
            if attempt == DB_RETRY_ATTEMPTS - 1:
                logger.error(f"Failed to initialise database pool after {DB_RETRY_ATTEMPTS} attempts: {e}")
                return None
            wait = 2 ** attempt
            logger.warning(f"Attempt {attempt + 1} to initialise pool failed. Retrying in {wait} seconds.")
            await asyncio.sleep(wait)
    return None
        
async def init_db_pool() -> bool:
    global _pool
    if not DATABASE_URL:
        logger.error("DATABASE_URL is not set in environment.")
        return False
    _pool = await _create_pool(DATABASE_URL)
    return _pool is not None

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Pool closed.")


def get_connection():
    if _pool is None:
        logger.error("Database connection pool is not initialized.")
        raise RuntimeError("pool is not initialized.")
    return _pool.connection()

async def query(sql, params=None):
    if _pool is None:
        raise RuntimeError("pool is not initialized.")
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()

