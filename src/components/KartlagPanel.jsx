import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEye, faEyeSlash, faTrash, faDownload } from '@fortawesome/free-solid-svg-icons';
import { downloadLayersAsGeoJSON, sanitizeFilenameSegment } from '../utils/exportUtils';

export function KartlagPanel({ drawnLayers = [], onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer }) {
    function handleLayerExport(layer) {
        if (!layer.geoJson) return;

        downloadLayersAsGeoJSON([layer], {
            filename: `${sanitizeFilenameSegment(layer.name, 'tegning')}.geojson`,
        });
    }

    function handleExport() {
        downloadLayersAsGeoJSON(drawnLayers, {
            filename: 'tegninger.geojson',
        });
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
