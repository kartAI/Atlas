"""
Thinking-trace sanitizer.

Scrubs sensitive server internals from AI reasoning traces before they are
streamed to the client.  Imported by server.py and exercised directly by
test_sanitizer.py.

Design notes:

  • SQL redaction is intentionally case-sensitive (no re.IGNORECASE).
    Matching only ALL-CAPS SQL keywords prevents false positives on
    common English verbs ("select", "update", "delete").  SQL is redacted
    with a deterministic scanner instead of a spanning regex so very long
    or unterminated statements cannot leak and cannot trigger regex
    backtracking surprises.

  • Rules are ordered from most-specific to least-specific so that
    broader patterns do not shadow more precise replacements.
"""

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_RE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_RE_SCHEMA_TABLE = re.compile(
    r"\b(?:app|kulturmiljoer|public)\.\w+",
    re.IGNORECASE,
)
# Case-sensitive: only ALL-CAPS SQL as written by AI models.
_RE_SQL_KEYWORD_START = re.compile(
    r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|"
    r"CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|EXPLAIN(?:\s+ANALYZE)?)\b"
)
_RE_CONN_STRING = re.compile(
    r"(?:postgres(?:ql)?://|mongodb(?:\+srv)?://|mysql://|redis://|amqp://|mssql://|"
    r"DefaultEndpointsProtocol=|AccountKey=)\S+",
    re.IGNORECASE,
)
# Azure Blob Storage URLs — not covered by _RE_INTERNAL_URL.
_RE_AZURE_BLOB = re.compile(
    r"https?://\S+\.blob\.core\.windows\.net\S*",
    re.IGNORECASE,
)
# Standalone Azure SAS signatures sometimes appear without the full blob URL.
_RE_AZURE_SAS_SIG = re.compile(
    r"(?<![A-Za-z0-9_])sig=[A-Za-z0-9%/+_-]{12,}",
    re.IGNORECASE,
)
_RE_INTERNAL_URL = re.compile(
    r"https?://(?:"
    r"localhost|127\.0\.0\.1|0\.0\.0\.0"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|host\.docker\.internal"
    r")(?::\d+)?\S*",
    re.IGNORECASE,
)
_RE_MCP_PATH = re.compile(r"/mcp/\w+/mcp\b")
_RE_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}\b"
    r"|\bAKIA[A-Z0-9]{16}\b"
    r"|\bnpm_[A-Za-z0-9]{20,}\b"
    r"|\bxox[a-z]-[A-Za-z0-9-]{10,}\b"
    r"|\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+",
)
# Absolute file system paths — reveals server directory layout.
_RE_FILE_PATH = re.compile(
    r"(?:[A-Za-z]:\\(?:[\w\s\-\.]+\\)+[\w\s\-\.]*"   # Windows: C:\Users\...
    r"|/(?:home|var|etc|opt|usr|srv|app|root|tmp|data)/\S+)",  # Unix absolute paths
)

# ---------------------------------------------------------------------------
# Ordered rule table  (most-specific → least-specific)
# ---------------------------------------------------------------------------

_PRE_SQL_RULES: list[tuple[re.Pattern, str]] = [
    (_RE_CONN_STRING,   "[connection-string]"),
    (_RE_TOKEN,         "[token]"),
    (_RE_AZURE_BLOB,    "[azure-storage-url]"),
    (_RE_AZURE_SAS_SIG, "[token]"),
    (_RE_FILE_PATH,     "[file-path]"),
]

_POST_SQL_RULES: list[tuple[re.Pattern, str]] = [
    (_RE_SCHEMA_TABLE,  "[table]"),
    (_RE_UUID,          "[id]"),
    (_RE_INTERNAL_URL,  "[internal-url]"),
    (_RE_MCP_PATH,      "[mcp-endpoint]"),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _redact_sql_statements(text: str) -> str:
    """Redact ALL-CAPS SQL from keyword to next semicolon, or to end of text."""
    parts: list[str] = []
    pos = 0

    while True:
        match = _RE_SQL_KEYWORD_START.search(text, pos)
        if not match:
            parts.append(text[pos:])
            break

        parts.append(text[pos:match.start()])
        parts.append("[SQL query]")

        semicolon = text.find(";", match.end())
        if semicolon < 0:
            break
        pos = semicolon + 1

    return "".join(parts)


def sanitize_thinking(text: str) -> str:
    """Strip sensitive internals (SQL, schemas, IDs, URLs, paths) from reasoning traces."""
    for pattern, replacement in _PRE_SQL_RULES:
        text = pattern.sub(replacement, text)
    text = _redact_sql_statements(text)
    for pattern, replacement in _POST_SQL_RULES:
        text = pattern.sub(replacement, text)
    return text


def sanitize_completed_thinking(text: str) -> str:
    """Finalize reasoning redaction for completed traces.

    Streaming chunks can safely hold back an unterminated ALL-CAPS SQL statement
    while more text is still arriving. Once the model has finished, that SQL
    tail must be redacted before the final flush and before persistence.
    """
    text = sanitize_thinking(text)
    pending_start = find_pending_sql_start(text)
    if pending_start >= 0:
        text = f"{text[:pending_start]}[SQL query]"
    return text


# Pattern that matches an ALL-CAPS SQL keyword at the start of a potential
# statement that has NOT yet been terminated with `;`.  Used by the streaming
# holdback logic to suppress emission while an unterminated SQL statement is
# still accumulating.
_RE_SQL_KEYWORD_START = re.compile(
    r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|"
    r"CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|EXPLAIN(?:\s+ANALYZE)?)\b",
)


def find_pending_sql_start(text: str) -> int:
    """Return the char offset of the last unterminated SQL keyword in *text*.

    If the text contains an ALL-CAPS SQL keyword (SELECT, INSERT INTO, etc.)
    that is NOT followed by a ``;`` terminator, return the start offset of that
    keyword — everything from that offset onward should be held back during
    streaming.

    Returns -1 when there is no pending (unterminated) SQL.
    """
    last_start = -1
    for m in _RE_SQL_KEYWORD_START.finditer(text):
        # Check whether this keyword is followed by a `;` in the remaining text
        after = text[m.start():]
        if ";" not in after:
            last_start = m.start()
    return last_start
