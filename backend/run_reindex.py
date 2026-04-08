import asyncio

asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from db import init_db_pool, close_pool
from ingest_pipeline import run_pipeline

async def main():
    ok = await init_db_pool()
    print("DB pool ready:", ok)

    result = await run_pipeline(force=True)
    print(result)

    await close_pool()

asyncio.run(main())