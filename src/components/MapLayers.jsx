export function MapLayers({ layers = [], onToggleLayer }) {
  return (
    <div className="map-layers-panel">
      <h3>Kartlag</h3>
      <ul>
        {layers.map(layer => (
            <li key={layer.id}>
                <label>
                    <input
                        type="checkbox"
                        checked={layer.visible}
                        onChange={() => onToggleLayer(layer.id)}
                    />
                    {layer.name}
                </label>
            </li>
        ))}
        </ul>
    </div>
    );
}
