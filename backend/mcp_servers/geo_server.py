"""
Tools:
  - list_kommuner:    List municipality numbers and names.
  - list_vernetyper:  List all protection types for cultural environments.
  - buffer_search:    Find cultural environments within a given radius.
"""

import json
import logging

from fastmcp import FastMCP
from db import query
from config import (
    BUFFER_DISTANCE_MAX_METERS,
    BUFFER_DISTANCE_MIN_METERS,
    BUFFER_RESULT_LIMIT,
)

logger = logging.getLogger(__name__)

mcp = FastMCP("geo_server")


@mcp.tool
async def list_kommuner(search: str = "") -> str:
    """
    List kommunenummer og kommunenavn. Kan filtreres med søkeord.

    Args:
        search: Søkeord for å filtrere på nummer eller navn (valgfritt).
    """
    if search:
        result = await query(
            "SELECT identifier, description FROM kulturmiljoer.kommunenummer "
            "WHERE identifier ILIKE %s OR description ILIKE %s ORDER BY identifier ASC",
            (f"%{search}%", f"%{search}%")
        )
    else:
        result = await query(
            "SELECT identifier, description FROM kulturmiljoer.kommunenummer ORDER BY identifier ASC"
        )
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool
async def list_vernetyper() -> str:
    """List alle vernetyper for kulturmiljøer."""
    result = await query(
        "SELECT identifier, description FROM kulturmiljoer.vernetype ORDER BY identifier ASC"
    )
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool
async def buffer_search(latitude: float, longitude: float, distance: float = 1000) -> str:
    """
    Finn kulturmiljøer innenfor en gitt avstand fra et punkt.

    Args:
        latitude:  Breddegrad, f.eks. 58.1599 for Kristiansand.
        longitude: Lengdegrad, f.eks. 8.0182 for Kristiansand.
        distance:  Søkeradius i meter. Standard er 1000m.
    """
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return json.dumps({"error": "Ugyldige koordinater."})

    if not (BUFFER_DISTANCE_MIN_METERS <= distance <= BUFFER_DISTANCE_MAX_METERS):
        return json.dumps({
            "error": f"Avstand må være mellom {BUFFER_DISTANCE_MIN_METERS} og {BUFFER_DISTANCE_MAX_METERS} meter."
        })

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
        """, (longitude, latitude, longitude, latitude, distance, BUFFER_RESULT_LIMIT))

        features = []
        for row in result:
            geometry = json.loads(row["geojson"]) if row["geojson"] else None
            properties = {k: v for k, v in row.items() if k != "geojson"}
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})

        return json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False
        )
    except Exception as exc:
        logger.exception("buffer_search failed: %s", type(exc).__name__)
        return json.dumps({"error": "Feil ved buffersøk. Prøv igjen senere."})


# Expose as ASGI app for mounting in server.py
geo_app = mcp.http_app(path="/mcp")