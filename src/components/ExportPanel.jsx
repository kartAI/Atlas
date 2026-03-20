import { useEffect, useState } from 'react'
import {
    countLayerFeatures,
    downloadLayersAsGeoJSON,
    downloadLayersAsJSON,
    downloadLayersAsPDF,
    downloadLayersAsPNG,
} from '../utils/exportUtils'

const EXPORT_ACTIONS = {
    geojson: {
        label: 'GeoJSON',
        run: downloadLayersAsGeoJSON,
    },
    json: {
        label: 'JSON',
        run: downloadLayersAsJSON,
    },
    pdf: {
        label: 'PDF',
        run: downloadLayersAsPDF,
    },
    png: {
        label: 'PNG',
        run: downloadLayersAsPNG,
    },
}

export function ExportPanel({ drawnLayers = [], layers = [] }) {
    const exportableLayers = drawnLayers.filter(layer => layer?.geoJson)
    const [selectedIds, setSelectedIds] = useState([])
    const [isExporting, setIsExporting] = useState(false)
    const [statusMessage, setStatusMessage] = useState('')
    const activeBaseLayer = layers.find(l => l?.visible)

    useEffect(() => {
        const exportableIds = drawnLayers
            .filter(layer => layer?.geoJson)
            .map(layer => layer.id)

        setSelectedIds(previousIds => {
            const nextIds = previousIds.filter(id => exportableIds.includes(id))
            const previousIdSet = new Set(previousIds)

            exportableIds.forEach(id => {
                if (!previousIdSet.has(id)) {
                    nextIds.push(id)
                }
            })

            return nextIds
        })
    }, [drawnLayers])

    const selectedLayers = exportableLayers.filter(layer => selectedIds.includes(layer.id))

    function toggleLayerSelection(layerId) {
        setSelectedIds(previousIds =>
            previousIds.includes(layerId)
                ? previousIds.filter(id => id !== layerId)
                : [...previousIds, layerId]
        )
    }

    function selectLayers(nextIds) {
        setSelectedIds(nextIds)
    }

    async function handleExport(format) {
        const action = EXPORT_ACTIONS[format]

        if (!action || selectedLayers.length === 0) return

        setIsExporting(true)
        setStatusMessage('')

        try {
            await Promise.resolve(
                action.run(selectedLayers, {
                    filenamePrefix: 'kartlag-eksport',
                    basemapUrl: activeBaseLayer?.url || null,
                })
            )
            setStatusMessage(`${action.label}-eksport startet.`)
        } catch (error) {
            setStatusMessage(
                error instanceof Error
                    ? error.message
                    : 'Eksporten kunne ikke fullføres.'
            )
        } finally {
            setIsExporting(false)
        }
    }

    if (exportableLayers.length === 0) {
        return (
            <div className="export-empty">
                <p>Ingen kartlag er klare for eksport ennå.</p>
                <p>Tegn eller generer geometri i kartet, så vises lagene her.</p>
            </div>
        )
    }

    return (
        <div className="export-panel">
            <div className="export-card">
                <h3 className="export-title">Eksporter</h3>
                <p className="export-subtitle">
                    Velg ett eller flere kartlag og eksporter dem som geodata eller som
                    grafisk kartskisse.
                </p>
                <p className="export-hint">
                    GeoJSON og JSON gir rådata. PNG og PDF lager en visuell eksport av de
                    valgte lagene.
                </p>
            </div>

            <div className="export-card">
                <div className="export-toolbar">
                    <button
                        type="button"
                        className="export-toolbar-btn"
                        onClick={() => selectLayers(exportableLayers.map(layer => layer.id))}
                    >
                        Velg alle
                    </button>
                    <button
                        type="button"
                        className="export-toolbar-btn"
                        onClick={() => selectLayers(exportableLayers.filter(layer => layer.visible).map(layer => layer.id))}
                    >
                        Kun synlige
                    </button>
                    <button
                        type="button"
                        className="export-toolbar-btn"
                        onClick={() => selectLayers([])}
                    >
                        Fjern valg
                    </button>
                </div>

                <div className="export-summary">
                    {selectedLayers.length} av {exportableLayers.length} lag valgt
                </div>

                <ul className="export-list">
                    {exportableLayers.map(layer => {
                        const featureCount = countLayerFeatures(layer)
                        const meta = [
                            layer.shape || 'Lag',
                            layer.visible ? 'Synlig' : 'Skjult',
                            `${featureCount} ${featureCount === 1 ? 'objekt' : 'objekter'}`,
                        ].join(' • ')

                        return (
                            <li key={layer.id}>
                                <label className="export-layer">
                                    <input
                                        className="export-checkbox"
                                        type="checkbox"
                                        checked={selectedIds.includes(layer.id)}
                                        onChange={() => toggleLayerSelection(layer.id)}
                                    />
                                    <span className="export-layer-copy">
                                        <span className="export-layer-name">{layer.name}</span>
                                        <span className="export-layer-meta">{meta}</span>
                                    </span>
                                </label>
                            </li>
                        )
                    })}
                </ul>
            </div>

            <div className="export-card">
                <div className="export-actions">
                    {Object.entries(EXPORT_ACTIONS).map(([format, action]) => (
                        <button
                            key={format}
                            type="button"
                            className="export-format-btn"
                            disabled={isExporting || selectedLayers.length === 0}
                            onClick={() => handleExport(format)}
                        >
                            {action.label}
                        </button>
                    ))}
                </div>

                {statusMessage && (
                    <p className="export-status">{statusMessage}</p>
                )}
            </div>
        </div>
    )
}
