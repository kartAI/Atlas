import { useState } from 'react';

const FILTER_OPTIONS = ['Alle', 'Overlegg', 'Buffer', 'Forenkling', 'Geometri'];

const ALL_TOOLS = [
  { name: 'Buffer',         icon: '⬡', category: 'Buffer', desc: 'Opprett en buffersone rundt geometrier',                colorClass: 'tool-purple' },
  { name: 'Snitt',          icon: '⊗', category: 'Overlegg',          desc: 'Finn overlappende areal mellom to lag',                 colorClass: 'tool-blue'   },
  { name: 'Forening',       icon: '⊕', category: 'Overlegg',          desc: 'Slå sammen geometrier fra to lag til ett',              colorClass: 'tool-blue'   },
  { name: 'Klipp',          icon: '✂', category: 'Geometri',          desc: 'Klipp et lag til grensen av et annet',                  colorClass: 'tool-green'  },
  { name: 'Oppløs',         icon: '◎', category: 'Forenkling',    desc: 'Aggreger og slå sammen objekter etter felles attributt', colorClass: 'tool-amber'  },
  { name: 'Differanse',     icon: '⊖', category: 'Overlegg',          desc: 'Trekk én geometri fra en annen',                        colorClass: 'tool-blue'   },
  { name: 'Konveks Skrog',  icon: '△', category: 'Geometri',          desc: 'Beregn konvekst skrog for et sett med geometrier',      colorClass: 'tool-green'  },
  { name: 'Sentroid',       icon: '⊙', category: 'Geometri',          desc: 'Beregn sentroiden til en geometri',                     colorClass: 'tool-green'  },
  { name: 'Forenkle',       icon: '〜', category: 'Forenkling',   desc: 'Forenkle geometri uten å ødelegge topologien',          colorClass: 'tool-amber'  },
  { name: 'Romlig Kobling', icon: '⋈', category: 'Overlegg',          desc: 'Koble attributter basert på romlige relasjoner',        colorClass: 'tool-blue'   },
  { name: 'Nærmeste Punkt', icon: '↔', category: 'Buffer', desc: 'Finn nærmeste punkter mellom to geometrier',            colorClass: 'tool-purple' },
  { name: 'Voronoi',        icon: '⬢', category: 'Buffer', desc: 'Generer et Voronoi-diagram fra et punktlag',            colorClass: 'tool-purple' },
];

const FEATURED_TOOLS = ALL_TOOLS.slice(0, 6);

export function Analysis() {
  const [search, setSearch]         = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [showAll, setShowAll]       = useState(false);
  const [activeFilters, setActiveFilters] = useState(new Set());
  const [sortAlpha, setSortAlpha]         = useState(false);

  function toggleFilter(opt) {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(opt)) next.delete(opt); else next.add(opt);
      return next;
    });
  }

  const sourceTools = (showAll || activeFilters.size > 0) ? ALL_TOOLS : FEATURED_TOOLS;
  const filteredTools = sourceTools.filter(t =>
    (activeFilters.size === 0 || activeFilters.has(t.category)) &&
    t.name.toLowerCase().includes(search.toLowerCase())
  );
  const visibleBoxes = sortAlpha
    ? [...filteredTools].sort((a, b) => a.name.localeCompare(b.name, 'nb'))
    : filteredTools;

  return (
    <div className="analysis-panel">

      {/* Header */}
      <div className="analysis-header">
        <h2 className="analysis-title">Analyser</h2>
        <p className="analysis-desc">
          Kjør geospatiale analyser ved å bruke geoMCP-verktøyene.
        </p>
      </div>

      {/* Search + Filter row */}
      <div className="analysis-top-row">
        <div className="analysis-search-wrap">
          <input
            className="analysis-search"
            type="text"
            placeholder="Søk etter verktøy..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="analysis-filter-wrap">
          <button
            className={`analysis-filter-btn${filterOpen ? ' active' : ''}`}
            onClick={() => setFilterOpen(o => !o)}
          >
            ⚙ Filter
            {(activeFilters.size > 0 || sortAlpha) && (
              <span className="analysis-filter-badge">{activeFilters.size + (sortAlpha ? 1 : 0)}</span>
            )}
          </button>
          {filterOpen && (
            <div className="analysis-filter-dropdown">
              <div className="analysis-filter-section-label">Kategori</div>
              {FILTER_OPTIONS.filter(o => o !== 'Alle').map(opt => (
                <button
                  key={opt}
                  className={`analysis-filter-option${activeFilters.has(opt) ? ' active' : ''}`}
                  onClick={() => toggleFilter(opt)}
                >
                  <span className="analysis-filter-check">{activeFilters.has(opt) ? '✓' : ''}</span>
                  {opt}
                </button>
              ))}
              <div className="analysis-filter-divider" />
              <div className="analysis-filter-section-label">Sortering</div>
              <button
                className={`analysis-filter-option${sortAlpha ? ' active' : ''}`}
                onClick={() => setSortAlpha(o => !o)}
              >
                <span className="analysis-filter-check">{sortAlpha ? '✓' : ''}</span>
                A–Å
              </button>
              {(activeFilters.size > 0 || sortAlpha) && (
                <button
                  className="analysis-filter-option analysis-filter-clear"
                  onClick={() => { setActiveFilters(new Set()); setSortAlpha(false); setFilterOpen(false); }}
                >
                  Nullstill filter
                </button>
              )}
            </div>
          )}
        </div>

        <button
          className={`analysis-showall-btn${showAll ? ' open' : ''}`}
          title={showAll ? 'Vis mindre' : 'Vis alle verktøy'}
          onClick={() => setShowAll(o => !o)}
        >
          {showAll ? '▲' : '▼'}
        </button>
      </div>

      {/* Tool grid */}
      <div className="analysis-grid">
        {visibleBoxes.length > 0 ? visibleBoxes.map(tool => (
          <button key={tool.name} className={`analysis-tool-box ${tool.colorClass}`}>
            <span className="analysis-tool-box-icon">{tool.icon}</span>
            <span className="analysis-tool-box-name">{tool.name}</span>
            <span className="analysis-tool-box-desc">{tool.desc}</span>
          </button>
        )) : (
          <p className="analysis-no-results">Ingen verktøy matcher søket ditt.</p>
        )}
      </div>

    </div>
  );
}