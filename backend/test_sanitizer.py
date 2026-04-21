"""
Tests for sanitize_thinking() in sanitizer.py.
Run standalone: python test_sanitizer.py
"""

import sys

from sanitizer import sanitize_thinking as sanitize
from sanitizer import sanitize_completed_thinking as sanitize_completed
from sanitizer import find_pending_sql_start


def _join(*parts: str) -> str:
    return "".join(parts)


GITHUB_TOKEN = _join("gh", "p_", "abcdefghijklmnopqrst1234567890")
GITHUB_PAT_TOKEN = _join("github", "_pat_", "ABCDEFGHIJ1234567890abcdef")
OPENAI_STYLE_TOKEN = _join("sk", "-", "abcdefghijklmnopqrstuvwxyz1234")
OPENAI_PROJECT_TOKEN = _join("sk", "-proj-", "abcdefghijklmnopqrstuvwxyz", "-SECRETTAIL1234567890")
NPM_TOKEN = _join("np", "m_", "abcdefghijklmnopqrstuvwxyz1234567890")
SLACK_BOT_TOKEN = _join("xox", "b-", "123456789012-123456789012-abcdefghijklmnopqrstuvwxyz")
AZURE_SAS_SIG = _join("si", "g=", "Z3JhbnQtdGhpcy1pcy1hLWxvbmctc2VjcmV0JTJGJTNE")
JWT_TOKEN = _join(
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9",
    ".",
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0",
    ".",
    "Signature_abc123",
)
AWS_ACCESS_KEY = _join("AK", "IAIOSFODNN7EXAMPLE")
LONG_SQL = (
    "SELECT "
    + ", ".join(f"column_{i}" for i in range(260))
    + " FROM app.users WHERE token = 'secret-value' AND role = 'admin';"
)


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
    (
        "SQL: very long query",
        LONG_SQL,
        ["[SQL query]"],
        ["SELECT", "column_200", "app.users", "secret-value"],
    ),

    # --- SQL without semicolon: still redact through end-of-text ---
    (
        "SQL no semi: statement redacted",
        "SELECT password, token FROM app.messages WHERE role = 'admin'",
        ["[SQL query]"],
        ["SELECT", "password", "token", "app.messages", "admin"],
    ),
    (
        "Schema ref without SQL keyword still caught",
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
        f"Authenticated with {GITHUB_TOKEN}",
        ["[token]"],
        [_join("gh", "p_")],
    ),
    (
        "Token github_pat_",
        f"Token: {GITHUB_PAT_TOKEN}",
        ["[token]"],
        [_join("github", "_pat_")],
    ),
    (
        "Token sk-",
        f"API key is {OPENAI_STYLE_TOKEN}",
        ["[token]"],
        [_join("sk", "-")],
    ),
    (
        "Token sk-proj hyphenated",
        f"Project API key is {OPENAI_PROJECT_TOKEN}",
        ["[token]"],
        [_join("sk", "-proj-"), "SECRETTAIL"],
    ),
    (
        "Token npm_",
        f"Token: {NPM_TOKEN}",
        ["[token]"],
        [_join("np", "m_")],
    ),
    (
        "Token Slack bot",
        f"Slack bot token {SLACK_BOT_TOKEN}",
        ["[token]"],
        [_join("xox", "b-"), "123456789012-123456789012"],
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
    (
        "Standalone Azure SAS sig",
        f"Use {AZURE_SAS_SIG} when calling the blob API",
        ["[token]"],
        [_join("si", "g=", "Z3JhbnQ")],
    ),
    (
        "FP: short sig stays",
        "The UI state uses sig=abc123 for a harmless local flag.",
        ["sig=abc123"],
        [],
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
        f"Bearer {JWT_TOKEN}",
        ["[token]"],
        ["eyJhbGci"],
    ),

    # --- AWS access keys ---
    (
        "Token AKIA",
        f"Using key {AWS_ACCESS_KEY} for S3 access",
        ["[token]"],
        [_join("AK", "IA")],
    ),

    # --- File paths: /tmp and /data ---
    (
        "Unix path /tmp",
        "Temp file at /tmp/upload_cache/abc123.json",
        ["[file-path]"],
        ["/tmp/upload_cache"],
    ),
    (
        "Unix path /data",
        "Data stored in /data/postgres/16/main",
        ["[file-path]"],
        ["/data/postgres"],
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


# ---- Completed-trace finalization tests ----

completed_cases = [
    (
        "Completed: unterminated SQL tail redacted",
        "Thinking... SELECT password_hash FROM app.users WHERE email = 'a@example.com'",
        ["Thinking... [SQL query]"],
        ["SELECT", "password_hash", "app.users", "a@example.com"],
    ),
    (
        "Completed: prior safe text preserved before pending SQL",
        "Prefix text. SELECT id FROM app.messages WHERE chat_id = 'abc123'",
        ["Prefix text. [SQL query]"],
        ["SELECT", "app.messages", "abc123"],
    ),
]

print("\n---- Completed trace finalization tests ----")
for label, inp, must_have, must_not_have in completed_cases:
    result = sanitize_completed(inp)
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


# ---- Streaming holdback simulation tests ----
# These verify that secrets split across chunk boundaries are never
# partially emitted before the sanitizer can recognise the full pattern.

_HOLDBACK = 128  # must match server.py _THINKING_HOLDBACK
_MAX_THINKING_CHARS = 100_000
_THINKING_TRUNCATED_MARKER = "[thinking truncated]"


def _finalize_streamed_thinking(raw, chars_sent, truncated):
    final = sanitize_completed(raw)
    if truncated:
        safe_end = max(0, len(final) - _HOLDBACK)
        final = final[:safe_end]
        final = f"{final}\n{_THINKING_TRUNCATED_MARKER}" if final else _THINKING_TRUNCATED_MARKER
    return final[chars_sent:]


def simulate_streaming(full_text, chunk_sizes, max_chars=None):
    """Simulate the server's streaming sanitization with holdback buffer.

    Mirrors the SQL-aware holdback logic in server.py's _stream_chat.
    Returns (final_text, list_of_deltas).
    """
    raw = ""
    chars_sent = 0
    deltas = []
    truncated = False

    pos = 0
    for size in chunk_sizes:
        chunk = full_text[pos:pos + size]
        pos += size
        if not chunk:
            break
        raw += chunk
        if max_chars is not None and len(raw) > max_chars:
            raw = raw[:max_chars]
            truncated = True
        sanitized = sanitize(raw)
        safe_end = max(chars_sent, len(sanitized) - _HOLDBACK)
        # Holdback uses sanitized text so offsets stay valid after redaction.
        pending_sql = find_pending_sql_start(sanitized)
        if pending_sql >= 0:
            safe_end = min(safe_end, pending_sql)
            safe_end = max(safe_end, chars_sent)
        if safe_end > chars_sent:
            deltas.append(sanitized[chars_sent:safe_end])
            chars_sent = safe_end
        if truncated:
            break

    # Final flush (mirrors server's post-loop flush)
    final_delta = _finalize_streamed_thinking(raw, chars_sent, truncated)
    if final_delta:
        deltas.append(final_delta)

    return "".join(deltas), deltas


# (label, full_text, chunk_sizes, forbidden_in_any_delta, must_appear_in_final)
_PAD = " " + "x" * 200  # padding so text exceeds holdback → partial emission

streaming_cases = [
    (
        "Stream: UUID split mid-token",
        f"The chat id is a1b2c3d4-e5f6-7890-abcd-ef1234567890{_PAD}",
        [25, 15, 300],  # split in the middle of the UUID
        ["a1b2c3d4", "e5f6-7890", "ef123456"],
        ["[id]"],
    ),
    (
        "Stream: connection string split",
        f"Using postgres://user:secret@db.host:5432/mydb{_PAD}",
        [20, 30, 300],  # split after "Using postgres://us"
        ["postgres://", "secret", "user:"],
        ["[connection-string]"],
    ),
    (
        "Stream: token split",
        f"Key is {GITHUB_TOKEN}{_PAD}",
        [12, 25, 300],  # split after "Key is ghp_a"
        [_join("gh", "p_")],
        ["[token]"],
    ),
    (
        "Stream: sk-proj token split",
        f"Key is {OPENAI_PROJECT_TOKEN}{_PAD}",
        [14, 30, 300],
        [_join("sk", "-proj-"), "SECRETTAIL"],
        ["[token]"],
    ),
    (
        "Stream: Azure SAS sig split",
        f"Blob auth {AZURE_SAS_SIG}{_PAD}",
        [18, 20, 300],
        [_join("si", "g=", "Z3JhbnQ")],
        ["[token]"],
    ),
    (
        "Stream: schema.table split",
        f"Looking at app.messages for context{_PAD}",
        [16, 10, 300],  # split after "Looking at app.m"
        ["app.messages"],
        ["[table]"],
    ),
    (
        "Stream: internal URL split",
        f"Calling http://10.0.0.5:8080/api/v1{_PAD}",
        [18, 15, 300],
        ["10.0.0.5"],
        ["[internal-url]"],
    ),
    (
        "Stream: clean text unchanged",
        f"This is a completely normal message with no secrets{_PAD}",
        [20, 30, 300],
        [],
        ["completely normal"],
    ),
    (
        "Stream: long SQL split across many chunks",
        f"Prefix text. SELECT id, name FROM app.users WHERE role = 'admin' AND active = TRUE ORDER BY name;{_PAD}",
        [20, 20, 20, 20, 20, 300],  # SQL split across many chunks
        ["SELECT", "app.users", "admin", "ORDER BY"],
        ["[SQL query]"],
    ),
    (
        "Stream: very long SQL over previous regex bound",
        f"Prefix text. {LONG_SQL}{_PAD}",
        [80, 120, 120, 120, 120, 120, 120, 120, 5000],
        ["SELECT", "column_200", "app.users", "secret-value"],
        ["[SQL query]"],
    ),
    (
        "Stream: unterminated SQL final flush",
        "Thinking. SELECT password, token FROM app.users WHERE role = 'admin'",
        [20, 20, 20, 20],
        ["SELECT", "password", "token", "app.users", "admin"],
        ["[SQL query]"],
    ),
    (
        "Stream: SQL keyword arrives first, semicolon much later",
        f"Thinking about this. SELECT * FROM app.messages WHERE chat_id = 'abc123' AND created_at > NOW() - INTERVAL '1 day';{_PAD}",
        [30, 30, 30, 30, 300],
        ["SELECT", "app.messages", "abc123"],
        ["[SQL query]"],
    ),
    (
        "Stream: unterminated SQL at end",
        "Thinking about this. SELECT password_hash FROM app.messages WHERE chat_id = 'abc123'",
        [28, 28, 80],
        ["SELECT", "password_hash", "app.messages", "abc123"],
        ["[SQL query]"],
    ),
    (
        "Stream: redaction before pending SQL (offset mismatch regression)",
        # Token before SQL shrinks from 104→7 chars after redaction; raw
        # offsets would overshoot and leak the SQL keyword in an early delta.
        "Prefix " + _join("gh", "p_") + "a" * 100 + " " + "z" * 200
        + " SELECT id, name, email, phone, address, city, country, created"
        + " FROM app.users WHERE status = True AND role = True"
        + " AND created > now() AND name LIKE pct ORDER BY id;"
        + " " + "x" * 200,
        [80, 80, 80, 80, 200, 300],
        ["SELECT", _join("gh", "p_"), "app.users"],
        ["[token]", "[SQL query]"],
    ),
]

print("\n---- Streaming holdback tests ----")
for label, full_text, chunk_sizes, forbidden, must_in_final in streaming_cases:
    final, deltas = simulate_streaming(full_text, chunk_sizes)
    passed = True

    # No individual delta may contain a forbidden fragment
    for frag in forbidden:
        for i, d in enumerate(deltas):
            if frag in d:
                print(f"FAIL [{label}]: delta {i} contains forbidden {frag!r}")
                print(f"  delta: {d!r}")
                passed = False

    # Final concatenated output must contain expected text
    for m in must_in_final:
        if m not in final:
            print(f"FAIL [{label}]: expected {m!r} in final output")
            print(f"  final: {final!r}")
            passed = False

    # Invariant: streaming result must equal batch sanitization
    expected = sanitize_completed(full_text)
    if final != expected:
        print(f"FAIL [{label}]: streaming result differs from batch sanitization")
        print(f"  streaming: {final!r}")
        print(f"  batch:     {expected!r}")
        passed = False

    if passed:
        ok += 1
        print(f"PASS [{label}]")
    else:
        fail += 1

print("\n---- Truncation guard tests ----")
truncation_input = (
    "Safe prefix "
    + ("x" * (_MAX_THINKING_CHARS - len("Safe prefix ") - 6))
    + _join("gh", "p_", "abcdefghijklmnopqrst1234567890")
)
trunc_final, trunc_deltas = simulate_streaming(
    truncation_input,
    [60_000, 60_000],
    max_chars=_MAX_THINKING_CHARS,
)
trunc_passed = True
for i, d in enumerate(trunc_deltas):
    if _join("gh", "p_") in d:
        print(f"FAIL [Truncation guard]: delta {i} contains forbidden token fragment")
        print(f"  delta: {d!r}")
        trunc_passed = False
if _THINKING_TRUNCATED_MARKER not in trunc_final:
    print("FAIL [Truncation guard]: missing truncation marker in final output")
    print(f"  final: {trunc_final!r}")
    trunc_passed = False
if _join("gh", "p_") in trunc_final:
    print("FAIL [Truncation guard]: final output contains forbidden token fragment")
    print(f"  final: {trunc_final!r}")
    trunc_passed = False
if trunc_passed:
    ok += 1
    print("PASS [Truncation guard]")
else:
    fail += 1

print()
print(f"{ok} passed, {fail} failed")
sys.exit(fail)
