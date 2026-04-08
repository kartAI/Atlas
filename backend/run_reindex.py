"""Force-reindex all documents from Azure Blob Storage.

Usage:
    cd backend
    python run_reindex.py
"""

import asyncio
import sys

from dotenv import load_dotenv
load_dotenv()

from db import init_db_pool, close_pool
from ingest_pipeline import run_pipeline


async def main():
    await init_db_pool()
    result = await run_pipeline(force=True)
    print(result)
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async requires SelectorEventLoop on Windows.
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        finally:
            loop.close()
    else:
        asyncio.run(main())
