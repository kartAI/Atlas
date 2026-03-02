import { ChatInterface } from "./chatInterface.jsx";

const PANEL_COMPONENTS = {
    Chatbot: ChatInterface,
    Kartlag: () => <h2>Kartlag</h2>,
    Analyse: () => <h2>Analyse</h2>,
    Eksporter: () => <h2>Eksporter</h2>
};

export function ContentPanel({ activePanel, onClose }) {
    if (!activePanel) return null;

    const Component = PANEL_COMPONENTS[activePanel] || (() => <h2>{activePanel}</h2>);

    return (
        <div className="content-panel">
            <button type="button" className="close-btn" onClick={onClose} aria-label="Lukk panel">✕</button>
            <Component />
        </div>
    );
}
