import './App.css'
import { useState, useEffect } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel.jsx';
import Map from './components/Map.jsx';
import { apiFetch, clearToken, clearActiveChatId } from './utils/auth';

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
  const [theme, setTheme] =useState(() => localStorage.getItem('theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t=> t === 'dark' ? 'light' : 'dark');

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
  },
  {
    id: 'ortofoto',
    name: 'Ortofoto / Satelitt',
    type: 'tile',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    visible: false,
    attribution: '© Esri, Maxar, Earthstar Geographics',
  }
  ]);

  const [drawnLayers, setDrawnLayers] = useState([]);

  const upsertDrawnLayer = (info) => {
    setDrawnLayers(previousLayers => {
      const hasExistingLayer = previousLayers.some(layer => layer.id === info.id);

      if (!hasExistingLayer) {
        return [...previousLayers, info];
      }

      return previousLayers.map(layer =>
        layer.id === info.id ? { ...layer, ...info } : layer
      );
    });
  };

  const setDrawnLayerVisible = (id, visible) =>
    setDrawnLayers(prev => prev.map(l => l.id === id ? { ...l, visible } : l));

  const removeDrawnLayer = (id) =>
    setDrawnLayers(prev => prev.filter(l => l.id !== id));

  const toggleLayer = (layerId) => {
    setLayers(prev => prev.map(layer => ({
      ...layer,
      visible: layer.id === layerId,
    })));
  }

  const handleSelect = (id) => {
    setActivePanel(activePanel === id ? null : id);
  };

  const [flyTarget, setFlyTarget] = useState(null);

  // Global user state (synced from ChatInterface via onUserChange)
  const [chatUser, setChatUser] = useState(null);

  async function handleHeaderLogout() {
    try { await apiFetch('/api/auth/logout', { method: 'POST' }); } catch {}
    clearToken();
    clearActiveChatId();
    setChatUser(null);
  }

  function handleHeaderLogin() {
    setActivePanel('Chatbot');
  }

  return (
    <>
      <Header theme={theme} onToggleTheme={toggleTheme} user={chatUser} onLogout={handleHeaderLogout} onLogin={handleHeaderLogin} />
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
          onToggleLayer={toggleLayer}
          drawnLayers={drawnLayers}
          onSetDrawnLayerVisible={setDrawnLayerVisible}
          onRemoveDrawnLayer={removeDrawnLayer}
          onFlyToLayer={setFlyTarget}
          chatUser={chatUser}
          onUserChange={setChatUser} />

        <main className="map-stage">
          <Map
            layers={layers}
            onToggleLayer={toggleLayer}
            drawnLayers={drawnLayers}
            onLayerCreated={upsertDrawnLayer}
            onLayerUpdated={upsertDrawnLayer}
            onLayerRemoved={removeDrawnLayer}
            flyTarget={flyTarget}
            onFlyDone={() => setFlyTarget(null)}
          />
        </main>
      </div>
    </>
  )
}

export default App
