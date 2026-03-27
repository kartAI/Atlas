const EXPORT_SCALE = 2
const EXPORT_LOGICAL_WIDTH = 1600
const EXPORT_LOGICAL_HEIGHT = 1000
const EXPORT_WIDTH = EXPORT_LOGICAL_WIDTH * EXPORT_SCALE
const EXPORT_HEIGHT = EXPORT_LOGICAL_HEIGHT * EXPORT_SCALE
const EXPORT_COLORS = [
    '#00e5ff',
    '#ff3d71',
    '#39ff14',
    '#ffab00',
    '#d500f9',
    '#00e676',
    '#ff6d00',
    '#536dfe',
]
const MIN_FEATURE_PIXELS = 20

// ── Filename helpers ──

function padNumber(value) {
    return String(value).padStart(2, '0')
}

function toFilenameSafeText(value) {
    return String(value ?? '')
        .trim()
        .toLowerCase()
        .replaceAll('\u00e6', 'ae')
        .replaceAll('\u00f8', 'o')
        .replaceAll('\u00e5', 'a')
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')
}

function getTimestampSuffix(date = new Date()) {
    return [
        date.getFullYear(),
        padNumber(date.getMonth() + 1),
        padNumber(date.getDate()),
    ].join('-') + '_' + [
        padNumber(date.getHours()),
        padNumber(date.getMinutes()),
        padNumber(date.getSeconds()),
    ].join('-')
}

function resolveFilename({ filename, filenamePrefix = 'kartlag-eksport', extension }) {
    if (filename) return filename

    const prefix = sanitizeFilenameSegment(filenamePrefix, 'kartlag-eksport')
    return `${prefix}-${getTimestampSuffix()}.${extension}`
}

function formatExportDate(date = new Date()) {
    return new Intl.DateTimeFormat('nb-NO', {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date)
}

// ── Feature / layer helpers ──

function normalizeFeature(geoJson) {
    if (!geoJson?.type) return null

    if (geoJson.type === 'Feature') return geoJson

    if (geoJson.type === 'FeatureCollection') {
        return geoJson.features
            .flatMap(feature => normalizeFeature(feature))
            .filter(Boolean)
    }

    return {
        type: 'Feature',
        properties: {},
        geometry: geoJson,
    }
}

function decorateFeature(feature, layer, featureIndex = 0) {
    if (!feature?.geometry) return null

    return {
        ...feature,
        id: feature.id ?? `${layer.id}-${featureIndex + 1}`,
        properties: {
            ...(feature.properties ?? {}),
            exportLayerId: layer.id,
            exportLayerName: layer.name,
            exportLayerShape: layer.shape,
            exportLayerVisible: layer.visible ?? true,
        },
    }
}

function getLayerFeatures(layer) {
    const normalized = normalizeFeature(layer?.geoJson)

    if (!normalized) return []

    if (Array.isArray(normalized)) {
        return normalized
            .map((feature, index) => decorateFeature(feature, layer, index))
            .filter(Boolean)
    }

    return [decorateFeature(normalized, layer)].filter(Boolean)
}

function getExportableLayers(layers = []) {
    return layers.filter(layer => layer?.geoJson)
}

function createFeatureCollection(layers = []) {
    return {
        type: 'FeatureCollection',
        features: getExportableLayers(layers).flatMap(getLayerFeatures),
    }
}

function createJsonExport(layers = []) {
    const exportableLayers = getExportableLayers(layers)

    return {
        exportedAt: new Date().toISOString(),
        layerCount: exportableLayers.length,
        featureCount: exportableLayers.flatMap(getLayerFeatures).length,
        layers: exportableLayers.map(layer => ({
            id: layer.id,
            name: layer.name,
            shape: layer.shape,
            visible: layer.visible ?? true,
            featureCount: getLayerFeatures(layer).length,
            geoJson: layer.geoJson,
        })),
    }
}

// ── Download helpers ──

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(url)
}

function downloadJsonFile(data, options) {
    const filename = resolveFilename(options)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: options.mimeType })
    downloadBlob(blob, filename)
}

// ── Geometry helpers ──

function forEachCoordinate(geometry, callback) {
    if (!geometry?.type) return

    switch (geometry.type) {
        case 'Point':
            callback(geometry.coordinates)
            break
        case 'MultiPoint':
        case 'LineString':
            geometry.coordinates.forEach(callback)
            break
        case 'MultiLineString':
        case 'Polygon':
            geometry.coordinates.forEach(line => line.forEach(callback))
            break
        case 'MultiPolygon':
            geometry.coordinates.forEach(polygon =>
                polygon.forEach(ring => ring.forEach(callback))
            )
            break
        case 'GeometryCollection':
            geometry.geometries.forEach(child => forEachCoordinate(child, callback))
            break
        default:
            break
    }
}

function getGeometryBounds(features) {
    let minX = Number.POSITIVE_INFINITY
    let minY = Number.POSITIVE_INFINITY
    let maxX = Number.NEGATIVE_INFINITY
    let maxY = Number.NEGATIVE_INFINITY

    features.forEach(feature => {
        forEachCoordinate(feature.geometry, coordinate => {
            const [x, y] = coordinate
            minX = Math.min(minX, x)
            minY = Math.min(minY, y)
            maxX = Math.max(maxX, x)
            maxY = Math.max(maxY, y)
        })
    })

    if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
        return { minX: 5, minY: 58, maxX: 15, maxY: 71 }
    }

    if (Math.abs(maxX - minX) < 1e-9) {
        minX -= 0.01
        maxX += 0.01
    }

    if (Math.abs(maxY - minY) < 1e-9) {
        minY -= 0.01
        maxY += 0.01
    }

    return { minX, minY, maxX, maxY }
}

// ── Web Mercator projection ──

function lngToMercatorX(lng) {
    return (lng + 180) / 360
}

function latToMercatorY(lat) {
    const latRad = lat * Math.PI / 180
    return (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2
}

function mercatorXToLng(mx) {
    return mx * 360 - 180
}

function mercatorYToLat(my) {
    return Math.atan(Math.sinh(Math.PI * (1 - 2 * my))) * 180 / Math.PI
}

function createMercatorProjector(bounds, frame, padding = 0.6) {
    const mx0 = lngToMercatorX(bounds.minX)
    const mx1 = lngToMercatorX(bounds.maxX)
    const my0 = latToMercatorY(bounds.maxY)
    const my1 = latToMercatorY(bounds.minY)

    const spanX = mx1 - mx0
    const spanY = my1 - my0
    const padX = spanX * padding
    const padY = spanY * padding

    const pMinX = mx0 - padX
    const pMaxX = mx1 + padX
    const pMinY = my0 - padY
    const pMaxY = my1 + padY

    const pSpanX = pMaxX - pMinX
    const pSpanY = pMaxY - pMinY
    const scale = Math.min(frame.width / pSpanX, frame.height / pSpanY)
    const offsetX = frame.x + (frame.width - pSpanX * scale) / 2
    const offsetY = frame.y + (frame.height - pSpanY * scale) / 2

    return {
        project([lng, lat]) {
            const mx = lngToMercatorX(lng)
            const my = latToMercatorY(lat)
            return {
                x: offsetX + (mx - pMinX) * scale,
                y: offsetY + (my - pMinY) * scale,
            }
        },
        projectMercator(mx, my) {
            return {
                x: offsetX + (mx - pMinX) * scale,
                y: offsetY + (my - pMinY) * scale,
            }
        },
        // Geographic bounds of the entire plot frame (for tile coverage)
        visibleBounds: {
            minX: mercatorXToLng((frame.x - offsetX) / scale + pMinX),
            maxX: mercatorXToLng((frame.x + frame.width - offsetX) / scale + pMinX),
            maxY: mercatorYToLat((frame.y - offsetY) / scale + pMinY),
            minY: mercatorYToLat((frame.y + frame.height - offsetY) / scale + pMinY),
        },
    }
}

// ── Tile helpers ──

function lngToTileX(lng, zoom) {
    return Math.floor(lngToMercatorX(lng) * (1 << zoom))
}

function latToTileY(lat, zoom) {
    return Math.floor(latToMercatorY(lat) * (1 << zoom))
}

function buildTileUrl(template, z, x, y) {
    return template
        .replace('{z}', String(z))
        .replace('{x}', String(x))
        .replace('{y}', String(y))
}

function calculateTileZoom(bounds, maxTiles = 100) {
    for (let z = 15; z >= 1; z--) {
        const x0 = lngToTileX(bounds.minX, z)
        const x1 = lngToTileX(bounds.maxX, z)
        const y0 = latToTileY(bounds.maxY, z)
        const y1 = latToTileY(bounds.minY, z)
        const count = (x1 - x0 + 1) * (y1 - y0 + 1)
        if (count <= maxTiles && count > 0) return z
    }
    return 3
}

async function fetchBasemapTiles(basemapUrl, projector) {
    if (!basemapUrl) return []

    const vb = projector.visibleBounds
    const zoom = calculateTileZoom(vb)
    const x0 = lngToTileX(vb.minX, zoom) - 1
    const x1 = lngToTileX(vb.maxX, zoom) + 1
    const y0 = latToTileY(vb.maxY, zoom) - 1
    const y1 = latToTileY(vb.minY, zoom) + 1
    const n = 1 << zoom

    const tilePromises = []
    for (let ty = Math.max(y0, 0); ty <= Math.min(y1, n - 1); ty++) {
        for (let tx = x0; tx <= x1; tx++) {
            const wrappedX = ((tx % n) + n) % n
            const url = buildTileUrl(basemapUrl, zoom, wrappedX, ty)
            const capturedTx = tx
            const capturedTy = ty
            tilePromises.push(
                fetch(url)
                    .then(r => r.ok ? r.blob() : null)
                    .then(blob => blob ? createImageBitmap(blob) : null)
                    .then(img => {
                        if (!img) return null
                        const topLeft = projector.projectMercator(capturedTx / n, capturedTy / n)
                        const bottomRight = projector.projectMercator((capturedTx + 1) / n, (capturedTy + 1) / n)
                        return { img, x: topLeft.x, y: topLeft.y, w: bottomRight.x - topLeft.x, h: bottomRight.y - topLeft.y }
                    })
                    .catch(() => null)
            )
        }
    }

    const results = await Promise.allSettled(tilePromises)
    return results
        .filter(r => r.status === 'fulfilled' && r.value)
        .map(r => r.value)
}

// ── Canvas drawing helpers ──

function drawExportBackground(ctx, w, h) {
    const gradient = ctx.createLinearGradient(0, 0, w, h)
    gradient.addColorStop(0, '#eff6f2')
    gradient.addColorStop(1, '#dfece5')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, w, h)

    ctx.save()
    ctx.globalAlpha = 0.42
    ctx.fillStyle = '#bddbcc'
    ctx.beginPath()
    ctx.arc(1430, 110, 180, 0, Math.PI * 2)
    ctx.fill()

    ctx.globalAlpha = 0.45
    ctx.fillStyle = '#c7e6d4'
    ctx.beginPath()
    ctx.arc(118, 922, 210, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
}

function drawExportHeader(ctx, layerCount, featureCount) {
    ctx.fillStyle = '#17352d'
    ctx.font = '700 54px "Segoe UI", Arial, sans-serif'
    ctx.fillText('Eksporterte kartlag', 86, 98)

    ctx.fillStyle = '#49645d'
    ctx.font = '24px "Segoe UI", Arial, sans-serif'
    ctx.fillText(`Generert ${formatExportDate()}`, 86, 136)

    ctx.font = '22px "Segoe UI", Arial, sans-serif'
    const label = featureCount === 1 ? 'geometri' : 'geometrier'
    ctx.fillText(`${layerCount} valgte lag \u2022 ${featureCount} ${label}`, 86, 172)
}

function drawExportPanels(ctx) {
    ctx.fillStyle = '#ffffff'
    ctx.strokeStyle = '#cdded5'
    ctx.lineWidth = 1

    ctx.beginPath()
    ctx.roundRect(330, 194, 940, 704, 28)
    ctx.fill()
    ctx.stroke()

    ctx.fillStyle = '#17352d'
    ctx.font = '700 26px "Segoe UI", Arial, sans-serif'
    ctx.fillText('Kartskisse', 364, 246)
}

function drawExportGrid(ctx, frame) {
    ctx.strokeStyle = '#d8e6df'
    ctx.lineWidth = 1

    for (let i = 0; i < 5; i++) {
        const x = frame.x + (frame.width / 4) * i
        ctx.beginPath()
        ctx.moveTo(x, frame.y)
        ctx.lineTo(x, frame.y + frame.height)
        ctx.stroke()
    }

    for (let i = 0; i < 5; i++) {
        const y = frame.y + (frame.height / 4) * i
        ctx.beginPath()
        ctx.moveTo(frame.x, y)
        ctx.lineTo(frame.x + frame.width, y)
        ctx.stroke()
    }

    ctx.strokeStyle = '#d5e3dc'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.roundRect(frame.x, frame.y, frame.width, frame.height, 22)
    ctx.stroke()
}

const LABEL_COLOR_BOX = 20

function getFeaturePixelExtent(feature, projector) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    let cx = 0, cy = 0, count = 0

    forEachCoordinate(feature.geometry, coord => {
        const pt = projector.project(coord)
        minX = Math.min(minX, pt.x)
        minY = Math.min(minY, pt.y)
        maxX = Math.max(maxX, pt.x)
        maxY = Math.max(maxY, pt.y)
        cx += pt.x
        cy += pt.y
        count++
    })

    if (count === 0) return null

    return {
        size: Math.max(maxX - minX, maxY - minY),
        cx: cx / count,
        cy: cy / count,
    }
}

function drawFeatureMarker(ctx, cx, cy, color) {
    ctx.save()

    ctx.fillStyle = color
    ctx.globalAlpha = 0.22
    ctx.beginPath()
    ctx.arc(cx, cy, 20, 0, Math.PI * 2)
    ctx.fill()

    ctx.globalAlpha = 0.9
    ctx.strokeStyle = color
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.arc(cx, cy, 10, 0, Math.PI * 2)
    ctx.stroke()

    ctx.globalAlpha = 1
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy, 6, 0, Math.PI * 2)
    ctx.fill()

    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(cx, cy, 2.5, 0, Math.PI * 2)
    ctx.fill()

    ctx.restore()
}

function getLayerCentroid(layer, projector) {
    const features = getLayerFeatures(layer)
    let cx = 0, cy = 0, count = 0
    features.forEach(f => {
        forEachCoordinate(f.geometry, coord => {
            const pt = projector.project(coord)
            cx += pt.x
            cy += pt.y
            count++
        })
    })
    if (count === 0) return null
    return { x: cx / count, y: cy / count }
}

function distributeLabelsY(entries, plotFrame) {
    if (!entries.length) return entries

    const topY = 234
    const bottomY = plotFrame.y + plotFrame.height - 20
    const count = entries.length

    entries.sort((a, b) => a.centroid.y - b.centroid.y)

    if (count === 1) {
        return entries.map(e => ({ ...e, labelY: topY + (bottomY - topY) / 2 }))
    }

    return entries.map((entry, i) => ({
        ...entry,
        labelY: topY + (i / (count - 1)) * (bottomY - topY),
    }))
}

function drawLeaderLabels(ctx, layers, colorByLayer, projector, plotFrame) {
    const mapCenterX = plotFrame.x + plotFrame.width / 2
    const leftLabelX = 40
    const rightLabelX = 1560
    const leftLabels = []
    const rightLabels = []

    layers.forEach(layer => {
        const centroid = getLayerCentroid(layer, projector)
        if (!centroid) return
        const color = colorByLayer.get(layer.id)
        const features = getLayerFeatures(layer)
        const entry = { layer, color, centroid, features }
        if (centroid.x < mapCenterX) leftLabels.push(entry)
        else rightLabels.push(entry)
    })

    const placedLeft = distributeLabelsY(leftLabels, plotFrame)
    const placedRight = distributeLabelsY(rightLabels, plotFrame)

    ctx.font = '600 18px "Segoe UI", Arial, sans-serif'

    placedLeft.forEach(entry => {
        const y = entry.labelY
        const textY = y + 12

        ctx.fillStyle = entry.color
        ctx.beginPath()
        ctx.roundRect(leftLabelX, y, LABEL_COLOR_BOX, LABEL_COLOR_BOX, 4)
        ctx.fill()

        ctx.fillStyle = '#17352d'
        const name = entry.layer.name || 'Lag'
        const label = name.length > 22 ? name.slice(0, 20) + '\u2026' : name
        const textLeft = leftLabelX + LABEL_COLOR_BOX + 8
        ctx.fillText(label, textLeft, textY)
        const textWidth = ctx.measureText(label).width

        const underlineY = textY + 5
        ctx.save()
        ctx.strokeStyle = '#17352d'
        ctx.lineWidth = 1.5
        ctx.globalAlpha = 0.5
        ctx.beginPath()
        ctx.moveTo(textLeft, underlineY)
        ctx.lineTo(textLeft + textWidth, underlineY)
        ctx.lineTo(entry.centroid.x, entry.centroid.y)
        ctx.stroke()

        ctx.fillStyle = '#17352d'
        ctx.beginPath()
        ctx.arc(entry.centroid.x, entry.centroid.y, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
    })

    placedRight.forEach(entry => {
        const y = entry.labelY
        const textY = y + 12

        ctx.font = '600 18px "Segoe UI", Arial, sans-serif'
        const name = entry.layer.name || 'Lag'
        const label = name.length > 22 ? name.slice(0, 20) + '\u2026' : name
        const textWidth = ctx.measureText(label).width

        const boxX = rightLabelX - LABEL_COLOR_BOX
        ctx.fillStyle = entry.color
        ctx.beginPath()
        ctx.roundRect(boxX, y, LABEL_COLOR_BOX, LABEL_COLOR_BOX, 4)
        ctx.fill()

        const textRight = boxX - 8
        const textLeft = textRight - textWidth
        ctx.fillStyle = '#17352d'
        ctx.fillText(label, textLeft, textY)

        const underlineY = textY + 5
        ctx.save()
        ctx.strokeStyle = '#17352d'
        ctx.lineWidth = 1.5
        ctx.globalAlpha = 0.5
        ctx.beginPath()
        ctx.moveTo(textRight, underlineY)
        ctx.lineTo(textLeft, underlineY)
        ctx.lineTo(entry.centroid.x, entry.centroid.y)
        ctx.stroke()

        ctx.fillStyle = '#17352d'
        ctx.beginPath()
        ctx.arc(entry.centroid.x, entry.centroid.y, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
    })
}

function drawCanvasGeometry(ctx, geometry, color, projector) {
    if (!geometry?.type) return

    const pointRadius = 7

    switch (geometry.type) {
        case 'Point': {
            const pt = projector.project(geometry.coordinates)
            ctx.save()
            ctx.fillStyle = color
            ctx.globalAlpha = 0.18
            ctx.beginPath()
            ctx.arc(pt.x, pt.y, pointRadius + 4, 0, Math.PI * 2)
            ctx.fill()
            ctx.globalAlpha = 1
            ctx.beginPath()
            ctx.arc(pt.x, pt.y, pointRadius, 0, Math.PI * 2)
            ctx.fill()
            ctx.restore()
            break
        }
        case 'MultiPoint':
            geometry.coordinates.forEach(coords =>
                drawCanvasGeometry(ctx, { type: 'Point', coordinates: coords }, color, projector)
            )
            break
        case 'LineString': {
            ctx.save()
            ctx.strokeStyle = color
            ctx.lineWidth = 5
            ctx.lineCap = 'round'
            ctx.lineJoin = 'round'
            ctx.beginPath()
            geometry.coordinates.forEach((coord, i) => {
                const pt = projector.project(coord)
                if (i === 0) ctx.moveTo(pt.x, pt.y)
                else ctx.lineTo(pt.x, pt.y)
            })
            ctx.stroke()
            ctx.restore()
            break
        }
        case 'MultiLineString':
            geometry.coordinates.forEach(line =>
                drawCanvasGeometry(ctx, { type: 'LineString', coordinates: line }, color, projector)
            )
            break
        case 'Polygon': {
            ctx.save()
            ctx.beginPath()
            geometry.coordinates.forEach(ring => {
                ring.forEach((coord, i) => {
                    const pt = projector.project(coord)
                    if (i === 0) ctx.moveTo(pt.x, pt.y)
                    else ctx.lineTo(pt.x, pt.y)
                })
                ctx.closePath()
            })
            ctx.fillStyle = color
            ctx.globalAlpha = 0.18
            ctx.fill('evenodd')
            ctx.globalAlpha = 1
            ctx.strokeStyle = color
            ctx.lineWidth = 4
            ctx.lineJoin = 'round'
            ctx.stroke()
            ctx.restore()
            break
        }
        case 'MultiPolygon':
            geometry.coordinates.forEach(polygon =>
                drawCanvasGeometry(ctx, { type: 'Polygon', coordinates: polygon }, color, projector)
            )
            break
        case 'GeometryCollection':
            geometry.geometries.forEach(child =>
                drawCanvasGeometry(ctx, child, color, projector)
            )
            break
        default:
            break
    }
}


function drawExportFooter(ctx) {
    ctx.fillStyle = '#49645d'
    ctx.font = '18px "Segoe UI", Arial, sans-serif'
    ctx.fillText('PNG og PDF er grafiske eksportfiler basert p\u00e5 valgte lag.', 86, 944)
    ctx.fillText('GeoJSON og JSON inneholder de samme geodataene som eksporteres fra sidepanelet.', 86, 972)
}

// ── Canvas export engine ──

async function createExportCanvas(layers, basemapUrl) {
    const exportableLayers = getExportableLayers(layers)
    const featureCollection = createFeatureCollection(exportableLayers)
    const features = featureCollection.features

    if (!features.length) {
        throw new Error('Ingen kartlag med geometri er valgt for eksport.')
    }

    const canvas = document.createElement('canvas')
    canvas.width = EXPORT_WIDTH
    canvas.height = EXPORT_HEIGHT

    const ctx = canvas.getContext('2d', { alpha: false, willReadFrequently: true })
    if (!ctx) throw new Error('Kunne ikke opprette canvas-kontekst.')
    ctx.scale(EXPORT_SCALE, EXPORT_SCALE)

    const plotFrame = { x: 354, y: 214, width: 892, height: 660 }
    const bounds = getGeometryBounds(features)
    const projector = createMercatorProjector(bounds, plotFrame)
    const colorByLayer = new Map(
        exportableLayers.map((layer, index) => [
            layer.id,
            EXPORT_COLORS[index % EXPORT_COLORS.length],
        ])
    )

    drawExportBackground(ctx, EXPORT_LOGICAL_WIDTH, EXPORT_LOGICAL_HEIGHT)
    drawExportHeader(ctx, exportableLayers.length, features.length)
    drawExportPanels(ctx)
    drawExportGrid(ctx, plotFrame)

    // Basemap tiles (clipped to plot frame)
    if (basemapUrl) {
        try {
            const tiles = await fetchBasemapTiles(basemapUrl, projector)
            if (tiles.length > 0) {
                ctx.save()
                ctx.beginPath()
                ctx.roundRect(plotFrame.x, plotFrame.y, plotFrame.width, plotFrame.height, 22)
                ctx.clip()
                tiles.forEach(t => ctx.drawImage(t.img, t.x, t.y, t.w, t.h))
                ctx.restore()
            }
        } catch (error) {
            console.warn('[Export] Tile fetch failed, continuing without basemap:', error)
        }
    }

    // Geometry features (clipped to plot frame)
    ctx.save()
    ctx.beginPath()
    ctx.roundRect(plotFrame.x, plotFrame.y, plotFrame.width, plotFrame.height, 22)
    ctx.clip()
    features.forEach(feature => {
        const color = colorByLayer.get(feature.properties?.exportLayerId) || EXPORT_COLORS[0]
        const extent = getFeaturePixelExtent(feature, projector)
        drawCanvasGeometry(ctx, feature.geometry, color, projector)
        if (extent && extent.size < MIN_FEATURE_PIXELS) {
            drawFeatureMarker(ctx, extent.cx, extent.cy, color)
        }
    })
    ctx.restore()

    drawLeaderLabels(ctx, exportableLayers, colorByLayer, projector, plotFrame)
    drawExportFooter(ctx)

    return canvas
}

// ── Canvas \u2192 Blob ──

function canvasToBlob(canvas, type) {
    return new Promise((resolve, reject) => {
        canvas.toBlob(blob => {
            if (!blob) {
                reject(new Error('Kunne ikke opprette eksportfil.'))
                return
            }

            resolve(blob)
        }, type)
    })
}

// ── PDF builder ──

function concatUint8Arrays(chunks, totalLength) {
    const result = new Uint8Array(totalLength)
    let offset = 0

    chunks.forEach(chunk => {
        result.set(chunk, offset)
        offset += chunk.length
    })

    return result
}

function escapePdfString(value) {
    return String(value ?? '')
        .replaceAll('\\', '\\\\')
        .replaceAll('(', '\\(')
        .replaceAll(')', '\\)')
}

function formatPdfDate(date = new Date()) {
    return [
        date.getFullYear(),
        padNumber(date.getMonth() + 1),
        padNumber(date.getDate()),
        padNumber(date.getHours()),
        padNumber(date.getMinutes()),
        padNumber(date.getSeconds()),
    ].join('')
}

function base64ToUint8Array(base64Value) {
    const binary = window.atob(base64Value)
    const bytes = new Uint8Array(binary.length)

    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index)
    }

    return bytes
}

function createPdfDocument(jpegDataUrl, imageWidth, imageHeight, title) {
    const base64Value = jpegDataUrl.replace(/^data:image\/jpeg;base64,/, '')
    const jpegBytes = base64ToUint8Array(base64Value)
    const encoder = new TextEncoder()
    const page =
        imageWidth >= imageHeight
            ? { width: 842, height: 595 }
            : { width: 595, height: 842 }
    const margin = 30
    const scale = Math.min(
        (page.width - margin * 2) / imageWidth,
        (page.height - margin * 2) / imageHeight
    )
    const drawWidth = Number((imageWidth * scale).toFixed(2))
    const drawHeight = Number((imageHeight * scale).toFixed(2))
    const offsetX = Number(((page.width - drawWidth) / 2).toFixed(2))
    const offsetY = Number(((page.height - drawHeight) / 2).toFixed(2))
    const contentStream = `q\n${drawWidth} 0 0 ${drawHeight} ${offsetX} ${offsetY} cm\n/Im0 Do\nQ\n`

    const chunks = []
    const offsets = [0]
    let totalLength = 0

    function pushText(text) {
        const bytes = encoder.encode(text)
        chunks.push(bytes)
        totalLength += bytes.length
    }

    function pushBytes(bytes) {
        chunks.push(bytes)
        totalLength += bytes.length
    }

    pushText('%PDF-1.3\n%\u00e2\u00e3\u00cf\u00d3\n')

    offsets[1] = totalLength
    pushText('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')

    offsets[2] = totalLength
    pushText('2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n')

    offsets[3] = totalLength
    pushText(`3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${page.width} ${page.height}] /Resources << /ProcSet [/PDF /ImageC] /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\nendobj\n`)

    offsets[4] = totalLength
    pushText(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`)
    pushBytes(jpegBytes)
    pushText('\nendstream\nendobj\n')

    offsets[5] = totalLength
    pushText(`5 0 obj\n<< /Length ${encoder.encode(contentStream).length} >>\nstream\n${contentStream}endstream\nendobj\n`)

    offsets[6] = totalLength
    pushText(`6 0 obj\n<< /Title (${escapePdfString(title)}) /Creator (GeoMCP SDK) /Producer (GeoMCP SDK) /CreationDate (D:${formatPdfDate()}) >>\nendobj\n`)

    const xrefStart = totalLength
    pushText('xref\n0 7\n0000000000 65535 f \n')

    for (let index = 1; index <= 6; index += 1) {
        pushText(`${String(offsets[index]).padStart(10, '0')} 00000 n \n`)
    }

    pushText(`trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n${xrefStart}\n%%EOF`)

    return concatUint8Arrays(chunks, totalLength)
}

// ── Public API ──

export function sanitizeFilenameSegment(value, fallback = 'eksport') {
    return toFilenameSafeText(value) || fallback
}

export function countLayerFeatures(layer) {
    return getLayerFeatures(layer).length
}

export function downloadLayersAsGeoJSON(layers, options = {}) {
    downloadJsonFile(createFeatureCollection(layers), {
        ...options,
        extension: 'geojson',
        mimeType: 'application/geo+json',
    })
}

export function downloadLayersAsJSON(layers, options = {}) {
    downloadJsonFile(createJsonExport(layers), {
        ...options,
        extension: 'json',
        mimeType: 'application/json',
    })
}

export async function downloadLayersAsPNG(layers, options = {}) {
    const canvas = await createExportCanvas(layers, options.basemapUrl)
    const filename = resolveFilename({ ...options, extension: 'png' })
    const blob = await canvasToBlob(canvas, 'image/png')
    downloadBlob(blob, filename)
}

export async function downloadLayersAsPDF(layers, options = {}) {
    const canvas = await createExportCanvas(layers, options.basemapUrl)
    const filename = resolveFilename({ ...options, extension: 'pdf' })
    const jpegDataUrl = canvas.toDataURL('image/jpeg', 0.92)
    const pdfBytes = createPdfDocument(jpegDataUrl, canvas.width, canvas.height, 'Kartlag eksport')
    downloadBlob(new Blob([pdfBytes], { type: 'application/pdf' }), filename)
}
