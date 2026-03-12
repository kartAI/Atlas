import { ChatInterface } from './ChatInterface';
import { Analysis } from './Analysis';

const PANEL_COMPONENTS = {
    'Chatbot': ChatInterface,
    'Kartlag': () => <h2>Kartlag</h2>, // Replace with real component later
    'Analyse': Analysis,
    'Eksporter': () => <h2>Eksporter</h2> // Replace with real component later
};

export function ContentPanel({ activePanel, onClose }) {
    const isOpen = !!activePanel;
    const Component = PANEL_COMPONENTS[activePanel] || (() => <h2>{activePanel}</h2>);

    return (
        <div className={`content-panel ${isOpen ? 'content-panel--open' : 'content-panel--closed'}`}>
            <button className="close-btn" onClick={onClose}>✕</button>
            {isOpen && <Component />}
        </div>
    );
}
