# CloudStream Docker Server

Server sperimentale per eseguire estensioni CloudStream `.cs3` originali in Docker e usare cataloghi, ricerca e riproduzione da un browser. Include API REST e player web HLS/DASH. È un progetto indipendente, non un server ufficiale CloudStream.

Sono preconfigurati i repository [Zero Tituli](https://github.com/fixered/zeroTituli) e [doGior's Had Enough](https://github.com/doGior/doGiorsHadEnough). I video provengono dalle sorgenti interrogate dalle estensioni: questo progetto non ospita un catalogo di file video.

## Requisiti

- Host **Linux x86_64**, Docker Engine e Docker Compose v2.
- Virtualizzazione KVM accessibile tramite `/dev/kvm`.
- Almeno **4 GB di RAM totali**, con memoria libera sufficiente per Android e gli altri servizi dell'host.
- Circa **10 GB liberi** per build, immagini e dati Android.
- Connessione Internet per build, repository e sorgenti.

Su VPS serve virtualizzazione annidata. ARM/Raspberry Pi e Docker Desktop non sono supportati da questa configurazione. Un host con soli 2 GB di RAM non è adatto al runtime attuale.

## Installazione

```bash
git clone https://github.com/samuu98/cloudstream-server.git
cd cloudstream-server
bash setup.sh
docker compose up -d --build
```

`setup.sh` crea `.env` e una chiave di firma privata in `android/server.keystore`. Conservare questa chiave per aggiornare l'APK senza perdere i dati Android. Nessuno dei due file va pubblicato in Git.

La prima build scarica SDK, emulatore, immagine Android e APK; richiede alcuni minuti. Dopo l'avvio aprire **http://localhost:8000**. Non serve un token con la configurazione predefinita: la pagina carica automaticamente i provider.

Per seguire l'avvio:

```bash
docker compose ps
docker compose logs -f android gateway
```

## Accesso dagli altri dispositivi della LAN

Modificare `.env`:

```dotenv
AUTH_REQUIRED=false
BIND_ADDRESS=0.0.0.0
PORT=8000
ANDROID_RAM_MB=1536
```

Applicare la modifica:

```bash
docker compose up -d
```

Aprire `http://IP_DEL_SERVER:8000` da telefono, tablet, TV o computer nella stessa rete. Se la porta è già occupata, impostare ad esempio `PORT=8001`. Per usare solo una specifica interfaccia LAN, assegnare a `BIND_ADDRESS` l'IP locale dell'host.

Chi può raggiungere la porta può usare le API e gli stream quando l'autenticazione è disattivata. Questa modalità è pensata per una LAN fidata, senza inoltro della porta sul router. Per accesso esterno usare autenticazione e HTTPS oppure un tunnel SSH.

## Variabili di configurazione

Docker Compose legge `.env` nella cartella del progetto. Vedere [.env.example](.env.example).

| Variabile | Default | Funzione |
| --- | --- | --- |
| `AUTH_REQUIRED` | `false` nel Compose | Se `true`, richiede il token per le API e mostra il modulo di accesso |
| `API_TOKEN` | Vuoto | Obbligatorio solo con autenticazione attiva |
| `BIND_ADDRESS` | `127.0.0.1` | Interfaccia host su cui pubblicare il servizio |
| `PORT` | `8000` | Porta host della pagina web e delle API |
| `ANDROID_RAM_MB` | `1536` | Memoria assegnata alla macchina Android; il consumo complessivo è maggiore |
| `REPOSITORY_URLS` | Zero Tituli e doGior | URL dei manifest dei repository, separati da virgole |

Esempio dei repository attuali:

```dotenv
REPOSITORY_URLS=https://raw.githubusercontent.com/fixered/zeroTituli/master/repo.json,https://raw.githubusercontent.com/doGior/doGiorsHadEnough/builds/repo.json
```

Per aggiungerne uno, aggiungere il suo URL diretto `repo.json` all'elenco e rieseguire `docker compose up -d`. “Aggiorna estensioni” nella pagina ricarica tutti i repository configurati. Se uno fallisce, gli altri vengono comunque tentati.

Per attivare l'autenticazione, generare un token:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Scrivere in `.env` `AUTH_REQUIRED=true` e `API_TOKEN=VALORE_GENERATO`, poi eseguire `docker compose up -d`. Per un tunnel SSH con il binding loopback:

```bash
ssh -L 8000:127.0.0.1:8000 utente@server
```

## Come funziona

```text
Browser + player Shaka / client REST
                 ↓ :8000
           Gateway FastAPI
                 ↓ :18181, solo interno
    CloudStream + bridge HTTP in Android Emulator
                 ↓ loader originale
      repo.json → plugins.json → plugin .cs3
                 ↓
          Sito della sorgente / CDN
```

L'APK ufficiale viene verificato tramite SHA-256, modificato con un hook in `MainActivity` e un DEX aggiuntivo con `ServerBridge.java`, quindi firmato con la chiave locale. Le altre classi e risorse rimangono originali. Il bridge richiama le API CloudStream, incluse coroutine, WebView ed extractors; i plugin passano dal loader originale e dalla sua verifica degli hash.

Il gateway espone cataloghi, ricerca, dettagli e risoluzione. Il menu identifica separatamente i provider omonimi di repository diversi. I video passano attraverso Android e il gateway, che conserva gli header e riscrive manifest HLS/DASH per il browser. Anche la banda video attraversa il server. Non sono implementati download permanenti o transcodifica.

I volumi Docker conservano Android e i dati del gateway. Le sessioni media sono in memoria: scadono dopo un'ora di inattività o al riavvio del gateway; risolvere nuovamente il contenuto per ripartire. ADB e il bridge Android restano interni al container.

## API REST

Documentazione interattiva: **http://localhost:8000/docs**. Con autenticazione attiva, le rotte `/api/*` richiedono `Authorization: Bearer TOKEN`.

| Metodo e rotta | Funzione / corpo JSON |
| --- | --- |
| GET `/health` | Stato generale, senza token |
| GET `/config` | Indica se è richiesta l'autenticazione, senza segreti |
| GET `/api/status` | Stato runtime e caricamento dei repository |
| GET `/api/providers` | Provider installati con `id`, nome, repository e sezioni |
| POST `/api/repository` | `{}`: ricarica i repository configurati |
| POST `/api/provider/home` | `{"provider":"ID","page":1,"section":0}` |
| POST `/api/provider/search` | `{"provider":"ID","query":"testo","page":1}` |
| POST `/api/provider/load` | `{"provider":"ID","url":"URL del catalogo"}` |
| POST `/api/provider/resolve` | `{"provider":"ID","data":"dataUrl o data episodio"}` |

Usare l'`id` restituito da `/api/providers`. Il nome semplice è accettato soltanto se univoco. Per film e dirette risolvere `dataUrl`; per serie/anime usare i dati degli episodi restituiti da `load`. La risoluzione restituisce stream, sottotitoli, header e un `playbackUrl` temporaneo del server. Gli URL `/media/*` consentono la riproduzione a chi li possiede fino alla scadenza.

## Compatibilità e diagnosi

Caricare un plugin non garantisce che ogni suo sito o stream funzioni. Domini, autenticazione, geolocalizzazione e protezioni delle sorgenti sono dipendenze esterne; alcune estensioni richiedono impostazioni personali.

Il player supporta HLS/DASH comuni e ClearKey eventualmente restituito dal plugin. Widevine e flussi di licenza specifici non sono integrati. Non vengono rimossi DRM o controlli di accesso. Sottotitoli, tracce separate, interceptor del player Android e manifest particolari possono richiedere ulteriore integrazione.

```bash
docker compose exec android adb logcat -d -s CS3Server PluginManager
docker compose exec android tail -100 /data/emulator.log
```

La build usa l'APK dell'archivio ufficiale `d77c856.apk`, commit `d77c8564653346b1dc70339e8758a0fc76dd2819`, SHA-256 `f1e08da61668c372548cbca5076f46aa9f3d2b5ffff5f890381df4de8fd93b88`. URL e hash sono in `android/build-apk.sh`: per aggiornare verificare il nuovo APK e ripetere la validazione. Le estensioni sono scaricate dai manifest configurati e possono cambiare indipendentemente dall'app.

## Gestione e test

```bash
# Ricostruire dopo modifiche al codice
docker compose up -d --build

# Arrestare conservando i dati
docker compose down
```

Non usare `docker compose down -v` se si vogliono conservare i volumi Android. Prima degli aggiornamenti conservare `.env`, chiave di firma e un backup dei dati persistenti a servizio fermo.

```bash
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Vedere [VALIDATION.md](VALIDATION.md) per le verifiche effettivamente eseguite e i loro limiti.

## Licenze e provenienza

Adattatore sotto **GPL-3.0**, come CloudStream; licenza in [LICENSE](LICENSE). Sorgente CloudStream corrispondente: [commit d77c856](https://github.com/recloudstream/cloudstream/tree/d77c8564653346b1dc70339e8758a0fc76dd2819). Modifiche e procedura di ricostruzione sono incluse in `android/`.

Shaka Player 4.16.11 è Apache-2.0, con licenza in `gateway/static/LICENSE-shaka.txt`. Android SDK/emulatore e immagini provengono dalle distribuzioni ufficiali Google con le rispettive licenze. Le estensioni appartengono ai rispettivi repository e non sono incluse nel codice pubblicato.
