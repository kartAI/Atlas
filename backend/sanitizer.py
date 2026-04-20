"""
Thinking-trace sanitizer.

Scrubs sensitive server internals from AI reasoning traces before they are
streamed to the client.  Imported by server.py and exercised directly by
test_sanitizer.py.

Design notes:

  • _RE_SQL is intentionally case-sensitive (no re.IGNORECASE).
    Matching only ALL-CAPS SQL keywords prevents false positives on
    common English verbs ("select", "update", "delete").  The pattern
    also requires a semicolon terminator so it never over-consumes text
    when no terminator is found — a `$` anchor in non-MULTILINE mode
    anchors to end-of-string, causing a lazy quantifier to swallow up
    to N chars of unrelated text.  Any schema/table refs in non-
    terminated SQL are still caught by _RE_SCHEMA_TABLE.

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
# Requires `;` terminator to avoid matching past end-of-statement.
# Bounded at 800 chars — enough for even a complex multi-line query.
# Defense-in-depth: _RE_SCHEMA_TABLE catches schema refs in any SQL
# that is not terminated with a semicolon.
_RE_SQL = re.compile(
    r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|"
    r"CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|EXPLAIN(?:\s+ANALYZE)?)\b"
    r"[\s\S]{0,800}?;",
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
    r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_]+"
    r"|\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+",
)
# Absolute file system paths — reveals server directory layout.
_RE_FILE_PATH = re.compile(
    r"(?:[A-Za-z]:\\(?:[\w\s\-\.]+\\)+[\w\s\-\.]*"   # Windows: C:\Users\...
    r"|/(?:home|var|etc|opt|usr|srv|app|root)/\S+)",  # Unix absolute paths
)

# ---------------------------------------------------------------------------
# Ordered rule table  (most-specific → least-specific)
# ---------------------------------------------------------------------------

_SANITIZE_RULES: list[tuple[re.Pattern, str]] = [
    (_RE_CONN_STRING,   "[connection-string]"),
    (_RE_TOKEN,         "[token]"),
    (_RE_AZURE_BLOB,    "[azure-storage-url]"),
    (_RE_FILE_PATH,     "[file-path]"),
    (_RE_SQL,           "[SQL query]"),
    (_RE_SCHEMA_TABLE,  "[table]"),
    (_RE_UUID,          "[id]"),
    (_RE_INTERNAL_URL,  "[internal-url]"),
    (_RE_MCP_PATH,      "[mcp-endpoint]"),
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_thinking(text: str) -> str:
    """Strip sensitive internals (SQL, schemas, IDs, URLs, paths) from reasoning traces."""
    for pattern, replacement in _SANITIZE_RULES:
        text = pattern.sub(replacement, text)
    return text
