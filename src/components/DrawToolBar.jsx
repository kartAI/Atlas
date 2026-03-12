import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import '@geoman-io/leaflet-geoman-free';

const SHAPE_LABELS = {
    Marker: 'Markør',
    Polygon: 'Polygon',
    Rectangle: 'Rektangel',
    Polyline: 'Linje',
    Circle: 'Sirkel',
};

export function DrawToolBar({ drawnLayers = [], onLayerCreated, onLayerRemoved }) {
    const map = useMap();
    const locationMarkerRef = useRef(null);
    const locateButtonRef = useRef(null);
    const layerMapRef = useRef(new Map()); // id -> leaflet layer
    const counterRef = useRef(1);
    const onLayerCreatedRef = useRef(onLayerCreated);
    const onLayerRemovedRef = useRef(onLayerRemoved);

    useEffect(() => {
        onLayerCreatedRef.current = onLayerCreated;
    }, [onLayerCreated]);

    useEffect(() => {
        onLayerRemovedRef.current = onLayerRemoved;
    }, [onLayerRemoved]);

    // Sync visibility / deletions from sidebar into actual Leaflet layers
    useEffect(() => {
        const currentIds = new Set(drawnLayers.map(l => l.id));

        for (const [id, layer] of [...layerMapRef.current]) {
            if (!currentIds.has(id)) {
                layer.remove();
                layerMapRef.current.delete(id);
            }
        }

        drawnLayers.forEach(({ id, visible }) => {
            const layer = layerMapRef.current.get(id);
            if (!layer) return;
            if (visible && !map.hasLayer(layer)) layer.addTo(map);
            else if (!visible && map.hasLayer(layer)) layer.remove();
        });
    }, [drawnLayers, map]);

    useEffect(() => {
        if (!map.pm) return;

        function setLocateButtonState(hasMarker) {
            const button = locateButtonRef.current;
            if (!button) return;

            button.classList.remove('leaflet-pm-icon-locate-user', 'leaflet-pm-icon-locate-delete');
            button.classList.add(hasMarker ? 'leaflet-pm-icon-locate-delete' : 'leaflet-pm-icon-locate-user');

            const title = hasMarker ? 'Fjern min posisjon' : 'Finn min posisjon';
            button.title = title;
            button.setAttribute('aria-label', title);
        }

        function clearLocationMarker() {
            if (!locationMarkerRef.current) return;
            locationMarkerRef.current.remove();
            locationMarkerRef.current = null;
            setLocateButtonState(false);
        }

        if (!map.pm.controlsVisible()) {
            map.pm.addControls({
                position: 'topleft',
                drawMarker: true,
                drawCircleMarker: false,
                drawPolyline: true,
                drawRectangle: true,
                drawPolygon: true,
                drawCircle: true,
                drawText: false,
                editMode: true,
                dragMode: true,
                cutPolygon: false,
                removalMode: true,
                rotateMode: false,
            });
            map.pm.setLang('nb');
        }

        const existingButtons = map.pm.Toolbar.getButtons();
        if (!existingButtons['locateMe']) {
            map.pm.Toolbar.createCustomControl({
                name: 'locateMe',
                block: 'custom',
                title: 'Finn min posisjon',
                className: 'leaflet-pm-icon-locate-user',
                onClick: () => {
                    if (locationMarkerRef.current) {
                        clearLocationMarker();
                        return;
                    }

                    map.locate({
                        enableHighAccuracy: true,
                        maxZoom: 14,
                        setView: false,
                    });
                },
                toggle: false,
            });
        }

        locateButtonRef.current = map
            .getContainer()
            .closest('.leaflet-container')
            ?.querySelector('.leaflet-pm-icon-locate-user, .leaflet-pm-icon-locate-delete');
        setLocateButtonState(Boolean(locationMarkerRef.current));

        function onDrawModeToggle({ enabled }) {
            if (enabled) map.dragging.disable();
            else map.dragging.enable();
        }
        map.on('pm:globaldrawmodetoggled', onDrawModeToggle);

        function onKeyDown(e) {
            if (e.key !== 'Escape') return;
            map.pm.disableDraw();
            map.pm.disableGlobalEditMode();
            map.pm.disableGlobalDragMode();
            map.pm.disableGlobalRemovalMode();
            map.dragging.enable();
        }
        document.addEventListener('keydown', onKeyDown);

        function onLayerCreate({ layer }) {
            const shape = layer.pm?.getShape?.() ?? 'Tegning';
            const id = `drawn-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            const name = `${SHAPE_LABELS[shape] ?? shape} ${counterRef.current++}`;
            layer._gmDrawnId = id;
            layerMapRef.current.set(id, layer);
            onLayerCreatedRef.current?.({ id, name, shape, visible: true, geoJson: layer.toGeoJSON() });
        }
        map.on('pm:create', onLayerCreate);

        function onLayerRemove({ layer }) {
            if (!layer._gmDrawnId) return;
            layerMapRef.current.delete(layer._gmDrawnId);
            onLayerRemovedRef.current?.(layer._gmDrawnId);
        }
        map.on('pm:remove', onLayerRemove);

        function onLocationFound(e) {
            if (locationMarkerRef.current) locationMarkerRef.current.remove();
            locationMarkerRef.current = L.marker(e.latlng)
                .addTo(map)
                .bindPopup('Du er her')
                .openPopup();
            map.flyTo(e.latlng, Math.max(map.getZoom(), 14), {
                animate: true,
                duration: 1.2,
            });
            setLocateButtonState(true);
        }
        map.on('locationfound', onLocationFound);

        function onLocationError() {
            clearLocationMarker();
        }
        map.on('locationerror', onLocationError);

        return () => {
            map.off('pm:globaldrawmodetoggled', onDrawModeToggle);
            map.off('pm:create', onLayerCreate);
            map.off('pm:remove', onLayerRemove);
            map.off('locationfound', onLocationFound);
            map.off('locationerror', onLocationError);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [map]);

    return null;
}

