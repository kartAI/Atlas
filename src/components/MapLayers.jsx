import { useState } from "react";
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faLayerGroup } from '@fortawesome/free-solid-svg-icons';

export function BaseMapSwitcher({ layers = [], onToggleLayer }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="map-layers-overlay">
      <button
        className={`map-layers-toggle ${open ? 'active' : ''}`}
        onClick={() => setOpen(prev => !prev)}
        title="Base map"
      >
        <FontAwesomeIcon icon={faLayerGroup} />
      </button>
      {open && (
        <div className="map-layers-dropdown">
          <div className="map-layers-header">Base map</div>
          <ul className="map-layers-list">
            {layers.map(layer => (
              <li key={layer.id} className="map-layers-item">
                <label className="map-layers-label">
                  <input
                    type="radio"
                    checked={layer.visible}
                    onChange={() => onToggleLayer(layer.id)}
                    style={{ display: 'none' }}
                  />  
                  <span className="map-layers-name">{layer.name}</span>
                  <div className={`map-layers-radio ${layer.visible ? 'active' : ''}`}>
                    <div className="map-layers-radio-dot" />
                  </div>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
