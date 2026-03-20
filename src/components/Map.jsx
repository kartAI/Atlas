    import { useEffect, useEffectEvent } from "react";
    import { MapContainer, TileLayer, WMSTileLayer, GeoJSON, useMap } from "react-leaflet";
    import { BaseMapSwitcher } from "./MapLayers";
    import L from "leaflet";
    import { DrawToolBar } from "./DrawToolBar";

    const NORWAY_BOUNDS = L.latLngBounds([55.0, 2.0], [73.0, 34.0]);

    // Pads maxBounds dynamically so zoomed-in panning is never restricted
    function DynamicBounds() {
        const map = useMap();

        useEffect(() => {
            function updateBounds() {
                const pad = Math.max(0, map.getZoom() - 5) * 5;
                map.setMaxBounds(NORWAY_BOUNDS.pad(pad));
            }

            updateBounds();
            map.on('zoomend', updateBounds);
            return () => map.off('zoomend', updateBounds);
        }, [map]);

        return null;
    }

    // Tells Leaflet to recalculate its size whenever the map container resizes
    function MapResizeObserver() {
        const map = useMap();

        useEffect(() => {
            const container = map.getContainer();
            const observer = new ResizeObserver(() => {
                map.invalidateSize();
            });
            observer.observe(container);
            return () => observer.disconnect();
        }, [map]);

        return null;
    }

    function FlyToController({ drawnLayers, flyTarget, onFlyDone }) {
        const map = useMap();
        const handleFlyDone = useEffectEvent(onFlyDone);

        useEffect(() => {
            if (!flyTarget) return;
            const layer = drawnLayers.find(l => l.id === flyTarget);
            if (!layer?.geoJson) return;

            const t = setTimeout(() => {
                const bounds = L.geoJSON(layer.geoJson).getBounds();
                if (bounds.isValid()) {
                    const ne = bounds.getNorthEast();
                    const sw = bounds.getSouthWest();
                    const spanLng = Math.abs(ne.lng - sw.lng);
                    const spanLat = Math.abs(ne.lat - sw.lat);
                    const span = Math.max(spanLng, spanLat);

                    // Smaller features → higher maxZoom for tighter framing
                    let maxZoom;
                    if (span < 0.005) maxZoom = 18;
                    else if (span < 0.05) maxZoom = 17;
                    else if (span < 0.5) maxZoom = 15;
                    else if (span < 2) maxZoom = 13;
                    else maxZoom = 11;

                    map.flyToBounds(bounds, { padding: [60, 60], maxZoom });
                }
                handleFlyDone();
            }, 50);
            return () => clearTimeout(t);
        }, [drawnLayers, flyTarget, map]);

        return null;
    }

    function Map({ layers, onToggleLayer, drawnLayers, onLayerCreated, onLayerUpdated, onLayerRemoved, flyTarget, onFlyDone }) {
        const center = [65.0, 15.0];

        return (
            <div className="map-root">
                <MapContainer
                    center={center}
                    zoom={5}
                    maxBounds={NORWAY_BOUNDS}
                    maxBoundsViscosity={0.5}
                    minZoom={4}
                    style={{ height: "100%", width: "100%" }}
                >
                    <DynamicBounds />
                    <MapResizeObserver />
                    <DrawToolBar
                        drawnLayers={drawnLayers}
                        onLayerCreated={onLayerCreated}
                        onLayerUpdated={onLayerUpdated}
                        onLayerRemoved={onLayerRemoved}
                    />
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

                    <FlyToController
                        drawnLayers={drawnLayers}
                        flyTarget={flyTarget}
                        onFlyDone={onFlyDone}
                    />
                </MapContainer>

                <BaseMapSwitcher layers={layers} onToggleLayer={onToggleLayer} />
            </div>
        );
    }

    export default Map;
