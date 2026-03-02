import { Bot, Layers, ChartColumn, Download } from "lucide-react";

const items = [
  { key: "Chatbot", icon: Bot },
  { key: "Kartlag", icon: Layers },
  { key: "Analyse", icon: ChartColumn },
  { key: "Eksporter", icon: Download },
];

export function Sidebar({ activeItem, onSelect }) {
  return (
    <nav className="sidebar">
      <h3 className="sidebar-heading">Meny</h3>
      <ul className="sidebar-menu">
        {items.map(({ key, icon: Icon }) => (
          <li key={key}>
            <button
              type="button"
              className={`sidebar-item ${activeItem === key ? "active" : ""}`}
              onClick={() => onSelect(key)}
              aria-pressed={activeItem === key}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{key}</span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
