import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEye, faEyeSlash, faTrash, faDownload } from '@fortawesome/free-solid-svg-icons';

export function KartlagPanel({ drawnLayers = [], onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer }) {
    function toFeatureCollection(layer) {
        return {
            ...layer.geoJson,
            properties: { ...layer.geoJson.properties, name: layer.name }
        };
    }

    function downloadGeoJson(data, filename) {
        const blob = new Blob(
            [JSON.stringify(data, null, 2)],
            { type: 'application/json' }
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    function getLayerFilename(name) {
        const sanitizedName = name
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '') || 'tegning';

        return `${sanitizedName}.geojson`;
    }

    function handleLayerExport(layer) {
        if (!layer.geoJson) return;

        downloadGeoJson(
            {
                type: 'FeatureCollection',
                features: [toFeatureCollection(layer)]
            },
            getLayerFilename(layer.name)
        );
    }

    function handleExport() {
        const featureCollection = {
            type: 'FeatureCollection',
            features: drawnLayers
                .filter(l => l.geoJson)
                .map(toFeatureCollection)
        };

        downloadGeoJson(featureCollection, 'tegninger.geojson');
    }

    if (drawnLayers.length === 0) {
        return (
            <div className="kartlag-empty">
                <p>Ingen tegninger ennå.</p>
                <p>Bruk tegneverktøyet på kartet for å legge til former.</p>
            </div>
        );
    }

    return (
        <div className="kartlag-panel">
            <h3 className="kartlag-title">Tegninger</h3>
            <ul className="kartlag-list">
                {drawnLayers.map(layer => (
                    <li key={layer.id} className="kartlag-item">
                        <span
                            className="kartlag-name"
                            onClick={() => onFlyToLayer?.(layer.id)}
                            title="Klikk for å gå til"
                        >
                            {layer.name}
                        </span>
                        <div className="kartlag-actions">
                            <button
                                className="kartlag-btn"
                                title="Last ned"
                                onClick={() => handleLayerExport(layer)}
                                disabled={!layer.geoJson}
                            >
                                <FontAwesomeIcon icon={faDownload} />
                            </button>
                            <button
                                className="kartlag-btn"
                                title={layer.visible ? 'Skjul' : 'Vis'}
                                onClick={() => onSetDrawnLayerVisible(layer.id, !layer.visible)}
                            >
                                <FontAwesomeIcon icon={layer.visible ? faEye : faEyeSlash} />
                            </button>
                            <button
                                className="kartlag-btn kartlag-btn--delete"
                                title="Slett"
                                onClick={() => onRemoveDrawnLayer(layer.id)}
                            >
                                <FontAwesomeIcon icon={faTrash} />
                            </button>
                        </div>
                    </li>
                ))}
            </ul>
            <button className="kartlag-btn kartlag-export" onClick={handleExport}>
                <FontAwesomeIcon icon={faDownload} /> Last ned som GeoJSON
            </button>
        </div>
    );
}
