---
layout: default
---

<div align="center">
  <img src="assets/norkartFull.png" alt="Atlas" width="400" />
  <p><em>AI-assistert geospatialt arbeidsverktøy for kartanalyse og KU-relaterte arbeidsflyter</em></p>
</div>

---

## Oversikt

Atlas er en GeoMCP-chatbot utviklet for å assistere saksbehandlere i arbeid med norske konsekvensutredninger (KU). Assistenten kombinerer et interaktivt kart, dokumentbasert kontekst og romlige analyser i ett grensesnitt – og lar brukere stille faglige spørsmål, hente geodata og eksportere kartlag uten å forlate arbeidsflaten.

---

## Mørk og lys modus

![Dark/light mode toggle](assets/EditedLightmode.gif)

Atlas støtter mørk og lys modus med persistent lagring i nettleseren.

---

## Interaktivt kart

![Map overview](assets/Basemaps.gif)

Kartarbeidsområdet er sentrert på Norge med bakgrunnskart fra Kartverket og flyfoto fra Esri.
Brukere kan bytte mellom bakgrunnskart i sanntid.

---

## Tegning og redigering

![Drawing tools](assets/draw-tools.gif)

Leaflet-Geoman gir tilgang til tegning av markører, polygoner, rektangler, linjer og sirkler,
samt redigering og fjerning av eksisterende lag. Posisjonering bruker nettleserens Geolocation API.

## Verktøy i aksjon

**1 — Velg og send verktøy**

![Tool sidebar](assets/SidebarTools.gif)

**2 — Resultat fra assistenten**

![Tool result](assets/ToolUsed.png)

---

## Laghåndtering

![Layer management](assets/MapLayersSidebar.gif)

Hvert kartlag kan skjules, vises på nytt eller slettes fra sidepanelet.
AI-genererte lag og brukerens egne lag behandles likt.

## AI-assistent og chat

![Chat interface](assets/chat-demo.gif)

Autentiserte brukere kan starte, gjenoppta og slette samtaler. Assistenten har tilgang til
MCP-verktøy og kan svare med kartlag som tegnes direkte i grensesnittet.

### Tokenforbruk

![Token usage](assets/tokenusage.gif)

Brukere kan se tokenforbruk per melding direkte i chatten.

---
## Romlige analyser

![Spatial analysis](assets/spatial-analysis.gif)

Bruker kan be assistenten om å kjøre buffersøk, geometrioperasjoner og domenespesifikke
kartoppslag – resultatene dukker opp som lag i kartet uten manuell behandling.

---

## Dokumentsøk

![Document search](assets/doc-search.gif)

Assistenten kan søke i og hente innhold fra PDF-dokumenter lagret i Azure Blob Storage,
og bruke disse som kontekst i svar.

---

## Eksport

![Export panel](assets/export.gif)

Valgte lag kan eksporteres direkte fra nettleseren:

- **GeoJSON** — råformat for videre databehandling
- **JSON** — generisk format
- **PNG** — kartskisse som bilde
- **PDF** — kartskisse klar for rapport

---

## Autentisering

![Auth flow](assets/auth.gif)

Brukere logger inn via et modalt grensesnitt. Passord er bcrypt-hashet, og sesjonstokens
er hashet i databasen. Sesjonstatus lagres i `localStorage`.

---

<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">

<style>
  body.dark { background: #0d1117; color: #c9d1d9; }
  body.dark .page-header { background: #161b22; background-image: none; }
  body.dark .main-content h1,
  body.dark .main-content h2,
  body.dark .main-content h3,
  body.dark .main-content h4 { color: #58a6ff; }
  body.dark .main-content a { color: #58a6ff; }
  body.dark hr { border-color: #30363d; }

  #theme-toggle {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    z-index: 999;
    background: #238636;
    color: #fff;
    border: none;
    border-radius: 2rem;
    padding: 0.5rem 1rem;
    cursor: pointer;
    font-size: 1.1rem;
  }
</style>

<button id="theme-toggle"><i id="theme-icon" class="fa-solid fa-moon"></i></button>

<script>
  const btn = document.getElementById('theme-toggle');
  const apply = dark => {
    document.body.classList.toggle('dark', dark);
    document.getElementById('theme-icon').className = dark ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
  };
  apply(localStorage.getItem('theme') === 'dark');
  btn.addEventListener('click', () => {
    const dark = !document.body.classList.contains('dark');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    apply(dark);
  });
</script>