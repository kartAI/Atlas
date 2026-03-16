import { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFilter } from '@fortawesome/free-solid-svg-icons';
import {
  Circle,
  Scissors,
  Ungroup,
  SquareDot,
  MinusCircle,
  SquaresIntersect,
  CircleDotDashed,
  Layers,
  Minimize2,
  SquaresUnite,
  MoveHorizontal,
  LayoutGrid,
} from 'lucide-react';

const FILTER_OPTIONS = ['Overlegg', 'Buffer', 'Forenkling', 'Geometri'];

const ALL_TOOLS = [
  { name: 'Buffer',          icon: Circle,           category: 'Buffer',     desc: 'Opprett en buffersone rundt geometrier'                 },
  { name: 'Snitt',           icon: SquaresIntersect, category: 'Overlegg',   desc: 'Finn overlappende areal mellom to lag'                  },
  { name: 'Forening',        icon: Layers,           category: 'Overlegg',   desc: 'Slå sammen geometrier fra to lag til ett'               },
  { name: 'Klipp',           icon: Scissors,         category: 'Geometri',   desc: 'Klipp et lag til grensen av et annet'                   },
  { name: 'Oppløs',          icon: Ungroup,          category: 'Forenkling', desc: 'Aggreger og slå sammen objekter etter felles attributt' },
  { name: 'Differanse',      icon: MinusCircle,      category: 'Overlegg',   desc: 'Trekk én geometri fra en annen'                         },
  { name: 'Konveks Hylster', icon: SquareDot,        category: 'Geometri',   desc: 'Beregn konvekst hylster for et sett med geometrier'     },
  { name: 'Sentroid',        icon: CircleDotDashed,  category: 'Geometri',   desc: 'Beregn sentroiden til en geometri'                      },
  { name: 'Forenkle',        icon: Minimize2,        category: 'Forenkling', desc: 'Forenkle geometri uten å ødelegge topologien'           },
  { name: 'Romlig Kobling',  icon: SquaresUnite,     category: 'Overlegg',   desc: 'Koble attributter basert på romlige relasjoner'         },
  { name: 'Nærmeste Punkt',  icon: MoveHorizontal,   category: 'Buffer',     desc: 'Finn nærmeste punkter mellom to geometrier'             },
  { name: 'Voronoi',         icon: LayoutGrid,       category: 'Buffer',     desc: 'Generer et Voronoi-diagram fra et punktlag'             },
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
    (showAll || activeFilters.size === 0 || activeFilters.has(t.category)) &&
    t.name.toLowerCase().includes(search.toLowerCase())
  );

  let prioritizedTools = filteredTools;
  let prioritizedCount = 0;

  if (showAll && activeFilters.size > 0) {
    const selectedTools = filteredTools.filter(t => activeFilters.has(t.category));
    const otherTools = filteredTools.filter(t => !activeFilters.has(t.category));
    prioritizedCount = selectedTools.length;
    prioritizedTools = [...selectedTools, ...otherTools];
  }

  const visibleBoxes = sortAlpha
    ? (showAll && activeFilters.size > 0
      ? [
          ...[...prioritizedTools.slice(0, prioritizedCount)].sort((a, b) => a.name.localeCompare(b.name, 'nb')),
          ...[...prioritizedTools.slice(prioritizedCount)].sort((a, b) => a.name.localeCompare(b.name, 'nb')),
        ]
      : [...prioritizedTools].sort((a, b) => a.name.localeCompare(b.name, 'nb')))
    : prioritizedTools;

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
            <FontAwesomeIcon icon={faFilter} />
            {(activeFilters.size > 0 || sortAlpha) && (
              <span className="analysis-filter-badge">{activeFilters.size + (sortAlpha ? 1 : 0)}</span>
            )}
          </button>
          {filterOpen && (
            <div className="analysis-filter-dropdown">
              <div className="analysis-filter-section-label">Kategori</div>
              {FILTER_OPTIONS.map(opt => (
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
        {visibleBoxes.length > 0 ? visibleBoxes.map(tool => {
          const Icon = tool.icon;
          return (
            <button key={tool.name} className={`analysis-tool-box`}>
              <span className="analysis-tool-box-icon">
                {typeof Icon === 'string' ? Icon : <Icon size={22} strokeWidth={2.1} />}
              </span>
              <span className="analysis-tool-box-name">{tool.name}</span>
              <span className="analysis-tool-box-desc">{tool.desc}</span>
            </button>
          );
        }) : (
          <p className="analysis-no-results">Ingen verktøy matcher søket ditt.</p>
        )}
      </div>

    </div>
  );
}