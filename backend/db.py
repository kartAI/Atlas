import asyncpg
import ssl
from config import DATABASE_URL

pool = None

async def connect_db():
    global pool
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    pool = await asyncpg.create_pool(DATABASE_URL, ssl=ssl_context)
# Creates a function to connect to the pgSQL database.
# SSL context is created for secure connection to the database.
    
async def disconnect_db():
    global pool
    if pool:
        await pool.close()
# Creates a function to disconnect from the pgSQL database.

async def query(sql, *params):
    async with pool.acquire() as connection:
        return await connection.fetch(sql, *params)
# Creates a function to execute a query against the database. Asyncpg method prevent SQL Injection.