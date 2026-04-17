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

