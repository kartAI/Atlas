import { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, LayersControl, useMap } from "react-leaflet";

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
    const lat = 58.1467;
    const lng = 7.9956;
    const z = 13;
    const { BaseLayer } = LayersControl;
    const [showGoogle, setShowGoogle] = useState(false);
    const [googleError, setGoogleError] = useState("");
    const googleMapRef = useRef(null);
    const roadThumb = `https://tile.openstreetmap.org/${z}/4277/2461.png`;
    const satelliteThumb = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/13/2461/4277";

    useEffect(() => {
        if (!showGoogle) return;

        const key = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
        if (!key) {
            setGoogleError("Missing VITE_GOOGLE_MAPS_API_KEY in your .env file.");
            return;
        }

        setGoogleError("");

        const createGoogleMap = () => {
            if (!window.google || !googleMapRef.current) return;

            const map = new window.google.maps.Map(googleMapRef.current, {
                center: { lat, lng },
                zoom: 18,
                mapTypeId: "satellite",
                tilt: 45,
                heading: 45,
                mapTypeControl: false,
                streetViewControl: false,
                fullscreenControl: false
            });

            new window.google.maps.Marker({
                position: { lat, lng },
                map,
                title: "Test"
            });
        };

        if (window.google && window.google.maps) {
            createGoogleMap();
            return;
        }

        let script = document.getElementById("google-maps-script");
        if (!script) {
            script = document.createElement("script");
            script.id = "google-maps-script";
            script.src = `https://maps.googleapis.com/maps/api/js?key=${key}`;
            script.async = true;
            script.defer = true;
            script.onload = createGoogleMap;
            script.onerror = () => setGoogleError("Could not load Google Maps.");
            document.head.appendChild(script);
        } else {
            script.addEventListener("load", createGoogleMap);
            return () => script.removeEventListener("load", createGoogleMap);
        }
    }, [showGoogle, lat, lng]);

    return (
        <div className="map-root">
            <div className="map-control-stack">
                <div className="map-mode-card" aria-label="Kartmodus">
                    <div className="map-mode-title">Kartmodus</div>
                    <button
                        type="button"
                        className={`map-mode-item ${!showGoogle ? "is-active" : ""}`}
                        onClick={() => setShowGoogle(false)}
                        title="Bytt til Leaflet"
                        aria-pressed={!showGoogle}
                    >
                        <span className="map-mode-bullet" />
                        <span className="map-mode-text">
                            <span className="map-mode-label">Leaflet</span>
                            <span className="map-mode-sub">2D kart</span>
                        </span>
                        <span className="map-mode-thumb" style={{ backgroundImage: `url(${roadThumb})` }} />
                    </button>
                    <button
                        type="button"
                        className={`map-mode-item ${showGoogle ? "is-active" : ""}`}
                        onClick={() => setShowGoogle(true)}
                        title="Bytt til Google 3D"
                        aria-pressed={showGoogle}
                    >
                        <span className="map-mode-bullet" />
                        <span className="map-mode-text">
                            <span className="map-mode-label">Google 3D</span>
                            <span className="map-mode-sub">3D visning</span>
                        </span>
                        <span className="map-mode-thumb" style={{ backgroundImage: `url(${satelliteThumb})` }} />
                    </button>
                </div>
            </div>

            {!showGoogle && (
                <MapContainer center={center} zoom={13} style={{ height: "100%", width: "100%" }}>
                    <FixMapSize />

                    <LayersControl position="topright">
                        <BaseLayer checked name="Road map">
                            <TileLayer
                                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                                attribution="&copy; OpenStreetMap contributors"
                            />
                        </BaseLayer>

                        <BaseLayer name="Satellite">
                            <TileLayer
                                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                                attribution="Tiles &copy; Esri"
                            />
                        </BaseLayer>

                        <BaseLayer name="Terrain">
                            <TileLayer
                                url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
                                attribution="Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap"
                            />
                        </BaseLayer>
                    </LayersControl>

                    <Marker position={center}>
                        <Popup>Test</Popup>
                    </Marker>
                </MapContainer>
            )}

            {showGoogle && (
                <div style={{ height: "100%", width: "100%" }}>
                    <div ref={googleMapRef} style={{ height: "100%", width: "100%" }} />
                    {googleError && (
                        <div style={{ position: "absolute", bottom: 10, left: 10, background: "white", padding: 8 }}>
                            {googleError}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default Map;
