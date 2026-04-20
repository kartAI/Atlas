---
layout: default
---

<div align="center">
  <img id="atlas-logo" src="assets/norkartFull.png" alt="Atlas" width="400" />
  <p><em>AI-assistert geospatialt arbeidsverktøy for kartanalyse og KU-relaterte arbeidsflyter</em></p>
</div>

---

## Oversikt

Atlas er en GeoMCP-chatbot utviklet for å assistere saksbehandlere i arbeid med norske konsekvensutredninger (KU). Assistenten kombinerer et interaktivt kart, dokumentbasert kontekst og romlige analyser i ett grensesnitt – og lar brukere stille faglige spørsmål, hente geodata og eksportere kartlag uten å forlate arbeidsflaten.

---

## Personlige Brukere

### Registrering

![Register flow](assets/registermodal.gif)

Nye brukere kan registrere seg gjennom logg inn knappen.

### Innlogging 

![Login flow](assets/loginmodal.gif)


Eksisterende brukere logger inn gjennom samme knapp. 

---

## Chat

### Send Melding

![Sende melding](assets/sendChat.gif) 

Enkelt skriv spørsmål eller forespørsler, deretter få svar fra assistenten. 

---

### Samtalehistorikk
![Samtalehistorikk](assets/ChatHistory.gif)

Alle tidligere samtaler vises i sidepanelet. Klikk på en samtale for å åpne den igjen og fortsette der du slapp.

---

### Slette en samtale

![Slette samtale](assets/deleteChats.gif)

Samtaler kan slettes enkeltvis fra historikkpanelet.

---

### Tokenforbruk

![Token usage](assets/tokenusage.gif)

Brukere kan se tokenforbruk per melding direkte i chatten.

---

##  Kart

### Kart Visninger 
![Map overview](assets/Basemaps.gif)

Kartarbeidsområdet er sentrert på Norge med bakgrunnskart fra Kartverket og flyfoto fra Esri.
Brukere kan bytte mellom bakgrunnskart i sanntid.

---

### Tegning i kart

![Drawing tools](assets/MapDraw.gif)

Leaflet gir tilgang til tegning av markører, polygoner, rektangler, linjer og sirkler,
samt redigering og fjerning av eksisterende lag. Posisjonering bruker nettleserens Geolocation API.

### Laghåndtering

![Layer management](assets/MapLayersSidebar.gif)

Hvert kartlag kan skjules, vises på nytt eller slettes fra sidepanelet.
AI-genererte lag og brukerens egne lag behandles likt.

---

## Verktøy i aksjon

**1 — Velg og send verktøy**

![Tool sidebar](assets/SidebarTools.gif)

**2 — Resultat fra assistenten**

![Tool result](assets/ToolUsed.png)

---

## Eksport

![Export panel](assets/ExportLayers.gif)

Valgte lag kan eksporteres direkte fra nettleseren:

- **GeoJSON** — råformat for videre databehandling
- **JSON** — generisk format
- **PNG** — kartskisse som bilde
- **PDF** — kartskisse klar for rapport

---

## Mørk og lys modus

![Dark/light mode toggle](assets/EditedLightmode.gif)

Atlas støtter mørk og lys modus med persistent lagring i nettleseren.

---

<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">

<style>
  body.dark { background: #0d1117; color: #c9d1d9; }
  body.dark hr { border-color: #30363d; }
  body.dark #theme-toggle { color: #fff}

  #theme-toggle {
    position: fixed;
    top: 1.5rem;
    right: 1.5rem;
    z-index: 999;
    background: #238636;
    color: #1a1a1a;
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
    document.getElementbyId('Atlas-logo').src = dark ? 'assets/norkartFull_white.png' : 'assets/norkartFull.png';
  };
  apply(localStorage.getItem('theme') === 'dark');
  btn.addEventListener('click', () => {
    const dark = !document.body.classList.contains('dark');
    localStorage.setItem('theme', dark ? 'dark' : 'light');
    apply(dark);
  });
</script>
