    import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, Marker, Popup } from "react-leaflet";
    import { BaseMapSwitcher } from "./MapLayers";

    const NORWAY_BOUNDS = [
        [57.0, 3.0],   // southwest corner 
        [72.0, 32.0]   // northeast corner
    ];

    function Map({ layers, onToggleLayer }) {
        const center = [58.1467, 7.9956];

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
                            return <TileLayer key={layer.id} url={layer.url} attribution={layer.attribution || '© <a href="https://kartverket.no">Kartverket</a>'} />;
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

                <BaseMapSwitcher layers={layers} onToggleLayer={onToggleLayer} />
            </div>
        );
    }

    export default Map;
