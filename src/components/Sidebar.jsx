import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';

export function Sidebar({ items, activePanel, onSelect }) {
    return (
        <nav className="sidebar">
            <h3 className="sidebar-heading">Meny</h3>
            <ul className="sidebar-menu">
                {items.map((item) => (
                <li key={item.id}>
                    <button
                    className={`sidebar-item ${activePanel === item.id ? 'active' : ''}`}
                    onClick={() => onSelect(item.id)}
                    >
                    <FontAwesomeIcon icon={item.icon} className="sidebar-icon" />
                    <span>{item.label}</span>
                    </button>
                </li>
                ))}
            </ul>
        </nav>
    )
}