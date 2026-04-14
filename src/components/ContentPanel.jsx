import { ChatInterface } from './ChatInterface';
import { ToolList } from './ToolList';
import { KartlagPanel } from './KartlagPanel';
import { ExportPanel } from './ExportPanel';

/**
 * ContentPanel
 *
 * Keeps ChatInterface mounted even when the user switches panels so the
 * active conversation, auth state, and in-progress input do not reset.
 */
export function ContentPanel({ activePanel, onClose, layers, drawnLayers, onSetDrawnLayerVisible, onRemoveDrawnLayer, onFlyToLayer, chatUser, onUserChange, onLayerCreated, selectedTools, onToggleTool, onClearSelectedTools, onGoToChat }) {
    const isOpen = !!activePanel;

    return (
        <div className={`content-panel ${isOpen ? 'content-panel--open' : 'content-panel--closed'}`}>
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
                    selectedTools={selectedTools}
                    onClearSelectedTools={onClearSelectedTools}
                    onRemoveTool={onToggleTool}
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

            {activePanel === 'Verktøy' && (
                <ToolList
                    selectedTools={selectedTools}
                    onToggleTool={onToggleTool}
                    onGoToChat={onGoToChat}
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
