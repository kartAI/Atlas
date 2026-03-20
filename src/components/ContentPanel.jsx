import { ChatInterface } from './ChatInterface';
import { Analysis } from './Analysis';
import { KartlagPanel } from './KartlagPanel';

const PANEL_COMPONENTS = {
    'Chatbot': ChatInterface,
    'Kartlag': KartlagPanel,
    'Analyse': Analysis,
    'Eksporter': () => <h2>Eksporter</h2> // Replace with real component later
}

export function ContentPanel({ activePanel, onClose, drawnLayers, onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer }) {
    const isOpen = !!activePanel;
    const Component = PANEL_COMPONENTS[activePanel] || (() => <h2>{activePanel}</h2>);

    return (
        <div className={`content-panel ${isOpen ? 'content-panel--open' : 'content-panel--closed'}`}>
            <button className="close-btn" onClick={onClose}>✕</button>
            {isOpen && (
                <Component
                    drawnLayers={drawnLayers}
                    onSetDrawnLayerVisible={onSetDrawnLayerVisible}
                    onRemoveDrawnLayer={onRemoveDrawnLayer}
                    onFlyToLayer={onFlyToLayer}
                />
            )}
        </div>
    );
}
