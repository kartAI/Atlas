import psycopg
from psycopg_pool import AsyncConnectionPool
import ssl
from psycopg.rows import dict_row
from config import DATABASE_URL

pool = None

# Creates a function to connect to the pgSQL database.
# SSL context is handled by psycopg when using "?ssl=require".
async def connect_db():
    global pool
    conninfo = f"{DATABASE_URL}?sslmode=require"
    pool = AsyncConnectionPool(conninfo, kwargs={"row_factory": dict_row,}, open=False)
    await pool.open()

# Creates a function to disconnect from the pgSQL database.
async def disconnect_db():
    global pool
    if pool:
        await pool.close()


# Creates a function to execute a query against the database. Psycopg method prevent SQL Injection.
# Params optional. If provided, psycopg will safely inject them into the query.
async def query(sql, params=None):
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()