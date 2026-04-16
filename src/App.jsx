import './App.css'
import { useState, useEffect, useRef, useCallback } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel.jsx';
import Map from './components/Map.jsx';
import { apiFetch, clearToken, clearActiveChatId, getActiveChatId, getToken } from './utils/auth';

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

  // Resizable content panel
  const [panelWidth, setPanelWidth] = useState(null); // null = CSS default (40vw)
  const [isPanelDragging, setIsPanelDragging] = useState(false);
  const isDraggingRef = useRef(false);
  const dragStartXRef = useRef(0);
  const dragStartWidthRef = useRef(0);

  const getPanelResizeBounds = useCallback(() => {
    const sidebarWidth = sidebarCollapsed ? 64 : 240;
    const availableWidth = Math.max(window.innerWidth - sidebarWidth - 48, 280);
    const maxWidth = Math.min(Math.round(window.innerWidth * 0.65), availableWidth);
    const minWidth = Math.min(320, maxWidth);
    return { minWidth, maxWidth };
  }, [sidebarCollapsed]);

  const handlePanelResizeMouseDown = useCallback((e) => {
    e.preventDefault();
    const { minWidth, maxWidth } = getPanelResizeBounds();
    const defaultWidth = Math.round(window.innerWidth * 0.4);
    isDraggingRef.current = true;
    setIsPanelDragging(true);
    dragStartXRef.current = e.clientX;
    dragStartWidthRef.current = panelWidth === null
      ? Math.max(minWidth, Math.min(defaultWidth, maxWidth))
      : panelWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [getPanelResizeBounds, panelWidth]);

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!isDraggingRef.current) return;
      const delta = e.clientX - dragStartXRef.current;
      const { minWidth, maxWidth } = getPanelResizeBounds();
      const newWidth = Math.max(minWidth, Math.min(dragStartWidthRef.current + delta, maxWidth));
      setPanelWidth(newWidth);
    };
    const onMouseUp = () => {
      if (!isDraggingRef.current) return;
      isDraggingRef.current = false;
      setIsPanelDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, [getPanelResizeBounds]);

  useEffect(() => {
    const clampPanelWidth = () => {
      setPanelWidth(currentWidth => {
        if (currentWidth === null) return currentWidth;
        const { minWidth, maxWidth } = getPanelResizeBounds();
        return Math.max(minWidth, Math.min(currentWidth, maxWidth));
      });
    };

    clampPanelWidth();
    window.addEventListener('resize', clampPanelWidth);
    return () => window.removeEventListener('resize', clampPanelWidth);
  }, [getPanelResizeBounds]);

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

  const upsertDrawnLayer = (info, options = {}) => {
    setDrawnLayers(previousLayers => {
      const hasExistingLayer = previousLayers.some(layer => layer.id === info.id);

      if (!hasExistingLayer) {
        return [...previousLayers, info];
      }

      return previousLayers.map(layer =>
        layer.id === info.id ? { ...layer, ...info } : layer
      );
    });

    // Persist to DB if an active chat exists and not already persisted by the backend.
    if (!options.persisted) {
      const chatId = getActiveChatId();
      if (chatId && info.geoJson) {
        apiFetch(`/api/chats/${chatId}/layers`, {
          method: 'POST',
          body: JSON.stringify({
            layer_id: info.id,
            name: info.name || 'Untitled layer',
            shape: info.shape || 'Feature',
            visible: info.visible !== false,
            geojson: info.geoJson,
          }),
        }).catch(() => { /* fire-and-forget */ });
      }
    }
  };

  const setDrawnLayerVisible = (id, visible) => {
    setDrawnLayers(prev => prev.map(l => l.id === id ? { ...l, visible } : l));
    const chatId = getActiveChatId();
    if (chatId) {
      apiFetch(`/api/chats/${chatId}/layers/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ visible }),
      }).catch(() => { /* fire-and-forget */ });
    }
  };

  const removeDrawnLayer = (id) => {
    setDrawnLayers(prev => prev.filter(l => l.id !== id));
    const chatId = getActiveChatId();
    if (chatId) {
      apiFetch(`/api/chats/${chatId}/layers/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      }).catch(() => { /* fire-and-forget */ });
    }
  };

  const setDrawnLayersFromDB = (layers) => setDrawnLayers(layers);

  const toggleLayer = (layerId) => {
    setLayers(prev => prev.map(layer => ({
      ...layer,
      visible: layer.id === layerId,
    })));
  }

  const handleSelect = (id) => {
    const next = activePanel === id ? null : id;
    if (!next) setPanelWidth(null); // reset width when panel closes
    setActivePanel(next);
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

  function handlePanelClose() {
    setPanelWidth(null);
    setActivePanel(null);
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
          onClose={handlePanelClose}
          layers={layers}
          onToggleLayer={toggleLayer}
          drawnLayers={drawnLayers}
          onLayerCreated={upsertDrawnLayer}
          onSetDrawnLayers={setDrawnLayersFromDB}
          onSetDrawnLayerVisible={setDrawnLayerVisible}
          onRemoveDrawnLayer={removeDrawnLayer}
          onFlyToLayer={setFlyTarget}
          chatUser={chatUser}
          onUserChange={setChatUser}
          selectedTools={selectedTools}
          onToggleTool={toggleTool}
          onClearSelectedTools={clearSelectedTools}
          onGoToChat={() => setActivePanel('Chatbot')}
          panelWidth={panelWidth} />

        {activePanel && (
          <div
            className={`panel-resize-handle${isPanelDragging ? ' panel-resize-handle--active' : ''}`}
            onMouseDown={handlePanelResizeMouseDown}
            aria-hidden="true"
          />
        )}

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
