import { useState, useMemo } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFilter } from '@fortawesome/free-solid-svg-icons';
import {
  Circle,
  Scissors,
  SquareDot,
  SquaresIntersect,
  Globe,
  CircleDot,
  LayoutGrid,
  FileText,
  Search,
  MapPin,
  Paintbrush,
  Church,
  Check,
  TextSearch,
  Sparkles,
  Blend,
  FolderSearch,
  Landmark,
  ShieldCheck,
  BarChart3,
} from 'lucide-react';

const CATEGORIES = ['Vektor', 'Kulturmiljø', 'Dokumentsøk', 'Dokumenter', 'Kart'];

const ALL_TOOLS = [
  // ── vector_server ──
  { name: 'Buffer',                icon: Circle,           server: 'vector', category: 'Vektor',      desc: 'Lag en buffersone rundt en geometri - f.eks. 500 m radius for nærhetanalyser',                                    mcpTool: 'vector-buffer'                    },
  { name: 'Snitt',                 icon: SquaresIntersect, server: 'vector', category: 'Vektor',      desc: 'Finn det overlappende arealet mellom to geometrier',                                                              mcpTool: 'vector-intersection'              },
  { name: 'Omsluttende rektangel', icon: SquareDot,        server: 'vector', category: 'Vektor',      desc: 'Beregn bounding box (minste omsluttende rektangel) til en geometri',                                              mcpTool: 'vector-envelope'                  },
  { name: 'Hent koordinater',      icon: Globe,            server: 'vector', category: 'Vektor',      desc: 'Trekk ut koordinatpar (lon/lat) fra en geometri',                                                                 mcpTool: 'vector-get_coordinates'           },
  { name: 'Punkt i polygon',       icon: CircleDot,        server: 'vector', category: 'Vektor',      desc: 'Sjekk hvilke punkter som faller innenfor et polygon - f.eks. om lokasjoner er innenfor en vernesone',              mcpTool: 'vector-point_in_polygon'          },
  { name: 'Voronoi',               icon: LayoutGrid,       server: 'vector', category: 'Vektor',      desc: 'Generer Voronoi-diagram fra punkter - deler kartet i innflytelsessoner per punkt',                                mcpTool: 'vector-voronoi'                   },
  { name: 'Verdensarv',            icon: Church,           server: 'vector', category: 'Vektor',      desc: 'Hent alle norske verdensarvsteder med beskrivelse og geometri',                                                   mcpTool: 'vector-get_verdensarv_sites'      },
  // ── geo_server ──
  { name: 'Kulturmiljøsøk',       icon: MapPin,           server: 'geo',    category: 'Kulturmiljø', desc: 'Finn kulturmiljøer innenfor en gitt radius fra et punkt',                                                         mcpTool: 'geo-buffer_search'                },
  { name: 'Kommuner',              icon: Landmark,         server: 'geo',    category: 'Kulturmiljø', desc: 'List kommunenummer og kommunenavn - kan filtreres med søkeord',                                                   mcpTool: 'geo-list_kommuner'                },
  { name: 'Vernetyper',            icon: ShieldCheck,      server: 'geo',    category: 'Kulturmiljø', desc: 'List alle vernetyper for kulturmiljøer',                                                                          mcpTool: 'geo-list_vernetyper'              },
  // ── search_server ──
  { name: 'Fulltekstsøk',         icon: Search,           server: 'search', category: 'Dokumentsøk', desc: 'Søk i dokumenter med norsk fulltekstsøk rangert etter relevans',                                                  mcpTool: 'search-search_documents'          },
  { name: 'Fuzzy-søk',            icon: TextSearch,       server: 'search', category: 'Dokumentsøk', desc: 'Fuzzy-søk med trigram-likhet - finner treff selv med skrivefeil',                                                 mcpTool: 'search-search_documents_fuzzy'    },
  { name: 'Semantisk søk',        icon: Sparkles,         server: 'search', category: 'Dokumentsøk', desc: 'Søk med AI-embeddings - finner dokumenter med lignende betydning',                                                mcpTool: 'search-search_documents_semantic' },
  { name: 'Hybridsøk',            icon: Blend,            server: 'search', category: 'Dokumentsøk', desc: 'Kombinert fulltekst + semantisk + fuzzy for bredest mulig dekning',                                               mcpTool: 'search-search_hybrid'             },
  { name: 'Indekseringsstatus',    icon: BarChart3,        server: 'search', category: 'Dokumentsøk', desc: 'Vis statusoversikt for dokumentindeksering (new, ready, failed)',                                                  mcpTool: 'search-get_indexing_status'       },
  // ── docs_server ──
  { name: 'List dokumenter',       icon: FolderSearch,     server: 'docs',   category: 'Dokumenter',  desc: 'List alle tilgjengelige PDF-dokumenter i Azure Blob Storage',                                                      mcpTool: 'docs-list_documents'              },
  { name: 'Hent dokument',         icon: FileText,         server: 'docs',   category: 'Dokumenter',  desc: 'Hent og les tekstinnholdet fra et spesifikt PDF-dokument',                                                        mcpTool: 'docs-fetch_document'              },
  // ── map_server ──
  { name: 'Tegn på kart',          icon: Paintbrush,       server: 'map',    category: 'Kart',        desc: 'Tegn former, punkter eller linjer direkte på kartet basert på analyseresultater',                                  mcpTool: 'map-draw_shape'                   },
];

const FEATURED_IDS = new Set([
  'vector-buffer', 'vector-intersection', 'vector-voronoi',
  'geo-buffer_search', 'search-search_hybrid', 'map-draw_shape',
]);
const FEATURED_TOOLS = ALL_TOOLS.filter(t => FEATURED_IDS.has(t.mcpTool));

export { ALL_TOOLS };

export function ToolList({ selectedTools = [], onToggleTool, onGoToChat }) {
  const [search, setSearch]               = useState('');
  const [filterOpen, setFilterOpen]       = useState(false);
  const [showAll, setShowAll]             = useState(false);
  const [activeFilters, setActiveFilters] = useState(new Set());
  const [sortAlpha, setSortAlpha]         = useState(false);

  const selectedNames = useMemo(() => new Set(selectedTools.map(t => t.name)), [selectedTools]);

  const isSearching = search.trim().length > 0;
  const hasFilters  = activeFilters.size > 0;

  const visibleTools = useMemo(() => {
    const source = (isSearching || showAll || hasFilters) ? ALL_TOOLS : FEATURED_TOOLS;
    const q = search.toLowerCase();

    let list = source.filter(t =>
      (!hasFilters || activeFilters.has(t.category)) &&
      t.name.toLowerCase().includes(q)
    );

    // Pin featured tools first so they don't shift when expanding
    if (!hasFilters) {
      const pinned  = list.filter(t => FEATURED_IDS.has(t.mcpTool));
      const extras  = list.filter(t => !FEATURED_IDS.has(t.mcpTool));
      list = [...pinned, ...extras];
    }

    if (sortAlpha) {
      if (hasFilters) {
        const matched = list.filter(t => activeFilters.has(t.category));
        const rest    = list.filter(t => !activeFilters.has(t.category));
        matched.sort((a, b) => a.name.localeCompare(b.name, 'nb'));
        rest.sort((a, b) => a.name.localeCompare(b.name, 'nb'));
        return [...matched, ...rest];
      }
      return [...list].sort((a, b) => a.name.localeCompare(b.name, 'nb'));
    }

    return list;
  }, [search, showAll, activeFilters, hasFilters, isSearching, sortAlpha]);

  function toggleFilter(opt) {
    setActiveFilters(prev => {
      const next = new Set(prev);
      next.has(opt) ? next.delete(opt) : next.add(opt);
      return next;
    });
  }

  function clearFilters() {
    setActiveFilters(new Set());
    setSortAlpha(false);
    setFilterOpen(false);
  }

  const badgeCount = activeFilters.size + (sortAlpha ? 1 : 0);

  return (
    <div className="tools-panel">
      <div className="tools-header">
        <h2 className="tools-title">Verktøy</h2>
        <p className="tools-desc">Utforsk tilgjengelige verktøy og bruk dem direkte i chatten.</p>
      </div>

      <div className="tools-top-row">
        <div className="tools-search-wrap">
          <input
            className="tools-search"
            type="text"
            placeholder="Søk etter verktøy..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="tools-filter-wrap">
          <button
            className={`tools-filter-btn${filterOpen ? ' active' : ''}`}
            onClick={() => setFilterOpen(o => !o)}
          >
            <FontAwesomeIcon icon={faFilter} />
            {badgeCount > 0 && <span className="tools-filter-badge">{badgeCount}</span>}
          </button>

          {filterOpen && (
            <div className="tools-filter-dropdown">
              <div className="tools-filter-section-label">Kategori</div>
              {CATEGORIES.map(opt => (
                <button
                  key={opt}
                  className={`tools-filter-option${activeFilters.has(opt) ? ' active' : ''}`}
                  onClick={() => toggleFilter(opt)}
                >
                  {opt}
                </button>
              ))}
              <div className="tools-filter-divider" />
              <div className="tools-filter-section-label">Sortering</div>
              <button
                className={`tools-filter-option${sortAlpha ? ' active' : ''}`}
                onClick={() => setSortAlpha(o => !o)}
              >
                A–Å
              </button>
              {badgeCount > 0 && (
                <button className="tools-filter-option tools-filter-clear" onClick={clearFilters}>
                  Nullstill filter
                </button>
              )}
            </div>
          )}
        </div>

        <button
          className={`tools-showall-btn${showAll ? ' open' : ''}`}
          title={showAll ? 'Vis mindre' : 'Vis alle verktøy'}
          onClick={() => setShowAll(o => !o)}
        >
          {showAll ? '▲' : '▼'}
        </button>
      </div>

      <div className="tools-grid">
        {visibleTools.length > 0 ? visibleTools.map(tool => {
          const Icon = tool.icon;
          const isSelected = selectedNames.has(tool.name);
          return (
            <button
              key={tool.name}
              className={`tools-tool-box${isSelected ? ' selected' : ''}`}
              onClick={() => onToggleTool?.(tool)}
            >
              <span className="tools-tool-box-icon">
                {isSelected
                  ? <Check size={22} strokeWidth={2.5} />
                  : <Icon size={22} strokeWidth={2.1} />}
              </span>
              <span className="tools-tool-box-name">{tool.name}</span>
              <span className="tools-tool-box-desc">{tool.desc}</span>
            </button>
          );
        }) : (
          <p className="tools-no-results">Ingen verktøy matcher søket ditt.</p>
        )}
      </div>

      {selectedTools.length > 0 && (
        <div className="tools-action-bar">
          <span className="tools-action-count">{selectedTools.length} verktøy valgt</span>
          <button className="tools-action-btn" onClick={onGoToChat}>Bruk i chat →</button>
        </div>
      )}
    </div>
  );
}
