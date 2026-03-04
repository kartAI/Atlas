import { useEffect } from "react";
import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, Marker, Popup, useMap } from "react-leaflet";

function FixMapSize() {
    const map = useMap();

    useEffect(() => {
        const i = setTimeout(() => {
            map.invalidateSize();
        }, 200);

        return () => clearTimeout(i);
    }, [map]);

    return null;
}

function Map({ layers }) {
    const center = [58.1467, 7.9956];

    return (
        <div className="map-root">
            <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }}>
                {layers
                .filter(layer => layer.visible)
                 .map(layer => {
                    if (layer.type === "tile") {
                        return <TileLayer key={layer.id} url={layer.url} />;
                    } 
                    if (layer.type === "wms") {
                        return (<WMSTileLayer key={layer.id} url={layer.url} layers={layer.layers} />);
                    }
                    if (layer.type === "geojson") {
                        return <GeoJSON key={layer.id} data={layer.data} />;
                    }
                    return null;
                    })
                }
                <Marker position={center}>
                    <Popup>Test</Popup>
                </Marker>
            </MapContainer>
        </div>
    );
}

export default Map;
