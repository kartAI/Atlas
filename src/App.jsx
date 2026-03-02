import { useState } from "react";
import { Header } from "./components/Header.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import Map from "./components/Map.jsx";

function App() {
  const [activeItem, setActiveItem] = useState("Kartlag");

  return (
    <div className="app">
      <Header />
      <div className="app-body">
        <Sidebar activeItem={activeItem} onSelect={setActiveItem} />
        <div className="content">
          <Map />
        </div>
      </div>
    </div>
  );
}

export default App;
