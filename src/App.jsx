import { useState } from "react";
import { Header } from "./components/header.jsx";
import { Sidebar } from "./components/sidebar.jsx";
import { ContentPanel } from "./components/ContentPanel.jsx";
import Map from "./components/map.jsx";

function App() {
  const [activePanel, setActivePanel] = useState(null);

  function handleSelect(item) {
    setActivePanel((current) => (current === item ? null : item));
  }

  return (
    <div className="app">
      <Header />
      <div className="app-body">
        <Sidebar activeItem={activePanel} onSelect={handleSelect} />
        <div className="content">
          <Map />
        </div>
        <ContentPanel activePanel={activePanel} onClose={() => setActivePanel(null)} />
      </div>
    </div>
  );
}

export default App;
