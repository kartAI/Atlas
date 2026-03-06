    import { useState } from "react";
    import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, Marker, Popup } from "react-leaflet";
    import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
    import { faLayerGroup } from '@fortawesome/free-solid-svg-icons';


    /* function FixMapSize() {
        const map = useMap();

        useEffect(() => {
            const i = setTimeout(() => {
                map.invalidateSize();
            }, 200);

            return () => clearTimeout(i);
        }, [map]);

        return null;
    }*/

    const NORWAY_BOUNDS = [
        [57.0, 3.0],   // southwest corner 
        [72.0, 32.0]   // northeast corner
    ];

    function Map({ layers, onToggleLayer }) {
        const center = [58.1467, 7.9956];
        const [layersPanelOpen, setLayersPanelOpen] = useState(false);

        return (
            <div className="map-root">
                <MapContainer
                    center={[65.0, 15.0]}
                    zoom={5}
                    maxBounds={NORWAY_BOUNDS}   
                    maxBoundsViscosity={1.0}
                    minZoom={4}
                    style={{ height: "100%", width: "100%" }}
                    
                >
                    {layers
                    .filter(layer => layer.visible)
                    .map(layer => {
                        if (layer.type === "tile") {
                            return <TileLayer key={layer.id} url={layer.url} attribution='© <a href="https://kartverket.no">Kartverket</a>' />;
                        } 
                        if (layer.type === "wms") {
                            return (<WMSTileLayer key={layer.id} url={layer.url} layers="Nibcache_UTM33_EUREF89" version="1.1.1" format="image/jpeg" attribution='© <a href="https://kartverket.no">Kartverket</a>' />);
                        }
                        if (layer.type === "geojson") {
                            return <GeoJSON key={layer.id} data={layer.data} attribution='© <a href="https://kartverket.no">Kartverket</a>' />;
                        }
                        return null;
                        })
                    }
                    <Marker position={center}>
                        <Popup>Test</Popup>
                    </Marker>
                </MapContainer>

                <div className="map-layers-overlay">
                    <button
                        className={`map-layers-toggle ${layersPanelOpen ? 'active' : ''}`}
                        onClick={() => setLayersPanelOpen(prev => !prev)}
                        title="Kartlag"
                    >
                        <FontAwesomeIcon icon={faLayerGroup} />
                    </button>

                    {layersPanelOpen && (
                        <div className="map-layers-dropdown">
                            <div className="map-layers-header">Kartlag</div>
                            <ul className="map-layers-list">
                                {layers.map(layer => (
                                    <li key={layer.id} className="map-layers-item">
                                        <label
                                            className="map-layers-label"
                                            onClick={() => onToggleLayer(layer.id)}
                                        >
                                            <span className="map-layers-name">{layer.name}</span>
                                            <div className={`map-layers-radio ${layer.visible ? 'active' : ''}`}>
                                                <div className="map-layers-radio-dot" />
                                            </div>
                                        </label>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    export default Map;
