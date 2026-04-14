import './App.css'
import { useState, useEffect } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel.jsx';
import Map from './components/Map.jsx';
import { apiFetch, clearToken, clearActiveChatId, getToken } from './utils/auth';

import { faLayerGroup, faWrench, faFileExport } from '@fortawesome/free-solid-svg-icons';
import { faMessage } from '@fortawesome/free-regular-svg-icons';

const menuItems = [
    { id: 'Chatbot', label: 'Chatbot', icon: faMessage },
    { id: 'Kartlag', label: 'Kartlag', icon: faLayerGroup },
    { id: 'Verktøy', label: 'Verktøy', icon: faWrench },
    { id: 'Eksporter', label: 'Eksporter', icon: faFileExport },
];

function App() {
  const [activePanel, setActivePanel] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [theme, setTheme] =useState(() => localStorage.getItem('theme') || 'dark');
  const [chatUser, setChatUser] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    async function syncChatUser() {
      if (!getToken()) return;

      try {
        const res = await apiFetch('/api/auth/me');
        if (!res.ok) {
          clearToken();
          clearActiveChatId();
          return;
        }

        const data = await res.json();
        setChatUser({ user_id: data.user_id, email: data.email });
      } catch {
        clearToken();
        clearActiveChatId();
      }
    }

    syncChatUser();
  }, []);

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
  const [selectedTools, setSelectedTools] = useState([]);

  const toggleTool = (tool) => {
    setSelectedTools(prev => {
      const exists = prev.some(t => t.name === tool.name);
      if (exists) return prev.filter(t => t.name !== tool.name);
      return [...prev, tool];
    });
  };

  const clearSelectedTools = () => setSelectedTools([]);

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

  async function handleHeaderLogout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Best-effort logout; local credentials are still cleared below.
    }
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
          onLayerCreated={upsertDrawnLayer}
          onSetDrawnLayerVisible={setDrawnLayerVisible}
          onRemoveDrawnLayer={removeDrawnLayer}
          onFlyToLayer={setFlyTarget}
          chatUser={chatUser}
          onUserChange={setChatUser}
          selectedTools={selectedTools}
          onToggleTool={toggleTool}
          onClearSelectedTools={clearSelectedTools}
          onGoToChat={() => setActivePanel('Chatbot')} />

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
