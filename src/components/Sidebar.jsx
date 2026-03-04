import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronLeft, faChevronRight } from '@fortawesome/free-solid-svg-icons';

export function Sidebar({ items, activePanel, onSelect, collapsed, onToggleCollapse }) {
    return (
        <nav className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
            <div className="sidebar-header">
                {!collapsed && <span className="sidebar-heading">Meny</span>}
                <button
                    className="sidebar-toggle"
                    onClick={onToggleCollapse}
                    aria-label={collapsed ? 'Utvid meny' : 'Skjul meny'}
                >
                    <FontAwesomeIcon icon={collapsed ? faChevronRight : faChevronLeft} />
                </button>
            </div>
            <ul className="sidebar-menu">
                {items.map((item) => (
                <li key={item.id} className="sidebar-menu-item">
                    <button
                        className={`sidebar-item ${activePanel === item.id ? 'active' : ''}`}
                        onClick={() => onSelect(item.id)}
                        title={collapsed ? item.label : undefined}
                    >
                        <FontAwesomeIcon icon={item.icon} className="sidebar-icon" />
                        {!collapsed && <span className="sidebar-label">{item.label}</span>}
                    </button>
                </li>
                ))}
            </ul>
        </nav>
    )
}