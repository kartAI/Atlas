import { ChatInterface } from './ChatInterface';
import { Analysis } from './Analysis';
import { KartlagPanel } from './KartlagPanel';
import { ExportPanel } from './ExportPanel';

/**
 * ContentPanel
 *
 * Keeps ChatInterface mounted even when the user switches panels so the
 * active conversation, auth state, and in-progress input do not reset.
 */
export function ContentPanel({ activePanel, onClose, layers, drawnLayers, onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer, chatUser, onUserChange, onLayerCreated, panelWidth }) {
    const isOpen = !!activePanel;

    const panelStyle = isOpen && panelWidth !== null
        ? { width: `${panelWidth}px`, maxWidth: `${panelWidth}px`, transition: 'none' }
        : {};

    return (
        <div className={`content-panel ${isOpen ? 'content-panel--open' : 'content-panel--closed'}`} style={panelStyle}>
            <button className="close-btn" onClick={onClose}>✕</button>
            <div
                style={{
                    display: activePanel === 'Chatbot' ? 'flex' : 'none',
                    flexDirection: 'column',
                    height: '100%',
                    minHeight: 0,
                }}
            >
                <ChatInterface
                    drawnLayers={drawnLayers}
                    onLayerCreated={onLayerCreated}
                    externalUser={chatUser}
                    onUserChange={onUserChange}
                />
            </div>

            {activePanel === 'Kartlag' && (
                <KartlagPanel
                    layers={layers}
                    drawnLayers={drawnLayers}
                    onSetDrawnLayerVisible={onSetDrawnLayerVisible}
                    onRemoveDrawnLayer={onRemoveDrawnLayer}
                    onFlyToLayer={onFlyToLayer}
                />
            )}

            {activePanel === 'Analyse' && (
                <Analysis
                    layers={layers}
                    drawnLayers={drawnLayers}
                    onSetDrawnLayerVisible={onSetDrawnLayerVisible}
                    onRemoveDrawnLayer={onRemoveDrawnLayer}
                    onFlyToLayer={onFlyToLayer}
                />
            )}

            {activePanel === 'Eksporter' && (
                <ExportPanel
                    layers={layers}
                    drawnLayers={drawnLayers}
                    onSetDrawnLayerVisible={onSetDrawnLayerVisible}
                    onRemoveDrawnLayer={onRemoveDrawnLayer}
                    onFlyToLayer={onFlyToLayer}
                />
            )}
        </div>
    );
}
