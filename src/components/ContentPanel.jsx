import { ChatInterface } from './ChatInterface';
import { MapLayers } from './MapLayers';

const PANEL_COMPONENTS = {
    'Chatbot': ChatInterface,
    'Kartlag': () => <h2>Kartlag</h2>, // Replace with real component later
    'Analyse': () => <h2>Analyse</h2>, // Replace with real component later
    'Eksporter': () => <h2>Eksporter</h2> // Replace with real component later
};

export function ContentPanel({ activePanel, onClose, layers, onToggleLayer }) {
    if (!activePanel) return null; // Don't render if no active panel

    const Component = PANEL_COMPONENTS[activePanel] || (() => <h2>{activePanel}</h2>);

    return (
        <div className="content-panel">
            <button className="close-btn" onClick={onClose}>✕</button>
            <Component />
        </div>
    );
}
