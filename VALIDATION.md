# Verifica del 1 ottobre 2026

La verifica è stata eseguita su Ubuntu 24.04 x86_64 con Docker e KVM. L'immagine finale usa l'APK archiviato `d77c856.apk`, verificato con lo SHA-256 riportato nel README. Build Docker dei due servizi, compilazione Java/DEX, firma APK e installazione Android sono riuscite.

## Estensioni reali

Il loader originale ha scaricato e caricato tutti i cinque `.cs3` di Zero Tituli. Le chiamate REST al catalogo hanno restituito:

| Estensione / provider | Caricata | Sezioni della prima pagina | Contenuti |
| --- | --- | --- | --- |
| AnimeUnity | Sì | 1 | 20 |
| FCTV33 | Sì | 5 | 16 |
| Hattrick / Hattrick Sport | Sì | 2 | 17 |
| MediasetInfinity / Mediaset Infinity | Sì | 1 | 12 |
| StreamingCommunity | Sì | 1 | 10 |

I conteggi sono una fotografia della verifica e possono cambiare con i siti.

Per Mediaset Infinity è stata verificata l'intera catena REST: catalogo delle dirette, dettagli di Canale 5, risoluzione di uno stream DASH, manifest riscritto dal gateway e frammento di inizializzazione video/audio restituito attraverso il proxy con **HTTP 200**. Il resoconto dell'immagine finale è in `validation.json`; non contiene token API, chiavi o URL di stream.

La pagina web è stata verificata nel browser: autenticazione, elenco sorgenti, catalogo, dettagli, risoluzione e riproduzione della diretta Canale 5. Il video aveva `readyState=4`, `paused=false` e nessun errore; Questa prova del player è stata eseguita con l'APK prerelease dello stesso commit, prima del passaggio all'APK archiviato; con l'APK archiviato sono stati ripetuti importazione, tutti i cataloghi, dettagli, risoluzione, manifest e trasferimento del frammento DASH.

È stata verificata anche la ricerca (`Naruto`: 18 risultati), e la ricostruzione/riavvio con il volume Android preesistente. La versione finale corregge la gestione dei file di blocco dell'AVD. L'app si avvia automaticamente tramite `AccountSelectActivity`, senza interventi sulla schermata Android.

## Test automatici

**7 test passati**:

- autenticazione e validazione degli input;
- HLS: URI di chiavi, mappe, varianti e segmenti;
- DASH: BaseURL, ereditarietà e template;
- firme nelle query DASH che contengono barre;
- redirect e header Range;
- sessioni e schemi URL non supportati;
- frammenti DASH firmati e rifiuto di percorsi con traversal.

Sono passati inoltre i controlli di sintassi Python, JavaScript e shell e la validazione della configurazione Compose.

Non sono stati provati tutti i titoli o tutti gli stream di ogni sorgente, né Widevine. Il caricamento dell'estensione e l'accesso al catalogo non garantiscono la riproducibilità di ogni contenuto. I limiti del player e delle sorgenti sono descritti nel README.

## 2 ottobre 2026 — Accesso LAN senza token

Otto test passati, compresa modalità senza token, autenticazione opzionale
e avvio rifiutato quando il token obbligatorio manca. Sintassi JS, shell e
Compose verificate. HTTP sulla porta LAN configurata: configurazione senza auth,
cinque provider e catalogo Mediaset HTTP 200 senza Authorization.
Browser non automatizzato in questo controllo. La distribuzione su un host aggiuntivo con soli 2 GB di RAM non è stata eseguita,
per memoria insufficiente.

## 2 ottobre 2026 — Repository doGior aggiunto

5 plugin Zero Tituli e 15 doGior caricati dal loader originale, stato ready.
25 provider disponibili con 25 ID distinti; AnimeUnity e StreamingCommunity
compaiono separatamente per repository. Cataloghi AnimeWorld doGior e
AnimeUnity doGior HTTP 200 senza token. Nove test gateway passati; APK
compilato e firma verificata. Nessuna verifica universale degli stream
delle nuove estensioni.
