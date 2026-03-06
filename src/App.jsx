import './App.css'
import { useState } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel.jsx';
import Map from './components/Map.jsx';

import { faLayerGroup, faChartLine, faFileExport } from '@fortawesome/free-solid-svg-icons';
import { faMessage } from '@fortawesome/free-regular-svg-icons';

const menuItems = [
    { id: 'Chatbot', label: 'Chatbot', icon: faMessage },
    { id: 'Kartlag', label: 'Kartlag', icon: faLayerGroup },
    { id: 'Analyse', label: 'Analyse', icon: faChartLine },
    { id: 'Eksporter', label: 'Eksporter', icon: faFileExport },
];

function App() {
  const [activePanel, setActivePanel] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [layers, setLayers] = useState([{
    id: 'topo',
    name: 'Topografisk (farge)',
    type: 'tile',
    url: 'https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png',
    visible: true,
  },
  {
    id: 'topo-raster',
    name: 'Topografisk (raster)',
    type: 'tile',
    url: 'https://cache.kartverket.no/v1/wmts/1.0.0/toporaster/default/webmercator/{z}/{y}/{x}.png',
    visible: false,
  },
  {    
    id: 'graa',
    name: 'Topografisk (gråtone)',
    type: 'tile',
    url: 'https://cache.kartverket.no/v1/wmts/1.0.0/topograatone/default/webmercator/{z}/{y}/{x}.png',
    visible: false,
  },
  {
    id: 'sjo',
    name: 'Sjøkart',
    type: 'tile',
    url: 'https://cache.kartverket.no/v1/wmts/1.0.0/sjokartraster/default/webmercator/{z}/{y}/{x}.png',
    visible: false,
  }
  ]);

  const toggleLayer = (layerId) => {
    setLayers(prev => prev.map(layer => ({
      ...layer,
      visible: layer.id === layerId,
    })));
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
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed(c => !c)}
        />
        <ContentPanel 
          activePanel={activePanel} 
          onClose={() => setActivePanel(null)}
          layers={layers}
          onToggleLayer={toggleLayer} />

        <main className="map-stage">
          <Map layers={layers} onToggleLayer={toggleLayer} />
        </main>
      </div>
    </>
  )
}

export default App
