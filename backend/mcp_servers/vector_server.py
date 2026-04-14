import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import logging
from fastmcp import FastMCP
from db import get_connection


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


vector_mcp = FastMCP("vector_server")

# ---------------------------------------------------------------------------
# Shapely tools
# Edit docstrings here to guide the AI agent on when to call each tool.
# ---------------------------------------------------------------------------

@vector_mcp.tool()
async def buffer(geojson:str, meter_radius:float) -> str:
    """
    Creates a buffer zone around a geometry.
    Use this when the user asks about areas within a certain distance of a location,
    impact zones, proximity analysis, or wants to create a buffered area. 
    Input must be a GeoJSON geometry string and return value is buffered geometry in GeoJSON format. 
    """
    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ST_AsGeoJSON(ST_Transform(ST_buffer(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 25833), %s), 4326)) AS buffer_geojson;
                    """,
                    (geojson, meter_radius)
                )
                row = await cur.fetchone()
                if not row:
                    return "Buffer operation failed: no result returned from database."
                return json.dumps({"buffer_geojson": json.loads(row["buffer_geojson"])}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error creating buffer: {e}")
        return f"Failed to create buffer: {e}"


@vector_mcp.tool()
async def intersection(geojson1: str, geojson2: str) -> str:
    """
    Finds the overlapping area between two geometries.
    Use this when the user asks what two areas have in common, overlap analysis,
    or wants to find the shared region between two spatial features.
    Both inputs must be GeoJSON geometry strings and the return value is the intersected area in GeoJSON format.
    """
    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ST_AsGeoJSON(
                        ST_Transform(
                             ST_Intersection(
                               ST_Transform(
                                   ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),25833),
                               ST_Transform(
                                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),25833)),4326)) AS intersection_geojson;
                    """,
                    (geojson1, geojson2)
                ) 
                row = await cur.fetchone()
                if not row:
                    return "Intersection operation failed: no result returned from database."
                return json.dumps({"intersection_geojson": json.loads(row["intersection_geojson"])}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error calculating intersection: {e}")
        return f"Failed to calculate intersection: {e}"


@vector_mcp.tool()
async def envelope(geojson: str) -> str:
    """
    Returns the bounding box (minimum enclosing rectangle) of a geometry.
    Use this when the user asks for the extent, bounding box, or spatial bounds of a feature.
    Input must be a GeoJSON string. Returns the bounding rectangle as GeoJSON.
    """
    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ST_AsGeoJSON(
                        ST_Transform(
                            ST_Envelope(
                                ST_Transform(
                                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),25833)),4326)) AS envelope_geojson;
                    """,
                    (geojson,)
                )
                row = await cur.fetchone()
                if not row or not row["envelope_geojson"]:
                    return "Could not create envelope."
                return json.dumps({
                    "envelope_geojson": json.loads(row["envelope_geojson"])
                }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Envelope failed: {e}")
        return f"Error creating envelope: {e}"


@vector_mcp.tool()
async def get_coordinates(geojson: str) -> str:
    """
    Extracts the coordinate pairs from a geometry.
    Use this when the user wants to know the actual lon/lat or x/y values of a geometry,
    or needs the raw coordinate list of a spatial feature.
    """
    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ST_AsGeoJSON(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)) AS geojson_out;
                    """,
                    (geojson,)
                )
                row = await cur.fetchone()
                if not row or not row["geojson_out"]:
                    return "Could not get coordinates."
                geometry = json.loads(row["geojson_out"])
                return json.dumps({"type": geometry["type"], "coordinates": geometry["coordinates"]}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting coordinates: {e}")
        raise ValueError(f"Failed to get coordinates: {e}")


# ---------------------------------------------------------------------------
# GeoPandas tools
# ---------------------------------------------------------------------------

@vector_mcp.tool()
async def point_in_polygon(points_geojson: str, polygon_geojson: str) -> str:
    """
    Checks which points fall inside which polygons using a spatial join.
    Use this when the user wants to know if locations are inside a protected area,
    zone, or region, or asks about containment of point features within polygons.
    Both inputs are GeoJSON strings.
    """
    try:
        points = json.loads(points_geojson)
        results = []
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                for feature in points.get("features", []):
                    geom = json.dumps(feature["geometry"])
                    await cur.execute(
                        """
                        SELECT ST_Within(
                            ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 25833),
                            ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 25833)
                        ) AS is_inside;
                        """,
                        (geom, polygon_geojson)
                    )
                    row = await cur.fetchone()
                    if row and row["is_inside"]:
                        results.append(feature)
        return json.dumps({
            "status": "success",
            "message": f"{len(results)} point(s) found inside the polygon." if results else "No points found inside the polygon.",
            "num_points": len(results),
            "points_inside": results
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in point_in_polygon: {e}")
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Database tools — custom tools
# ---------------------------------------------------------------------------

@vector_mcp.tool()
async def get_verdensarv_sites() -> str:
    """
    Fetches all Norwegian world heritage sites from the database including
    their name, protection date, description and GeoJSON geometry.
    Use this tool when the user asks about Norwegian world heritage sites,
    their locations, or any details about them. Always return the full list
    from the database, even if the user only asks about one site.
    After calling this tool, pass the GeoJSON geometries to map-draw_shape()
    to visualize the sites on the map.
    """
    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        navn,
                        vernedato,
                        informasjon,
                        ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
                    FROM norges_verdensarv;
                    """
                )
                rows = await cur.fetchall()
                if not rows:
                    return "No world heritage sites found in database."
                results = [
                    {
                        "navn": dict(row)["navn"],
                        "vernedato": dict(row)["vernedato"].isoformat() if dict(row)["vernedato"] else None,
                        "informasjon": dict(row)["informasjon"],
                        "geojson": dict(row)["geojson"],
                    }
                    for row in rows
                ]
                return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to fetch world heritage sites: {e}")
        return f"Error fetching world heritage sites: {e}"

@vector_mcp.tool(annotations={"readOnlyHint": True})
async def voronoi(geojson: str) -> str:
    """
    Generates a Voronoi diagram from a GeoJSON FeatureCollection of points (or any geometries,
    whose centroids are used as input seeds). Uses PostGIS ST_VoronoiPolygons for a true
    Delaunay-based result.

    Returns a GeoJSON FeatureCollection where each Voronoi polygon carries the properties
    of the seed feature it was generated from.
    Send the result to map-draw_shape() to visualize it on the map.

    Use this tool whenever the user asks for Voronoi analysis, influence zones, nearest-feature
    partitioning, or any spatial tessellation from a set of point or polygon features.

    Args:
        geojson: A GeoJSON FeatureCollection (points or polygons). Each feature may carry
                 any properties — they are preserved on the output polygons.
    """
    try:
        collection = json.loads(geojson)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Ugyldig GeoJSON: {e}"})

    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        return json.dumps({"error": "GeoJSON må være en FeatureCollection."})

    features_in = collection.get("features")
    if not isinstance(features_in, list):
        return json.dumps({"error": "GeoJSON mangler en gyldig 'features'-liste."})
    if len(features_in) < 2:
        return json.dumps({"error": "Minst 2 punkter kreves for å generere et Voronoi-diagram."})

    valid_features = []
    for index, feature in enumerate(features_in, start=1):
        if not isinstance(feature, dict):
            return json.dumps({"error": f"Feature #{index} er ugyldig."})

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or not geometry.get("type"):
            return json.dumps({"error": f"Feature #{index} mangler en gyldig geometri."})

        valid_features.append(feature)

    try:
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    WITH seeds AS (
                        SELECT
                            ST_Centroid(
                                ST_Transform(
                                    ST_SetSRID(ST_GeomFromGeoJSON(feat->>'geometry'), 4326),
                                    25833
                                )
                            ) AS centroid
                        FROM json_array_elements(%s::json) AS feat
                    )
                    SELECT
                        COUNT(*) FILTER (WHERE centroid IS NOT NULL AND NOT ST_IsEmpty(centroid)) AS seed_count,
                        COUNT(DISTINCT ST_AsEWKB(centroid)) FILTER (WHERE centroid IS NOT NULL AND NOT ST_IsEmpty(centroid)) AS distinct_seed_count
                    FROM seeds;
                    """,
                    (json.dumps(valid_features),)
                )
                stats = await cur.fetchone()
                seed_count = int(stats["seed_count"] or 0) if stats else 0
                distinct_seed_count = int(stats["distinct_seed_count"] or 0) if stats else 0

                if seed_count < 2:
                    return json.dumps({"error": "Minst 2 gyldige geometrier kreves for å generere et Voronoi-diagram."})
                if distinct_seed_count < 2:
                    return json.dumps({"error": "Minst 2 unike punktposisjoner kreves for å generere et Voronoi-diagram."})
                if distinct_seed_count != seed_count:
                    return json.dumps({"error": "Duplikate seed-posisjoner støttes ikke i Voronoi-verktøyet."})

                await cur.execute(
                    """
                    WITH seeds AS (
                        SELECT
                            ordinality AS seed_id,
                            feat,
                            ST_Centroid(
                                ST_Transform(
                                    ST_SetSRID(ST_GeomFromGeoJSON(feat->>'geometry'), 4326),
                                    25833
                                )
                            ) AS centroid
                        FROM json_array_elements(%s::json) WITH ORDINALITY AS t(feat, ordinality)
                    ),
                    valid_seeds AS (
                        SELECT seed_id, feat, centroid
                        FROM seeds
                        WHERE centroid IS NOT NULL AND NOT ST_IsEmpty(centroid)
                    ),
                    voronoi_polys AS (
                        SELECT ROW_NUMBER() OVER () AS poly_id, dumped.geom AS voronoi_geom
                        FROM (
                            SELECT (ST_Dump(ST_VoronoiPolygons(ST_Collect(centroid)))).geom
                            FROM valid_seeds
                        ) AS dumped
                    )
                    SELECT
                        s.seed_id,
                        s.feat->'properties' AS properties,
                        ST_AsGeoJSON(ST_Transform(p.voronoi_geom, 4326)) AS geojson
                    FROM valid_seeds s
                    JOIN LATERAL (
                        SELECT v.voronoi_geom
                        FROM voronoi_polys v
                        ORDER BY
                            CASE WHEN ST_Covers(v.voronoi_geom, s.centroid) THEN 0 ELSE 1 END,
                            ST_Distance(v.voronoi_geom, s.centroid),
                            v.poly_id
                        LIMIT 1
                    ) p ON TRUE
                    ORDER BY s.seed_id;
                    """,
                    (json.dumps(valid_features),)
                )
                rows = await cur.fetchall()
                if not rows:
                    return json.dumps({"error": "Voronoi-beregning returnerte ingen polygoner."})

                out_features = []
                for row in rows:
                    r = dict(row)
                    geometry = json.loads(r["geojson"]) if r["geojson"] else None
                    properties = r["properties"] if isinstance(r["properties"], dict) else {}
                    out_features.append({
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": properties,
                    })

                return json.dumps(
                    {"type": "FeatureCollection", "features": out_features},
                    ensure_ascii=False,
                    default=str,
                )
    except Exception as e:
        logger.error(f"voronoi failed: {e}")
        return json.dumps({"error": f"Voronoi-beregning feilet: {e}"})


# Mount the vector MCP ASGI app at the /mcp/vector path
vector_app = vector_mcp.http_app(path="/mcp")
