from copilot import Tool
from db import query
import asyncio
import json
import logging
from config import (
    BUFFER_DISTANCE_MAX_METERS,
    BUFFER_DISTANCE_MIN_METERS,
    BUFFER_RESULT_LIMIT,
    list_documents,
    fetch_document,
)

logger = logging.getLogger(__name__)

async def handle_list_kommuner(invocation):
    search = invocation["arguments"].get("search", "")
    if search:
        result = await query(
            "SELECT identifier, description FROM kulturmiljoer.kommunenummer WHERE identifier ILIKE %s OR description ILIKE %s ORDER BY identifier ASC",
            (f"%{search}%", f"%{search}%")
        )
    else:
        result = await query(
            "SELECT identifier, description FROM kulturmiljoer.kommunenummer ORDER BY identifier ASC"
        )
    return {
        "textResultForLlm": json.dumps(result, ensure_ascii=False, default=str),
        "resultType": "success"
    }
    
list_kommuner_tool = Tool(
    name="list_kommuner",
    description="List kommunenummer og kommunenavn. Kan filtreres med søkeord.",
    parameters={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "Søkeord for å filtrere på nummer eller navn"
            }
        },
        "required": []
    },
    handler=handle_list_kommuner
)

async def handle_list_vernetyper(invocation):
    result = await query(
        "SELECT identifier, description FROM kulturmiljoer.vernetype ORDER BY identifier ASC"
    )
    return {
        "textResultForLlm": json.dumps(result, ensure_ascii=False, default=str),
        "resultType": "success"
    }
    
list_vernetyper_tool = Tool(
    name="list_vernetyper",
    description="List alle vernetyper for kulturmiljøer.",
    parameters={
        "type": "object",
        "properties": {},
        "required": []
    },
    handler=handle_list_vernetyper
)

async def handle_buffer_search(invocation):
    arguments = invocation.get("arguments", {})
    request_id = invocation.get("id", "unknown")

    try:
        lat = float(arguments["latitude"])
        lon = float(arguments["longitude"])
        distance = float(arguments.get("distance", 1000))
    except (KeyError, TypeError, ValueError):
        logger.warning("buffer_search invalid arguments request_id=%s", request_id)
        return {
            "textResultForLlm": "Ugyldig input: latitude, longitude og distance må være numeriske verdier.",
            "resultType": "error"
        }

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        logger.warning("buffer_search out-of-range coordinates request_id=%s", request_id)
        return {
            "textResultForLlm": "Ugyldige koordinater: latitude må være mellom -90 og 90, longitude mellom -180 og 180.",
            "resultType": "error"
        }

    if not (BUFFER_DISTANCE_MIN_METERS <= distance <= BUFFER_DISTANCE_MAX_METERS):
        logger.warning("buffer_search out-of-range distance request_id=%s", request_id)
        return {
            "textResultForLlm": (
                f"Ugyldig avstand: må være mellom {BUFFER_DISTANCE_MIN_METERS} "
                f"og {BUFFER_DISTANCE_MAX_METERS} meter."
            ),
            "resultType": "error"
        }

    logger.debug("buffer_search started request_id=%s", request_id)

    try:
        result = await query("""
            SELECT k.objid, k.navn, k.kulturmiljokategori, k.vernetype,
                   k.informasjon,
                   ST_Distance(
                       k.omrade,
                       ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)
                   ) as avstand_meter,
                   ST_AsGeoJSON(ST_Transform(k.omrade, 4326)) as geojson
            FROM kulturmiljoer.kulturmiljo k
            WHERE ST_DWithin(
                k.omrade,
                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                %s
            )
            ORDER BY avstand_meter ASC
            LIMIT %s
        """, (lon, lat, lon, lat, distance, BUFFER_RESULT_LIMIT))

        features = []
        for row in result:
            geometry = json.loads(row["geojson"]) if row["geojson"] else None
            properties = {k: v for k, v in row.items() if k != "geojson"}
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": properties
            })

        feature_collection = {
            "type": "FeatureCollection",
            "features": features
        }

        logger.info("buffer_search success request_id=%s result_count=%s", request_id, len(result))
        return {
            "textResultForLlm": json.dumps(feature_collection, ensure_ascii=False),
            "resultType": "success"
        }
    except Exception as exc:
        logger.exception(
            "buffer_search failed request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        return {
            "textResultForLlm": "Feil ved buffersøk. Proev igjen senere.",
            "resultType": "error"
        }
        
buffer_search_tool = Tool(
    name="buffer_search",
    description="Finn kulturmiljøer innenfor en gitt avstand fra et punkt. Tar koordinater (latitude/longitude) og avstand i meter.",
    parameters={
        "type": "object",
        "properties": {
            "latitude": {
                "type": "number",
                "description": "Breddegrad (latitude), f.eks. 58.1599 for Kristiansand"
            },
            "longitude": {
                "type": "number",
                "description": "Lengdegrad (longitude), f.eks. 8.0182 for Kristiansand"
            },
            "distance": {
                "type": "number",
                "description": "Søkeradius i meter. Standard er 1000m."
            }
        },
        "required": ["latitude", "longitude"]
    },
    handler=handle_buffer_search
)

# DEMO FUNCTIONALITY - AZURE BLOB STORAGE DOCUMENT TOOLS

async def handle_list_documents(invocation):
    """List all available PDF documents in Azure Blob Storage."""
    docs = list_documents()
    return {
        "textResultForLlm": json.dumps(docs, ensure_ascii=False),
        "resultType": "success"
    }

list_documents_tool = Tool(
    name="list_documents",
    description="List alle tilgjengelige PDF-dokumenter i Azure Blob Storage.",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=handle_list_documents
)


async def handle_fetch_document(invocation):
    """Fetch the full text content of a specific document from Azure Blob Storage."""
    name = invocation["arguments"].get("name", "")
    if not name:
        return {"textResultForLlm": "Mangler dokumentnavn.", "resultType": "error"}
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, fetch_document, name)
        return {
            "textResultForLlm": json.dumps({"name": name, "content": text}, ensure_ascii=False),
            "resultType": "success"
        }
    except Exception as exc:
        logger.exception("fetch_document failed name=%s error_type=%s", name, type(exc).__name__)
        return {"textResultForLlm": f"Kunne ikke hente dokumentet '{name}'.", "resultType": "error"}

fetch_document_tool = Tool(
    name="fetch_document",
    description="Hent tekstinnholdet fra et spesifikt PDF-dokument i Azure Blob Storage. VIKTIG: Kall alltid list_documents først for å få det eksakte filnavnet før du bruker dette verktøyet.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Det eksakte filnavnet på dokumentet slik det returneres av list_documents, f.eks. 'KU Landskap 16.12.25 (1).PDF'"
            }
        },
        "required": ["name"]
    },
    handler=handle_fetch_document
)
# DEMO END