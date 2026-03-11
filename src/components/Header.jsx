import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSun, faMoon } from '@fortawesome/free-solid-svg-icons';

export function Header({ theme, onToggleTheme }) {
    return (
        <div className="header-bar">
            <div className="logo">
                <img src={theme === 'dark' ? '/norkartFull_white.png' : '/norkartFull.png'} />
            </div>
             <button className="theme-toggle" onClick={onToggleTheme}>
                <FontAwesomeIcon icon={theme === 'dark' ? faSun : faMoon} />
            </button>
        </div>
    )
}