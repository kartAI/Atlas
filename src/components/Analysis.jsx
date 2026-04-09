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
  FileText,
  Search,
  MapPin,
  Paintbrush,
  Church,
  Check,
} from 'lucide-react';

const FILTER_OPTIONS = ['Overlegg', 'Buffer', 'Forenkling', 'Geometri', 'Data', 'Kart'];

const ALL_TOOLS = [
  // Spatial / vector operations (vector_server)
  { name: 'Buffer',          icon: Circle,           category: 'Buffer',     desc: 'Lag en buffersone (f.eks. 500m radius) rundt punkter, linjer eller flater for nærhetanalyser',   mcpTool: 'vector-buffer'      },
  { name: 'Snitt',           icon: SquaresIntersect, category: 'Overlegg',   desc: 'Finn det overlappende arealet mellom to geometrier — nyttig for å se hva som finnes innenfor et bestemt område', mcpTool: 'vector-intersection' },
  { name: 'Forening',        icon: Layers,           category: 'Overlegg',   desc: 'Slå sammen to eller flere geometrier til én samlet flate',            mcpTool: 'vector-intersection' },
  { name: 'Klipp',           icon: Scissors,         category: 'Geometri',   desc: 'Klipp et geometrilag til grensene av et annet — bruk for å begrense data til et interesseområde',   mcpTool: 'vector-intersection' },
  { name: 'Oppløs',          icon: Ungroup,          category: 'Forenkling', desc: 'Aggreger mange objekter til færre basert på felles attributt, f.eks. slå sammen kommuner i et fylke', mcpTool: 'vector-intersection' },
  { name: 'Differanse',      icon: MinusCircle,      category: 'Overlegg',   desc: 'Fjern én geometri fra en annen — f.eks. finn arealet utenfor en buffersone',               mcpTool: 'vector-intersection' },
  { name: 'Konveks Hylster', icon: SquareDot,        category: 'Geometri',   desc: 'Beregn det minste omsluttende polygonet rundt et sett av punkter eller geometrier',     mcpTool: 'vector-envelope'    },
  { name: 'Sentroid',        icon: CircleDotDashed,  category: 'Geometri',   desc: 'Finn midtpunktet (sentroiden) til en flate — nyttig for å plassere etiketter eller markører', mcpTool: 'vector-get_coordinates' },
  { name: 'Forenkle',        icon: Minimize2,        category: 'Forenkling', desc: 'Redusér antall punkter i en geometri for raskere visning uten å miste den overordnede formen',       mcpTool: 'vector-envelope'    },
  { name: 'Romlig Kobling',  icon: SquaresUnite,     category: 'Overlegg',   desc: 'Koble attributter fra et lag til et annet basert på romlig overlapp (spatial join)',       mcpTool: 'vector-point_in_polygon' },
  { name: 'Nærmeste Punkt',  icon: MoveHorizontal,   category: 'Buffer',     desc: 'Finn de nærmeste punktene mellom to geometrier — f.eks. avstand til nærmeste vei eller bygning', mcpTool: 'vector-get_coordinates' },
  { name: 'Voronoi',         icon: LayoutGrid,       category: 'Buffer',     desc: 'Generer Voronoi-diagram fra punkter — deler kartet i soner der hvert punkt har sitt nærmeste område', mcpTool: 'vector-buffer'      },
  // Data / lookup tools
  { name: 'Søk dokumenter',  icon: Search,           category: 'Data',       desc: 'Søk i indekserte PDF-dokumenter med fulltekst, fuzzy eller semantisk søk',                        mcpTool: 'search-search_hybrid' },
  { name: 'Hent dokument',   icon: FileText,         category: 'Data',       desc: 'Hent og les innholdet i et bestemt PDF-dokument fra dokumentlageret',                            mcpTool: 'docs-fetch_document' },
  // Geo / cultural environment
  { name: 'Kulturmiljøsøk',  icon: MapPin,          category: 'Kart',       desc: 'Finn kulturmiljøer innenfor en gitt radius fra et punkt — søk etter fredede områder nær en lokasjon', mcpTool: 'geo-buffer_search'   },
  { name: 'Verdensarv',      icon: Church,         category: 'Kart',       desc: 'Hent alle norske verdensarvsteder med beskrivelse og geometri, og vis dem på kartet',             mcpTool: 'vector-get_verdensarv_sites' },
  { name: 'Tegn på kart',    icon: Paintbrush,       category: 'Kart',       desc: 'Be AI-en tegne former, punkter eller linjer direkte på kartet basert på analyseresultater',       mcpTool: 'map-draw_shape'       },
];

const FEATURED_TOOLS = ALL_TOOLS.slice(0, 6);

export { ALL_TOOLS };

export function Analysis({ selectedTools = [], onToggleTool, onGoToChat }) {
  const [search, setSearch]         = useState('');
  const [filterOpen, setFilterOpen] = useState(false);
  const [showAll, setShowAll]       = useState(false);
  const [activeFilters, setActiveFilters] = useState(new Set());
  const [sortAlpha, setSortAlpha]         = useState(false);

  const selectedNames = new Set(selectedTools.map(t => t.name));

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
                  {opt}
                </button>
              ))}
              <div className="analysis-filter-divider" />
              <div className="analysis-filter-section-label">Sortering</div>
              <button
                className={`analysis-filter-option${sortAlpha ? ' active' : ''}`}
                onClick={() => setSortAlpha(o => !o)}
              >
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
          const isSelected = selectedNames.has(tool.name);
          return (
            <button
              key={tool.name}
              className={`analysis-tool-box${isSelected ? ' selected' : ''}`}
              onClick={() => onToggleTool?.(tool)}
            >
              <span className="analysis-tool-box-icon">
                {isSelected
                  ? <Check size={22} strokeWidth={2.5} />
                  : (typeof Icon === 'string' ? Icon : <Icon size={22} strokeWidth={2.1} />)}
              </span>
              <span className="analysis-tool-box-name">{tool.name}</span>
              <span className="analysis-tool-box-desc">{tool.desc}</span>
            </button>
          );
        }) : (
          <p className="analysis-no-results">Ingen verktøy matcher søket ditt.</p>
        )}
      </div>

      {/* Floating action bar when tools are selected */}
      {selectedTools.length > 0 && (
        <div className="analysis-action-bar">
          <span className="analysis-action-count">
            {selectedTools.length} verktøy valgt
          </span>
          <button className="analysis-action-btn" onClick={onGoToChat}>
            Bruk i chat →
          </button>
        </div>
      )}

    </div>
  );
}