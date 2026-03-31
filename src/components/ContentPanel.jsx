import { useState, useEffect } from 'react';
import { ChatInterface } from './ChatInterface';
import { Analysis } from './Analysis';
import { KartlagPanel } from './KartlagPanel';
import { ExportPanel } from './ExportPanel';

const PANEL_COMPONENTS = {
    'Chatbot': ChatInterface,
    'Kartlag': KartlagPanel,
    'Analyse': Analysis,
    'Eksporter': ExportPanel,
};

/**
 * ContentPanel
 *
 * Uses a "keep-alive" strategy: once a panel has been visited it stays
 * mounted in the DOM and is simply hidden (display:none) when inactive.
 * This preserves component state — especially important for ChatInterface
 * which must not lose its conversation on every sidebar navigation.
 */
export function ContentPanel({ activePanel, onClose, layers, drawnLayers, onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer, chatUser, onUserChange }) {
    const isOpen = !!activePanel;

    // Track which panels have ever been opened so we know which to keep mounted.
    const [everOpened, setEverOpened] = useState(new Set());

    useEffect(() => {
        if (activePanel) {
            setEverOpened(prev => {
                if (prev.has(activePanel)) return prev;
                const next = new Set(prev);
                next.add(activePanel);
                return next;
            });
        }
    }, [activePanel]);

    return (
        <div className={`content-panel ${isOpen ? 'content-panel--open' : 'content-panel--closed'}`}>
            <button className="close-btn" onClick={onClose}>✕</button>
            {Array.from(everOpened).map(panelId => {
                const Comp = PANEL_COMPONENTS[panelId];
                if (!Comp) return null;
                return (
                    <div
                        key={panelId}
                        style={{
                            display: activePanel === panelId ? 'flex' : 'none',
                            flexDirection: 'column',
                            height: '100%',
                            minHeight: 0,
                        }}
                    >
                        <Comp
                            layers={layers}
                            drawnLayers={drawnLayers}
                            onSetDrawnLayerVisible={onSetDrawnLayerVisible}
                            onRemoveDrawnLayer={onRemoveDrawnLayer}
                            onFlyToLayer={onFlyToLayer}
                            externalUser={chatUser}
                            onUserChange={onUserChange}
                        />
                    </div>
                );
            })}
        </div>
    );
}

