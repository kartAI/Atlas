import './App.css'
import { useState } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel.jsx';
import Map from './components/Map.jsx';

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSquarePollVertical } from '@fortawesome/free-solid-svg-icons';
import { faMessage } from '@fortawesome/free-regular-svg-icons';
import { layer } from '@fortawesome/fontawesome-svg-core';
import { map } from 'leaflet';

const menuItems = [
    { id: 'Chatbot', label: 'Chatbot', icon: faMessage },
    { id: 'Kartlag', label: 'Kartlag', icon: faSquarePollVertical },
    { id: 'Analyse', label: 'Analyse', icon: faSquarePollVertical },
    { id: 'Eksporter', label: 'Eksporter', icon: faSquarePollVertical },
];

function App() {
  const [activePanel, setActivePanel] = useState(null);

  const [layers, setLayers] = useState([{
    id: 'osm',
    name: 'OpenStreetMap',
    type: 'tile',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    visible: true,
  },
  {    
    id: 'topo',
    name: 'Topografisk',
    type: 'tile',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    visible: false,
  }, 
  {
    id: 'satellite',
    name: 'Satellite',
    type: 'tile',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    visible: false,
  }
  ]);

  const toggleLayer = (layerId) => {
    setLayers(layers.map(layer => {
      if (layer.id === layerId) {
        return { ...layer, visible: !layer.visible };
      }
      return layer;
    }));
    }

  const handleSelect = (id) => {
    setActivePanel(activePanel === id ? null : id);
  };

  return (
    <>
      <Header />
      <div className="app-body">
        <Sidebar 
          items={menuItems} 
          activePanel={activePanel} 
          onSelect={handleSelect}
        />
        <ContentPanel 
          activePanel={activePanel} 
          onClose={() => setActivePanel(null)}
          layers={layers}
          onToggleLayer={toggleLayer} />

        <main className="map-stage">
          <Map layers={layers} />
        </main>
      </div>
    </>
  )
}

export default App
