import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOL_CATALOG_PATH = Path(__file__).resolve().parents[1] / "shared" / "tool_catalog.json"
_MAX_TOOL_HINTS = 10


def _load_catalog() -> list[dict]:
    with _TOOL_CATALOG_PATH.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    tools = raw.get("tools")
    if not isinstance(tools, list):
        raise ValueError("shared/tool_catalog.json must contain a 'tools' list")

    seen_ids: set[str] = set()
    normalized_tools: list[dict] = []
    for entry in tools:
        if not isinstance(entry, dict):
            raise ValueError("Tool catalog entries must be JSON objects")

        name = entry.get("name")
        category = entry.get("category")
        description = entry.get("desc")
        mcp_tool = entry.get("mcpTool")
        server = entry.get("server")

        if not all(isinstance(value, str) and value.strip() for value in (name, category, description, mcp_tool, server)):
            raise ValueError(f"Invalid tool catalog entry: {entry!r}")

        if mcp_tool in seen_ids:
            raise ValueError(f"Duplicate MCP tool id in catalog: {mcp_tool}")

        seen_ids.add(mcp_tool)
        normalized_tools.append(entry)

    return normalized_tools


TOOL_CATALOG = _load_catalog()
ALLOWED_TOOL_HINTS = {tool["mcpTool"] for tool in TOOL_CATALOG}


def normalize_tool_hints(tool_hints) -> list[str]:
    """
    Accept only known MCP tool identifiers from the shared catalog.

    This prevents prompt injection via raw client-supplied hint strings and
    avoids bloating the prompt with arbitrary or duplicated values.
    """
    if not isinstance(tool_hints, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()

    for item in tool_hints:
        if len(normalized) >= _MAX_TOOL_HINTS:
            break
        if not isinstance(item, str):
            continue

        candidate = item.strip()
        if not candidate or candidate in seen or candidate not in ALLOWED_TOOL_HINTS:
            continue

        seen.add(candidate)
        normalized.append(candidate)

    dropped = len(tool_hints) - len(normalized)
    if dropped > 0:
        logger.info("Dropped %d invalid or duplicate tool hint(s)", dropped)

    return normalized
