"""
Tests for sanitize_thinking() in sanitizer.py.
Run standalone: python test_sanitizer.py
"""
import sys

from sanitizer import sanitize_thinking as sanitize


# ---- Test cases ---- (label, input, must_have, must_not_have)
cases = [
    # --- False positives: English verbs must NOT be redacted ---
    (
        "FP: English 'select'",
        "I need to select the right approach here.",
        ["select"],
        [],
    ),
    (
        "FP: English 'update'",
        "The user wants to update their preferences.",
        ["update"],
        [],
    ),
    (
        "FP: English 'delete'",
        "We should delete this concern from our list.",
        ["delete"],
        [],
    ),
    (
        "FP: English 'create'",
        "I will create a new plan for this task.",
        ["create"],
        [],
    ),
    (
        "FP: no over-consumption (sentence after select)",
        "I will select the best strategy. Then I'll proceed.",
        ["I will select", "Then I'll proceed"],
        [],
    ),

    # --- SQL ALL-CAPS + semicolon: MUST be fully redacted ---
    (
        "SQL: simple SELECT",
        "SELECT id, name FROM app.users WHERE id = 'abc';",
        ["[SQL query]"],
        ["SELECT", "app.users", "id ="],
    ),
    (
        "SQL: INSERT INTO",
        "INSERT INTO app.messages (chat_id, role) VALUES ('a', 'b');",
        ["[SQL query]"],
        ["INSERT", "app.messages"],
    ),
    (
        "SQL: UPDATE",
        "UPDATE app.chats SET title = 'foo' WHERE id = 'bar';",
        ["[SQL query]"],
        ["UPDATE", "app.chats"],
    ),
    (
        "SQL: DELETE FROM",
        "DELETE FROM app.sessions WHERE expires_at < NOW();",
        ["[SQL query]"],
        ["DELETE", "app.sessions"],
    ),
    (
        "SQL: TRUNCATE TABLE",
        "TRUNCATE TABLE app.messages;",
        ["[SQL query]"],
        ["TRUNCATE", "app.messages"],
    ),
    (
        "SQL: EXPLAIN ANALYZE",
        "EXPLAIN ANALYZE SELECT * FROM app.chunks;",
        ["[SQL query]"],
        ["EXPLAIN", "app.chunks"],
    ),
    (
        "SQL: multiline query",
        "SELECT\n  id,\n  name\nFROM app.users\nWHERE role = 'admin';",
        ["[SQL query]"],
        ["SELECT", "app.users"],
    ),

    # --- SQL without semicolon: schema ref still caught individually ---
    (
        "SQL no semi: schema ref still caught",
        "I will query app.messages to find the answer",
        ["[table]"],
        ["app.messages"],
    ),

    # --- UUID ---
    (
        "UUID redaction",
        "The chat id is a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        ["[id]"],
        ["a1b2c3d4-e5f6"],
    ),
    (
        "UUID uppercase",
        "Session A1B2C3D4-E5F6-7890-ABCD-EF1234567890 expired",
        ["[id]"],
        ["A1B2C3D4"],
    ),

    # --- Connection strings ---
    (
        "ConnStr postgres",
        "Using postgres://user:secret@db.host:5432/mydb?sslmode=require",
        ["[connection-string]"],
        ["postgres://", "secret"],
    ),
    (
        "ConnStr DefaultEndpoints",
        "DefaultEndpointsProtocol=https;AccountName=foo;AccountKey=bar",
        ["[connection-string]"],
        ["AccountName=foo"],
    ),
    (
        "ConnStr AccountKey standalone",
        "AccountKey=dGhpcyBpcyBhIGJhc2U2NA==",
        ["[connection-string]"],
        ["AccountKey="],
    ),

    # --- Tokens ---
    (
        "Token ghp_",
        "Authenticated with ghp_abcdefghijklmnopqrst1234567890",
        ["[token]"],
        ["ghp_"],
    ),
    (
        "Token github_pat_",
        "Token: github_pat_ABCDEFGHIJ1234567890abcdef",
        ["[token]"],
        ["github_pat_"],
    ),
    (
        "Token sk-",
        "API key is sk-abcdefghijklmnopqrstuvwxyz1234",
        ["[token]"],
        ["sk-"],
    ),

    # --- Azure Blob ---
    (
        "Azure blob URL",
        "Download from https://mystorageacct.blob.core.windows.net/docs/file.pdf",
        ["[azure-storage-url]"],
        ["blob.core.windows.net", "mystorageacct"],
    ),
    (
        "Azure blob URL with SAS token",
        "https://store.blob.core.windows.net/c/f.pdf?sv=2020&sig=abc123",
        ["[azure-storage-url]"],
        ["store.blob", "sig="],
    ),

    # --- Internal URLs ---
    (
        "Internal localhost",
        "Calling http://localhost:8000/api/chat",
        ["[internal-url]"],
        ["localhost"],
    ),
    (
        "Internal 127.0.0.1",
        "Endpoint is http://127.0.0.1:5000/health",
        ["[internal-url]"],
        ["127.0.0.1"],
    ),

    # --- MCP paths ---
    (
        "MCP path standalone",
        "Using /mcp/db/mcp for database queries",
        ["[mcp-endpoint]"],
        ["/mcp/db/mcp"],
    ),
    (
        "MCP path with trailing slash stays (localhost catches full URL)",
        "Server at http://localhost:8000/mcp/geo/mcp",
        ["[internal-url]"],
        ["localhost", "/mcp/geo/mcp"],
    ),

    # --- File paths ---
    (
        "Windows absolute path",
        r"Loading config from C:\Users\enged\source\repos\Atlas\backend\config.py",
        ["[file-path]"],
        ["C:\\Users"],
    ),
    (
        "Unix absolute path /app",
        "Module at /app/backend/server.py failed to load",
        ["[file-path]"],
        ["/app/backend"],
    ),
    (
        "Unix path /home",
        "Found at /home/ubuntu/backend/db.py",
        ["[file-path]"],
        ["/home/ubuntu"],
    ),

    # --- Schema table refs ---
    (
        "Schema: app.chats",
        "Looking at app.chats for context",
        ["[table]"],
        ["app.chats"],
    ),
    (
        "Schema: kulturmiljoer.kulturmiljo",
        "Query kulturmiljoer.kulturmiljo for results",
        ["[table]"],
        ["kulturmiljoer.kulturmiljo"],
    ),
    (
        "Schema: public.norges_verdensarv",
        "Searching public.norges_verdensarv for heritage sites",
        ["[table]"],
        ["public.norges_verdensarv"],
    ),

    # --- FP gauntlet: common English with dangerous-looking words ---
    (
        "FP: 'public' in normal English",
        "The public announcement was made today.",
        ["public announcement"],
        [],
    ),
    (
        "FP: 'select' mid-sentence",
        "You can select any item from the list to proceed.",
        ["select any item"],
        [],
    ),
    (
        "FP: 'update' mid-sentence",
        "We should update the documentation regularly.",
        ["update the documentation"],
        [],
    ),
    (
        "FP: does not match partial word 'selector'",
        "Use the CSS selector to style the element.",
        ["selector"],
        [],
    ),

    # --- Private / RFC 1918 IP addresses ---
    (
        "Internal 10.x.x.x",
        "Backend at http://10.0.0.5:8080/api/v1",
        ["[internal-url]"],
        ["10.0.0.5"],
    ),
    (
        "Internal 172.16.x.x",
        "Service http://172.16.0.1:3000/health is healthy",
        ["[internal-url]"],
        ["172.16.0.1"],
    ),
    (
        "Internal 192.168.x.x",
        "Running on http://192.168.1.100:5000/",
        ["[internal-url]"],
        ["192.168.1.100"],
    ),
    (
        "Internal host.docker.internal",
        "Connecting to http://host.docker.internal:8000/mcp/db/mcp",
        ["[internal-url]"],
        ["host.docker.internal"],
    ),
    (
        "FP: public IP not redacted",
        "Fetching https://40.112.72.205/api",
        ["https://40.112.72.205/api"],
        [],
    ),

    # --- Additional connection strings ---
    (
        "ConnStr mongodb",
        "Using mongodb://admin:secret@cluster.mongodb.net/db?retryWrites=true",
        ["[connection-string]"],
        ["mongodb://", "secret"],
    ),
    (
        "ConnStr redis",
        "Cache at redis://default:pass@redis.host:6379",
        ["[connection-string]"],
        ["redis://", "pass@"],
    ),
    (
        "ConnStr mysql",
        "mysql://root:pwd@127.0.0.1:3306/mydb",
        ["[connection-string]"],
        ["mysql://", "root:pwd"],
    ),

    # --- JWT / Azure tokens ---
    (
        "Token JWT",
        "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.Signature_abc123",
        ["[token]"],
        ["eyJhbGci"],
    ),
]


ok = 0
fail = 0
for label, inp, must_have, must_not_have in cases:
    result = sanitize(inp)
    passed = True
    for m in must_have:
        if m not in result:
            print(f"FAIL [{label}]: expected {m!r} in result")
            print(f"  input:  {inp!r}")
            print(f"  result: {result!r}")
            passed = False
    for m in must_not_have:
        if m in result:
            print(f"FAIL [{label}]: should NOT contain {m!r} in result")
            print(f"  input:  {inp!r}")
            print(f"  result: {result!r}")
            passed = False
    if passed:
        ok += 1
        print(f"PASS [{label}]")
    else:
        fail += 1

print()
print(f"{ok} passed, {fail} failed")
sys.exit(fail)
