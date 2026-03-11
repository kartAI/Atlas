import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import logging
from typing import Any, cast
from contextlib import asynccontextmanager
from fastmcp import FastMCP
from db import init_db_pool, close_pool, get_connection
from config import MCP_TRANSPORT, MCP_PORT

# gis-mcp imports used for create_map and save_output are "helpers"
from gis_mcp.visualize.map_tool import create_map
from gis_mcp.save_tool import save_output
import geopandas as gpd

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def vector_server_lifespan(server: FastMCP):
    logger.info("Starting up Vector MCP Server")
    success = await init_db_pool()
    if not success:
        logger.warning(
            "Vector server started without a database connection pool. "
            "Check DATABASE_URL in .env"
        )
    yield
    logger.info("Shutting down Vector MCP Server")
    await close_pool()


vector_mcp = FastMCP(lifespan=vector_server_lifespan)

# create_map is registered directly from gis-mcp (requires gis-mcp[visualize])
vector_mcp.tool()(create_map) # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Shapely tools
# Edit docstrings here to guide the AI agent on when to call each tool.
# ---------------------------------------------------------------------------

@vector_mcp.tool()
def buffer(geometry: str, distance: float, resolution: int = 16,
          join_style: int = 1, mitre_limit: float = 5.0,
          single_sided: bool = False) -> dict[str, Any]:
    """
    Creates a buffer zone around a geometry.
    Use this when the user asks about areas within a certain distance of a location,
    impact zones, proximity analysis, or wants to expand a geometry outward.
    Input geometry must be a WKT string. Returns the buffered geometry as WKT.
    """
    _join_style_map = {1: "round", 2: "mitre", 3: "bevel"}
    try:
        from shapely import wkt
        geom = wkt.loads(geometry)
        buffered = geom.buffer(
            distance=distance,
            resolution=resolution,
            join_style=_join_style_map.get(join_style, "round"), #type: ignore[arg-type]
            mitre_limit=mitre_limit,
            single_sided=single_sided
        )
        return {
            "status": "success",
            "geometry": buffered.wkt,
            "message": "Buffer created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating buffer: {e}")
        raise ValueError(f"Failed to create buffer: {e}")


@vector_mcp.tool()
def intersection(geometry1: str, geometry2: str) -> dict[str, Any]:
    """
    Finds the overlapping area between two geometries.
    Use this when the user asks what two areas have in common, overlap analysis,
    or wants to find the shared region between two spatial features.
    Both inputs must be WKT strings. Returns the intersecting geometry as WKT.
    """
    try:
        from shapely import wkt
        geom1 = wkt.loads(geometry1)
        geom2 = wkt.loads(geometry2)
        result = geom1.intersection(geom2)
        return {
            "status": "success",
            "geometry": result.wkt,
            "message": "Intersection created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating intersection: {e}")
        raise ValueError(f"Failed to create intersection: {e}")


@vector_mcp.tool()
def envelope(geometry: str) -> dict[str, Any]:
    """
    Returns the bounding box (minimum enclosing rectangle) of a geometry.
    Use this when the user asks for the extent, bounding box, or spatial bounds of a feature.
    Input must be a WKT string. Returns the bounding rectangle as WKT.
    """
    try:
        from shapely import wkt
        geom = wkt.loads(geometry)
        result = geom.envelope
        return {
            "status": "success",
            "geometry": result.wkt,
            "message": "Envelope (bounding box) created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating envelope: {e}")
        raise ValueError(f"Failed to create envelope: {e}")


@vector_mcp.tool()
def get_coordinates(geometry: str) -> dict[str, Any]:
    """
    Extracts the coordinate pairs from a geometry.
    Use this when the user wants to know the actual lon/lat or x/y values of a geometry,
    or needs the raw coordinate list of a spatial feature.
    Input must be a WKT string.
    """
    try:
        from shapely import wkt
        geom = wkt.loads(geometry)
        return {
            "status": "success",
            "coordinates": [list(coord) for coord in geom.coords],
            "message": "Coordinates retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Error getting coordinates: {e}")
        raise ValueError(f"Failed to get coordinates: {e}")


@vector_mcp.tool()
def geometry_to_geojson(geometry: str) -> dict[str, Any]:
    """
    Converts a WKT geometry string to GeoJSON format.
    Use this when the result needs to be displayed on a map, sent to the frontend,
    or when any tool has returned WKT and the user needs GeoJSON instead.
    """
    try:
        from shapely import wkt
        from shapely.geometry import mapping
        geom = wkt.loads(geometry)
        return {
            "status": "success",
            "geojson": mapping(geom),
            "message": "Geometry converted to GeoJSON successfully"
        }
    except Exception as e:
        logger.error(f"Error converting geometry to GeoJSON: {e}")
        return {"status": "error", "message": str(e)}


@vector_mcp.tool()
def geojson_to_geometry(geojson: dict[str, Any]) -> dict[str, Any]:
    """
    Converts a GeoJSON geometry object to WKT format.
    Use this when a tool or the user provides GeoJSON and another tool requires WKT as input.
    """
    try:
        from shapely.geometry import shape
        geom = shape(geojson)
        return {
            "status": "success",
            "geometry": geom.wkt,
            "message": "GeoJSON converted to geometry successfully"
        }
    except Exception as e:
        logger.error(f"Error converting GeoJSON to geometry: {e}")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# GeoPandas tools
# ---------------------------------------------------------------------------

@vector_mcp.tool()
def point_in_polygon(points_path: str, polygons_path: str,
                    output_path: str | None = None) -> dict[str, Any]:
    """
    Checks which points fall inside which polygons using a spatial join.
    Use this when the user wants to know if locations are inside a protected area,
    zone, or region, or asks about containment of point features within polygons.
    Both inputs are file paths to geospatial files (GeoJSON, Shapefile, etc.).
    """
    try:
        points = gpd.read_file(points_path)
        polygons = gpd.read_file(polygons_path)
        if points.crs is not None and points.crs != polygons.crs:
            polygons = polygons.to_crs(points.crs)
        result = gpd.sjoin(points, polygons, how="left", predicate="within")
        if output_path:
            result.to_file(output_path)
        preview_df = result.head(5).copy()
        if "geometry" in preview_df.columns:
            preview_df["geometry"] = preview_df["geometry"].apply(
                lambda g: g.wkt if g is not None else None
            )
        return {
            "status": "success",
            "message": "Point-in-polygon test completed successfully.",
            "num_features": len(result),
            "crs": str(result.crs),
            "columns": list(result.columns),
            "preview": preview_df.to_dict(orient="records"),
            "output_path": output_path,
        }
    except Exception as e:
        logger.error(f"Error in point_in_polygon: {e}")
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Save tool — uses save_output helper from gis-mcp
# ---------------------------------------------------------------------------

@vector_mcp.tool()
def save_results(
    data: dict[str, Any],
    filename: str | None = None,
    formats: list[str] | None = None,
    folder: str = "outputs"
) -> dict[str, Any]:
    """
    Saves the result from any tool to one or more file formats (JSON, CSV, GeoJSON, Shapefile, etc.).
    Only call this when the user explicitly asks to save or export results.
    formats can include: json, csv, txt, yaml, xlsx, shp, geojson, geotiff.
    """
    try:
        paths = save_output(data, filename=filename, folder=folder, formats=formats)
        return {
            "status": "success",
            "saved_files": paths,
            "message": "Results saved successfully."
        }
    except Exception as e:
        logger.error(f"Error saving results: {e}")
        return {"status": "error", "message": f"Failed to save results: {e}"}


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

    @vector_mcp.tool()
    async def intersection() -> str:
        """
        Checks if a given point or polygon intersects with any world heritage site, buffer zone or other polygon or sites of interest. Returns 
        """


if __name__ == "__main__":
    from fastmcp.server.server import Transport
    if MCP_TRANSPORT == "http" or MCP_TRANSPORT == "sse":
        vector_mcp.run(transport=cast("Transport", MCP_TRANSPORT), port=MCP_PORT)
    else:
        vector_mcp.run(transport=cast("Transport", MCP_TRANSPORT) if MCP_TRANSPORT else None)