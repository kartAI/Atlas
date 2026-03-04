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
        />
        <main className="map-stage">
          <Map />
        </main>
      </div>
    </>
  )
}

export default App
