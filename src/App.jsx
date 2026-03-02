import './App.css'
import { useState } from 'react';
import { Header } from './components/Header.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ContentPanel } from './components/ContentPanel';

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSquarePollVertical } from '@fortawesome/free-solid-svg-icons';
import { faMessage } from '@fortawesome/free-regular-svg-icons';

const menuItems = [
    { id: 'Chatbot', label: 'Chatbot', icon: faMessage },
    { id: 'Kartlag', label: 'Kartlag', icon: faSquarePollVertical },
    { id: 'Analyse', label: 'Analyse', icon: faSquarePollVertical },
    { id: 'Eksporter', label: 'Eksporter', icon: faSquarePollVertical },
];

function App() {
  const [activePanel, setActivePanel] = useState(null);

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
        />
      </div>
    </>
  )
}

export default App