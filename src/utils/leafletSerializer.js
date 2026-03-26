import L from 'leaflet'

const EARTH_RADIUS_METERS = 6378137
const CIRCLE_SEGMENTS = 64

function destinationPoint(lat, lng, distanceMeters, bearingDegrees) {
    const angularDistance = distanceMeters / EARTH_RADIUS_METERS
    const bearing = (bearingDegrees * Math.PI) / 180
    const latitude = (lat * Math.PI) / 180
    const longitude = (lng * Math.PI) / 180

    const nextLatitude = Math.asin(
        Math.sin(latitude) * Math.cos(angularDistance)
        + Math.cos(latitude) * Math.sin(angularDistance) * Math.cos(bearing)
    )

    const nextLongitude = longitude + Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitude),
        Math.cos(angularDistance) - Math.sin(latitude) * Math.sin(nextLatitude)
    )

    return [
        (nextLongitude * 180) / Math.PI,
        (nextLatitude * 180) / Math.PI,
    ]
}

function circleToPolygon(layer) {
    const center = layer.getLatLng()
    const radiusMeters = layer.getRadius()
    const ring = []

    for (let index = 0; index < CIRCLE_SEGMENTS; index += 1) {
        const bearing = (index / CIRCLE_SEGMENTS) * 360
        ring.push(destinationPoint(center.lat, center.lng, radiusMeters, bearing))
    }

    ring.push(ring[0])

    return {
        type: 'Feature',
        properties: {
            radiusMeters: Number(radiusMeters.toFixed(2)),
        },
        geometry: {
            type: 'Polygon',
            coordinates: [ring],
        },
    }
}

function normalizeGeoJson(geoJson) {
    if (!geoJson?.type) return null

    if (geoJson.type === 'Feature' || geoJson.type === 'FeatureCollection') {
        return geoJson
    }

    return {
        type: 'Feature',
        properties: {},
        geometry: geoJson,
    }
}

export function serializeLeafletLayer(layer) {
    if (!layer) return null

    if (layer instanceof L.Circle) {
        return circleToPolygon(layer)
    }

    return normalizeGeoJson(layer.toGeoJSON())
}
