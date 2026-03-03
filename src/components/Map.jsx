import { useEffect } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";

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

function Map() {
    const center = [58.1467, 7.9956];

    return (
        <div className="map-root">
            <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }}>
                <FixMapSize />
                <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution="&copy; OpenStreetMap contributors"
                />
                <Marker position={center}>
                    <Popup>Test</Popup>
                </Marker>
            </MapContainer>
        </div>
    );
}

export default Map;
