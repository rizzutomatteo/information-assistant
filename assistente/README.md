# Assistente assicurativo di Velaria

L'assistente risponde alle domande sui prodotti di una compagnia assicurativa cercando nei suoi
documenti: è il **RAG** del progetto, un'API del gruppo (`POST /turno`). Questo progetto è tutto
ciò che gli sta intorno: il sito dimostrativo di **Velaria**, una compagnia fittizia, con la chat
scritta, i documenti da consultare, l'accesso con le polizze di ogni utente e il **canale voce**,
cioè le chiamate dal sito e le telefonate al numero vero. Chat e voce mandano le domande alla
stessa API; finché quella vera non c'è, ne fa le veci una finta API.

```
browser ─┬─ pagine, documenti, chat scritta ──── sito/    ─┐
         ├─ registrazione, accesso, polizze ──── accesso/  │ POST /turno (SSE)
         └─ chiamata dal sito (WebRTC) ───┐                ├──────────────────▶ API dell'assistente
telefono ── centralino (Asterisk) ────────┴──── voce/    ─┘   rag/              (il RAG)
```

| Parte | Dove | Cosa fa |
|---|---|---|
| Sito | `src/assistente/sito/` | la home page di Velaria, i documenti con le ancore per i link del RAG, la chat scritta |
| Accesso | `src/assistente/accesso/` | registrazione, accesso con password, Google o PIN telefonico, polizze di ogni utente, utenti di prova (`/a`) |
| Voce | `src/assistente/voce/`, `voce/` | le chiamate dal sito e le telefonate: voce → testo → API → testo → voce |
| RAG | `src/assistente/rag/` | il client dell'API dell'assistente, lo stesso per chat e voce, e la finta API |

Costa zero: niente servizi a pagamento (vedi «Il canale voce»).

## Con Docker

Serve solo Docker (con Compose). Dalla cartella del progetto:

```bash
docker compose up -d --build     # la prima volta costruisce l'immagine (3,7 GB, con i modelli)
```

Poi si apre <http://localhost:8002> (un'altra porta con `PORTA=8080` nel file `.env`). Partono due
container: il sito (`sito`) e la finta API dell'assistente (`finta-api`); utenti e polizze restano
nel volume `dati` anche dopo `docker compose down`.

- Chat, documenti, registrazione, accesso e polizze funzionano su qualsiasi macchina.
- Le **chiamate dal browser**: su Linux, aprendo il sito dalla stessa macchina, l'audio arriva
  diretto al container. Su Windows e Mac, o da un altro computer, serve il TURN di Cloudflare
  (gratuito): la sua chiave va nel file `.env` (`CLOUDFLARE_TURN_KEY_ID` e
  `CLOUDFLARE_TURN_KEY_TOKEN`). Il microfono funziona solo su `localhost` o in HTTPS.
- Facoltativi, nel file `.env` (vedi `.env.example`): `AMMINISTRAZIONE_PASSWORD` per la pagina
  `/a`, `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` per «Accedi con Google», `GROQ_API_KEY` per
  trascrivere la voce con Whisper su Groq invece che sulla CPU.

La VPS del progetto usa invece `docker-compose.vps.yml` (vedi «Sulla VPS»).

## Provarlo in 3 comandi, senza Docker

Serve Python 3.11 o più recente. La prima volta si scaricano le due voci di Piper, italiana e
inglese (60 MB ciascuna), e Whisper `small` (480 MB).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install --no-deps -e ".[test]"

finta-api &      # una finta API dell'assistente, sulla porta 8001 (vedi sotto)
assistente       # il server: sito, chat, accesso e voce, sulla porta 8002
```

Poi si apre <http://localhost:8002>: è la home page dimostrativa (sotto). Il pulsante «Assistente»
apre la chat; il microfono, nella chat o in cima alla pagina, avvia la chiamata. Il microfono
funziona solo in HTTPS o su `localhost`: vedi [Dal telefono](#dal-telefono).

Una chiamata di prova senza browser né microfono, che dice le domande con Piper e misura i tempi:

```bash
prova-chiamata "Cos'è la franchigia?" "Voglio parlare con un operatore"
prova-chiamata --lingua en "What is the excess?"
```

I test (nessun modello né rete): `pytest`. Sono divisi come il codice: `tests/sito/`,
`tests/accesso/`, `tests/voce/`, `tests/rag/`, più `tests/test_server.py` per il server intero.

## La pagina dimostrativa

Il server fa la home page di **Velaria**, una compagnia assicurativa fittizia: prodotti e
istruzioni per i sinistri vengono dai documenti anonimizzati del gruppo (`documenti/`, che il sito
mostra anche, vedi «I documenti»), mentre
recapiti e dati societari sono segnaposto evidenti (numeri a zeri, indirizzi `@example.com`),
tranne il numero dell'assistente, lo 0733 145 0210, attivo h24 (in cima alla pagina, nelle sezioni
dell'assistente, dei sinistri e dei contatti, e nell'area riservata accanto al PIN). In
basso a destra c'è l'assistente, in un pannello solo:

- **scritto**: la domanda va a `POST /api/chat` del server, che la passa all'API
  (`/turno`, canale `chat`) e restituisce la domanda e poi gli eventi dell'API; la chat mostra
  gli stati («Cerco nei documenti…») e poi la risposta;
- **a voce**: il microfono avvia la chiamata WebRTC; la trascrizione, gli stati e la risposta
  arrivano sul canale dati con gli stessi campi e finiscono nella stessa chat.

**La pagina è fatta in Python** (`sito/pagina.py`), con i modelli Jinja2 di `sito/pagine/`: `base.html` per
ciò che hanno tutte le pagine (testata, icone, piede), `pagina.html` per la home page,
`documenti.html` e `documento.html` per i documenti, `messaggio.html` per i messaggi della chat. Il server la compone a ogni visita,
nella lingua scelta e con l'area riservata di chi ha fatto l'accesso. Anche i messaggi della chat
li fa il server: a ogni evento, che arrivi da `/api/chat` o dal canale dati della chiamata,
aggiunge `html` (il messaggio pronto, con la risposta in Markdown e le fonti) e `attesa` (la riga
sotto la conversazione, vuota quando l'assistente ha finito). Il testo che viene da fuori (la
domanda, la risposta, le citazioni) passa dal modello, che ne neutralizza l'HTML. Nel browser
restano solo le cose che il server non può fare: in `sito/statico/assistente.js` il pannello, la
lettura della risposta che arriva man mano e la chiamata (microfono e WebRTC), in
`sito/statico/accesso.js` la finestra di accesso.

Chat e voce usano la stessa `sessione`, quindi per l'API sono una conversazione sola. Caratteri:
Plus Jakarta Sans e Instrument Serif (SIL Open Font License), serviti dal sito; icone Lucide (ISC).

**La lingua** si sceglie con le bandiere italiana e inglese in alto: chiedono la pagina con
`?lingua=en` (o `it`), il server la ricorda in un cookie e ricarica la pagina nella lingua nuova.
La conversazione e il pannello aperto passano alla pagina nuova; durante una chiamata le bandiere
sono spente, perché ricaricare la pagina farebbe cadere la chiamata. Tutti i testi stanno in
`testi.py`, con italiano e inglese affiancati (`Testo("Accedi", "Sign in")`), anche quelli degli
script, che la pagina passa loro nella sua lingua. Un testo che manca è un errore, e un test
controlla che ognuno abbia le due lingue.

Anche l'assistente risponde nella lingua scelta: la pagina la manda con ogni domanda e con ogni
chiamata, e il server la passa all'API (campo `lingua`, vedi il contratto). In una chiamata
inglese Whisper ascolta in inglese, Piper parla con la voce `en_GB-cori-medium` e `parlato.py`
legge numeri, importi, date e ore all'inglese (inglese britannico, come la bandiera). Una
chiamata resta nella lingua in cui è partita; al telefono si parla sempre italiano. I dati delle
polizze restano in italiano.

**L'accesso** (`accesso/`, `sito/statico/accesso.js`) si apre dal pulsante «Accedi» in alto
oppure dalla chat quando l'API risponde che serve (`accesso: true`, vedi il contratto): la risposta
ha allora un pulsante «Accedi» che apre la stessa finestra. La finestra ha due schede:

- **Registrati** crea un account: nome, cognome ed email facoltativi, utente (3-40 caratteri:
  lettere, cifre, `.` `_` `-`, salvato in minuscolo) e password (almeno 8 caratteri). Si entra
  subito, senza polizze: le aggiunge l'utente. Il sito pubblico è aperto a tutti, quindi dopo 30
  registrazioni in un'ora la successiva aspetta;
- **Accedi** entra **con utente e password**: di chi si è registrato o degli utenti di prova
  caricati dalla pagina `/a` (vedi «Utenti e polizze»). Dopo 5 password sbagliate per lo stesso
  utente si aspettano 15 minuti.

Sotto le due schede c'è l'accesso **con Google**: il pulsante «Accedi con Google» è della pagina
(con lo stile del sito, chiaro e scuro) e apre una finestra di Google (Google Identity Services,
modello «codice», caricato la prima volta che si apre l'accesso). Alla fine Google dà alla pagina un
codice monouso; la pagina lo manda a `POST /api/accesso` e il server lo scambia con Google, con il
client secret, per un ID token (un JWT firmato con nome ed email). Il server lo verifica con le
chiavi pubbliche di Google (firma, destinatario uguale al client ID, emittente, scadenza, email
verificata) ed entra come l'utente con quella email; se non c'è, lo crea con dati e polizze di prova
(prodotti e garanzie sono quelli dei DIP di Velaria Auto e Casa Velaria, mentre numeri, targa,
scadenze e premi sono finti). Senza client OAuth il pulsante non c'è.

In cima alla pagina compare allora l'area riservata con i dati e le polizze dell'utente, e il suo
**PIN telefonico** per farsi riconoscere quando si chiama il numero. Con «Aggiungi una polizza»
l'utente se ne aggiunge una (prodotto del catalogo, numero, scadenza, cosa assicura, premio,
garanzie), e con «Togli» la toglie. L'area la fa il server, come il resto della pagina: dopo
l'accesso, l'uscita e ogni polizza aggiunta o tolta, la pagina riprende dal server solo l'area e il
pulsante in alto, quindi la chat e un'eventuale chiamata restano come sono.

Serve un client OAuth di Google (Google Cloud Console, «Client» di tipo «Applicazione web», con
l'indirizzo del sito tra le «Origini JavaScript autorizzate»; nessun URI di reindirizzamento),
in `ASSISTENTE_GOOGLE_CLIENT_ID` e `ASSISTENTE_GOOGLE_CLIENT_SECRET` (con docker compose il secret sta nel
file `.env`, come `GOOGLE_CLIENT_SECRET`). Il client ID non è un segreto, il client secret sì.
Senza nessuno dei due si entra solo con utente e password. Finché l'app di Google è «In test»,
possono entrare solo gli account elencati tra gli utenti di prova (Google Auth Platform,
«Pubblico»).

La sessione è un cookie `HttpOnly`, `Secure`, `SameSite=Strict`; le sessioni stanno in memoria e
si perdono quando il server riparte. Per `Strict` il browser non manda il cookie a chi arriva da un
link di un altro sito: la pagina si apre senza l'area riservata, che ricompare ricaricandola. Il
server legge il cookie per la pagina e in `/api/chat` e `/api/offer`, dove passa il token all'API
come `Authorization: Bearer`: l'API sa che l'utente ha fatto l'accesso, per scritto e al
telefono. La chiamata usa l'accesso che c'era quando è partita: chi accede durante una chiamata
deve riattaccare e richiamare.

| Endpoint | Cosa fa |
|---|---|
| `POST /api/registrazione` | `nome`, `utente`, `password` (e facoltativi `cognome`, `email`) → account nuovo, già dentro (409 con `campo` se nome utente o email sono già usati, 429 dopo troppe registrazioni) |
| `POST /api/accesso/password` | `utente` e `password` → cookie di sessione e dati dell'utente (401 se sbagliati, 429 dopo troppi tentativi) |
| `POST /api/accesso` | codice di Google (`codice`) → cookie di sessione e dati dell'utente (401 se non valido, 503 senza client OAuth) |
| `POST /api/uscita` | chiude la sessione |
| `POST /api/polizze` | aggiunge una polizza a chi è entrato (stessi campi del JSON di `/a`) → `{"id": …}` |
| `DELETE /api/polizze/<id>` | toglie una sua polizza (404 se non è sua) |

### Utenti e polizze

Utenti e polizze stanno in un file SQLite (`accesso/utenti.py`, `ASSISTENTE_UTENTI`): con docker compose è
`dati/utenti.sqlite`, lo stesso per le due copie del sito, che così restano allineate. Le password
non si salvano: si salva la loro impronta scrypt, con un sale diverso per ognuna. Al primo avvio
c'è solo Mario Rossi, senza password, con il PIN `123456` delle prove al telefono. Ogni utente ha
un PIN telefonico diverso, perché al telefono il PIN da solo dice chi è.

Gli utenti di prova si caricano dalla pagina **`/a`** (`accesso/amministrazione.py`), protetta dalla
password `ASSISTENTE_AMMINISTRAZIONE_PASSWORD` (con docker compose `AMMINISTRAZIONE_PASSWORD` nel file
`.env`; senza, la pagina non c'è). Si incolla un JSON come quello dello stampino
`src/assistente/accesso/esempio_utenti.json` (il pulsante «Usa l'esempio» lo mette nel campo):

```json
{
  "utenti": [
    {
      "utente": "giulia.verdi",
      "password": "una-password-lunga",
      "nome": "Giulia",
      "cognome": "Verdi",
      "email": "giulia.verdi@example.com",
      "codice_fiscale": "VRDGLI90A41A000X",
      "telefono": "+39 000 000 0004",
      "indirizzo": "Via Esempio, 2 – 00000 Città",
      "pin_telefono": "246810",
      "polizze": [
        {
          "prodotto": "Velaria Auto",
          "numero": "0000000101",
          "oggetto": "Autovettura targata AB000CD",
          "scadenza": "2027-09-30",
          "premio": 520.0,
          "garanzie": ["Responsabilità civile", "Furto e Incendio", "Cristalli"]
        }
      ]
    }
  ]
}
```

| Campo | Regola |
|---|---|
| `utente` | obbligatorio; minuscole, cifre, `.` `_` `-`, da 3 a 40 caratteri |
| `password` | obbligatoria; almeno 8 caratteri |
| `nome` | obbligatorio |
| `cognome`, `codice_fiscale`, `telefono`, `indirizzo` | facoltativi |
| `email` | facoltativa; chi entra con Google con questa email è questo utente |
| `pin_telefono` | facoltativo, 6 cifre; se manca se ne sceglie uno libero |
| `polizze` | facoltativo; `prodotto` è uno del catalogo (Velaria Auto, Velaria Moto, Velaria Furgoni&Van, Velaria Altri Veicoli, Velaria Natanti, Velaria Monopattini Elettrici, Casa Velaria, Mutuo Velaria, Velaria Viaggi, Assicurazione Vita Velaria, Previdente formula su misura, Piano Risparmio Velaria, Pensione Integrativa Velaria), `scadenza` è `AAAA-MM-GG`, `premio` in euro, `garanzie` un elenco (anche vuoto) |

Un utente con un nome che c'è già viene sostituito, polizze comprese (il PIN resta, se il JSON non
ne dà uno). Il caricamento è tutto o niente: con un campo sbagliato, un doppione nel file o un PIN
o un'email di un altro utente non cambia nulla, e la pagina dice dove sta l'errore.

## I documenti

Il sito mostra i documenti dei prodotti (condizioni di assicurazione, DIP, KID, moduli…), gli
stessi da cui il RAG prende i pezzi: i 138 file Markdown anonimizzati di `documenti_anonimi.zip`,
nella cartella del Drive del gruppo «DOCUMENTI E FAQ ANONIMIZZATI», scompattati in `documenti/`
(`<area>/<nome>.md`). Le aree sono le quattro della home page: `auto_e_altri_veicoli`,
`casa_e_famiglia`, `vita_e_risparmio`, `previdenza`.

| Indirizzo | Cosa c'è |
|---|---|
| `/documenti` | l'elenco, diviso per area (`/documenti#casa_e_famiglia` porta a un'area); ci si arriva dal menu in alto e dal link «Documenti» di ogni area dei prodotti |
| `/documenti/<area>/<nome>` | un documento: il percorso del file senza `.md` |
| `…#pagina-N` | la pagina N del PDF originale (il commento `<!-- pagina N -->` del file) |
| `…#<titolo>` | un titolo del documento, con l'ancora fatta dal testo: «Che cosa è assicurato?» → `#che-cosa-e-assicurato` (se due titoli sono uguali, il secondo diventa `…_1`) |

Così il RAG ricava il link dal file e dalla pagina del pezzo che cita, senza tabelle a parte:

```
casa_e_famiglia/dip_documento_informativo_precontrattuale_casa.md, pagina 2
→ /documenti/casa_e_famiglia/dip_documento_informativo_precontrattuale_casa#pagina-2
```

`sito/documenti.py` legge i file all'avvio e fa l'HTML di un documento la prima volta che qualcuno lo
apre (Python-Markdown, con le tabelle). Il titolo viene dal nome del file («DIP casa»), con il
prodotto e l'edizione scritti in testa al file quando ci sono («· Casa Velaria - ed. 10/2026»):
distinguono le edizioni di uno stesso documento (`…_auto`, `…_auto_2`). Nei file non c'è HTML a
parte i commenti, e il sito non lo lascerebbe passare: un `<` resta testo. I documenti sono in
italiano anche nella pagina inglese.

Per aggiornarli: si scompatta lo zip nuovo al posto di `documenti/` e si ricostruisce l'immagine
(`docker compose up -d --build`), che li contiene (`ASSISTENTE_DOCUMENTI=/app/documenti`). Il resto della
cartella del Drive (FAQ, script e registri dell'anonimizzazione) è in `documenti_drive/`, fuori
dall'immagine: `sostituzioni.tsv` e `anonimizzazione.tsv` hanno i nomi reali e non vanno pubblicati.

## La finta API

L'API vera dell'assistente non esiste ancora, quindi `finta-api` ne fa le veci. Ha lo stesso
contratto (sotto) e manda gli stati del grafo descritto nella relazione (`input_guard`,
`classify`, `retrieve`, `grade`), con attese che simulano i tempi. Non ha ancora una base di
conoscenza, quindi risponde solo a due frasi di esempio, nella lingua chiesta (`lingua`: le
risposte e gli stati qui sotto, oppure gli stessi in inglese):

| Messaggio | Risposta |
|---|---|
| «ciao» (o «salve», «buongiorno», «buonasera», «hello», «hi», «good morning»…) | «Ciao, come posso esserti utile?» |
| «le mie info» (o «le mie informazioni», «la mia polizza», «voglio fare l'accesso», «login», «my information», «sign in»…) | da ospite, che serve l'accesso, con `accesso: true` (al telefono «Per continuare devo sapere chi sei.»); con l'accesso già fatto, «Hai già fatto l'accesso: come posso esserti utile?» |
| tutto il resto | «Mi dispiace, questa informazione non è nella mia base di conoscenza.» |

La richiesta di accesso simula quello che farà l'API vera quando una domanda riguarda i dati
dell'utente (la sua polizza, i suoi sinistri) e l'utente è ancora ospite.

Quando l'API vera c'è, basta `ASSISTENTE_API_URL=http://…` e la finta API non serve più.

## Il contratto con l'API

È lo stesso della web chat, con in più due campi:

- `canale`: `chat`, `voce` (chiamata dal browser, con la chat accanto) o `telefono` (dal numero
  vero, senza chat; si parte da ospite);
- `lingua`: quella scelta con le bandiere della pagina, `it` o `en` (al telefono sempre `it`).
  L'API risponde in quella lingua, anche negli stati; i documenti sono in italiano, quindi le
  citazioni restano come sono.

```http
POST /turno
Authorization: Bearer <token>          (solo se l'utente ha fatto il login)
Content-Type: application/json

{"sessione": "…", "messaggio": "Cos'è la franchigia?", "canale": "voce", "lingua": "it"}
```

La risposta è un flusso Server-Sent Events: uno `stato` per ogni nodo del grafo, poi la risposta.

```
event: stato
data: {"nodo": "retrieve", "testo": "Cerco nei documenti"}

event: risposta
data: {"testo": "…", "citazioni": ["CGA Auto ed. 03/2024, art. 12, p. 18"],
       "intento": "prodotto", "confidenza": "alta", "operatore": false, "accesso": false}
```

Una citazione, come il testo della risposta, può essere un link Markdown a un documento del sito
(vedi «I documenti»): la chat lo mostra cliccabile, in una scheda nuova, e la voce ne dice solo il
testo. I link ammessi sono quelli che cominciano con `/documenti/` o con `https://`.

```json
"citazioni": ["[DIP Casa Velaria ed. 10/2026, p. 2](/documenti/casa_e_famiglia/dip_documento_informativo_precontrattuale_casa#pagina-2)"]
```

`accesso: true` vuol dire che per rispondere l'API deve sapere chi è l'utente: la chat mostra il
pulsante «Accedi», la chiamata dal browser dice di accedere dalla pagina e richiamare, e al
telefono l'assistente chiede il PIN (vedi «Il numero di telefono»). Il campo può mancare (vale
`false`). Come ci si riconosce lo decide il canale: all'API basta dire che serve.

Cosa cambia nell'API per il canale voce:

- con `canale: "voce"` la generazione deve rispondere in **2-3 frasi brevi**, senza elenchi né
  tabelle. Il canale voce comunque ne dice al massimo `VOCE_MAX_FRASI` e rimanda alla chat per il
  resto;
- la `sessione` è la stessa della chat (la pagina la tiene in `sessionStorage`), quindi voce e
  testo sono una sola conversazione;
- il token è lo stesso della chat: il server lo prende dal cookie dell'accesso quando
  la chiamata parte (nella pagina dimostrativa è il token della sessione di prova; nel sistema
  vero sarà quello di Keycloak, che l'API scambia per quello del server polizze).

## Il canale voce

Si parla all'assistente invece di scrivergli: c'è un microfono nella web chat, la domanda
detta a voce va alla **stessa API della chat** e la risposta torna letta ad alta voce. Nella chat,
intanto, compaiono la trascrizione e la risposta completa con le fonti.

Costa zero: niente servizi a pagamento. La voce si trascrive nel cloud, nei piani gratuiti: dal
sito con Whisper large-v3 su Groq, al telefono con Azure Speech, che con l'audio telefonico
capisce meglio; quando non rispondono, sul server del progetto. Tutto il resto gira sul server.

```
browser ──WebRTC (audio cifrato)──▶ VAD ──▶ chi parla ──▶ Whisper ──▶   Ponte    ──▶ Piper ──WebRTC──▶ browser
 (microfono)                       (Silero) (impronta)   (voce→testo)     │       (testo→voce)    (altoparlante)
                                                                          │
                                                       POST /turno (SSE) ▼
                                                    API dell'assistente (la stessa della web chat)
```

| Pezzo | Cosa fa | Tecnologia (licenza) |
|---|---|---|
| Trasporto | audio tra browser e server, senza servizi esterni | Pipecat `SmallWebRTCTransport` (BSD-2), aiortc (BSD-3) |
| Fine della frase | capisce quando l'utente ha smesso di parlare | Silero VAD (MIT) |
| Solo chi chiama | scarta le frasi delle altre persone nella stanza; il VAD segue il volume di chi chiama | sherpa-onnx (Apache-2.0) con CAM++ di WeSpeaker, addestrato su VoxCeleb |
| Voce → testo | trascrive in italiano o in inglese, nel cloud con la riserva sulla CPU | dal sito Whisper large-v3 su Groq, al telefono Azure Speech e poi Groq (piani gratuiti); in locale faster-whisper `small` int8 (MIT) |
| Ponte con l'API | manda il testo all'API, dice le frasi di attesa, passa la risposta | `ponte.py` |
| Testo per la voce | Markdown, importi, date, sigle e codici scritti per esteso | `parlato.py` |
| Testo → voce | voce italiana o inglese, sulla CPU | Piper (GPL-3): `it_IT-paola-medium`; `en_GB-cori-medium`, la voce di Cori Samuel dal dataset Hi-Fi TTS di NVIDIA (CC BY 4.0) |
| Numero di telefono | riceve le telefonate e passa l'audio in WebSocket | Asterisk 22 LTS (GPL-2), `voce/centralino/` |

Il codice è in `src/assistente/voce/`; fuori dal codice, in `voce/`, ci sono il centralino
(`voce/centralino/`), i modelli scaricati per le prove in locale (`voce/modelli/`) e le
registrazioni delle chiamate di prova (`voce/prove/`).

## Come si comporta al telefono

- **Saluto.** «Ciao, sono l'assistente automatico della compagnia, dimmi pure la tua domanda.»:
  chi chiama sa subito che non parla con una persona (AI Act, art. 50). Che la voce non viene
  registrata lo dice il pannello dell'assistente.
- **Attese.** Se la risposta tarda più di `VOCE_ATTESA` secondi dice una frase adatta al nodo in
  corso («Un attimo, cerco nei documenti», «… leggo i dati della tua polizza»), poi al massimo
  altre due («Ci vuole ancora qualche secondo»).
- **Risposta.** Le prime frasi, con numeri, importi, date, targhe e sigle scritti per esteso
  («€ 1.500,00» → «millecinquecento euro», «03/2024» → «marzo duemilaventiquattro», «AB123CD» →
  «a, bi, uno, due, tre, ci, di»), poi la fonte principale senza il numero di pagina. Link ed email
  non si dettano: si rimanda alla chat.
- **Interruzioni.** Se l'utente parla sopra l'assistente, l'assistente smette. Se fa una domanda
  nuova mentre la precedente è in corso, vince l'ultima.
- **Rumore.** Le trascrizioni vuote e le frasi che Whisper «inventa» sul silenzio («Sottotitoli a
  cura di QTSS», «… Amara.org») si scartano.
- **Altre voci nella stanza.** Risponde solo a chi chiama (`chi_parla.py`). La prima frase forte
  detta mentre l'assistente tace dà l'impronta della sua voce; dopo, le frasi che le somigliano
  meno di `VOCE_SOGLIA_VOCE` si scartano, e non interrompono l'assistente. Il VAD conta come voce
  solo ciò che è al massimo 15 dB sotto il volume di chi chiama: il brusio di fondo non tiene
  aperta la frase. In un'aula simulata (le telefonate registrate con sopra le voci di 36 persone
  del dataset MInDS-14: commenti nelle pause, voci sovrapposte, brusio) sono passate 49 frasi su
  50 di chi chiamava, e dopo il riferimento un solo commento di un'altra persona. Prima del
  riferimento passa tutto: un commento nei primi secondi della chiamata riceve risposta.
- **Operatore.** Quando l'API passa a un operatore lo dice a voce, e la chat mostra che l'operatore
  risponderà lì (in Chatwoot, come per la chat).
- **Linee occupate.** Oltre `VOCE_CHIAMATE_MAX` chiamate insieme, la pagina avvisa e propone la
  chat.

## Privacy

- L'audio non si salva. Per trascriverla, ogni frase va a un servizio nel cloud, molto più veloce
  del modello locale: dal sito a Whisper large-v3 su Groq; al telefono ad Azure Speech
  (Microsoft, area North Europe: l'audio resta nell'UE), poi a Groq. Se un servizio non risponde
  entro `VOCE_GROQ_ATTESA` o `VOCE_AZURE_ATTESA` secondi, o ha finito le richieste gratuite, la
  frase passa al successivo, e alla fine al server. L'audio non si può mascherare con Presidio
  prima di mandarlo fuori: per tenerlo tutto sul server basta togliere le chiavi
  (`GROQ_API_KEY` e `AZURE_SPEECH_KEY` nel file `.env`). Piper gira sempre in locale.
- Nei log ci sono i tempi e gli intenti, mai il testo detto dall'utente (solo la sua lunghezza).
  La trascrizione arriva all'API come un messaggio della chat, quindi segue le stesse regole:
  maschera, audit, Chatwoot.
- L'audio tra browser e server è cifrato (DTLS-SRTP, obbligatorio in WebRTC).
- L'impronta della voce di chi chiama si calcola sul server, resta in memoria solo per la
  chiamata e non si confronta con nessuna voce salvata: serve solo a separare chi chiama dalle
  altre persone nella stanza.

## Tempi misurati

Sul server del progetto (Oracle Ampere, 4 core Arm, 24 GB):

| Passo | Tempo |
|---|---|
| Piper, una frase di 5 s | 0,4 s |
| Whisper large-v3 su Groq, una domanda (2-4 s di parlato), rete compresa | 0,3-0,8 s |
| Azure Speech, una frase dal telefono, rete compresa | 0,7 s in media |
| Impronta della voce, 3 s di parlato | 0,1 s |
| Whisper `small`, una domanda (5 s di parlato) | 3,5 s a server scarico |
| Whisper `base`, la stessa domanda | 1,4 s (ma «se ha la scadenza», «copetura») |
| Connessione WebRTC, dal clic a «In linea» | 0,6 s |
| Dal clic al saluto | circa 2,5 s |

Sulla CPU, Whisper costa quasi uguale per una frase di 1 o di 5 secondi: lavora sempre su una
finestra di 30 s, e l'encoder è quasi tutto il tempo. Per lo stesso motivo `beam_size=5`
(predefinito) costa come `beam_size=1` e sbaglia meno.

**Con la CPU occupata da altro i tempi crescono molto.** Durante le prove, con i 4 core già al
90% per un altro programma, Whisper `small` ha impiegato 9-14 s per domanda. Sul server
dell'assistente la CPU è condivisa con OpenSearch, i tre Qwen3 0.6B e il resto: va misurato con
tutto acceso. Se è troppo lento: `VOCE_WHISPER_MODELLO=base`, o meno `VOCE_CHIAMATE_MAX`. Con
Groq la trascrizione non usa la CPU del server: il modello locale lavora solo quando Groq non
risponde.

Memoria: il server occupa 0,6 GB a riposo (Whisper `small` int8 e le due voci di Piper già caricati)
e circa 1 GB dopo una chiamata. I modelli si caricano una volta sola e servono tutte le chiamate.

## Sulla VPS: https://assicurazioni.matteorizzuto.com

Sulla VPS gira `docker-compose.vps.yml`: la copia privata (`privata`) e quella pubblica
(`pubblica`) del sito, la finta API, il tunnel e il centralino, che ripartono da soli. Gli
indirizzi della VPS e i segreti stanno nel file `.env` (`.env.example`, «La VPS del progetto»),
dove `COMPOSE_FILE=docker-compose.vps.yml` fa usare questo file a ogni `docker compose` (anche
`docker compose up -d --build` per aggiornare). La copia privata è raggiungibile solo dalla
tailnet, come gli altri siti della VPS:

- un proxy (Caddy) fa HTTPS e `tailscale_auth`, poi passa a `127.0.0.1:8002`; il nome punta
  all'indirizzo Tailscale della VPS (`IP_TAILNET`);
- l'audio non passa dal proxy: va in UDP direttamente su `IP_TAILNET`, porte `8098-8101`
  (`VOCE_INDIRIZZI` e `VOCE_PORTE_UDP`, vedi `src/assistente/voce/rete.py`). Nelle regole della tailnet quelle
  porte devono essere aperte per i dispositivi che chiamano:

  ```json
  {"action": "accept", "src": ["autogroup:member"], "proto": "udp", "dst": ["tag:server:8098-8101"]}
  ```

### La copia pubblica: https://velaria.matteorizzuto.com

Lo stesso sito, per chi non è nella tailnet: il servizio `pubblica` del compose (stessa immagine e
stessa finta API, porta `8003`), senza telefonate e senza registro delle frasi.

- La pagina arriva dal **tunnel di Cloudflare** (servizio `tunnel`, cloudflared): la connessione
  parte dalla VPS, quindi nessuna porta è aperta da internet.
- L'audio passa dal **TURN di Cloudflare** (`src/assistente/voce/turn.py`; gratuito fino a 1.000 GB al mese):
  il firewall di Oracle non lascia entrare UDP da fuori, e il browser arriva anche da reti che
  bloccano l'UDP (TURN su TLS, porta 443). Le credenziali durano due ore e il server le rinnova da
  solo. Senza chiave TURN resta lo STUN di Cloudflare, che basta solo su alcune reti.
- Perché il TURN funzioni, le chiamate usano la politica di bundle predefinita di aiortc
  (`BALANCED`) invece di quella che chiede pipecat (`MAX_BUNDLE`): con `MAX_BUNDLE` un browser che
  può passare solo dal TURN, come un telefono su rete mobile, non si collega mai (vedi
  `src/assistente/voce/rete.py`). Provato con Chrome costretto al TURN: la frase arriva e l'assistente
  risponde.
- `python3 -I strumenti/cloudflare_pubblica.py` crea (o riusa) tunnel, record DNS e chiave TURN, e ne scrive i
  segreti nel file `.env` (`CLOUDFLARE_*`). Usa il token di `~/.secrets/proxy.env`; per creare
  la chiave TURN serve un token con il permesso Account → Calls → Edit (la chiave attuale è stata
  creata con un token a parte). Poi `docker compose up -d`.
- «Accedi con Google» funziona solo se `https://velaria.matteorizzuto.com` è tra le origini
  JavaScript autorizzate del client OAuth «Sito Velaria», e finché l'app Google è «In test» entra
  solo chi è tra gli utenti di prova.

## Dal telefono

Il browser dà il microfono solo a pagine in **HTTPS** (o su `localhost`).

- **Con Tailscale** (il server è già nella tailnet, con HTTPS attivo):
  `tailscale serve --bg --https=8443 8002` pubblica la pagina su
  `https://<nome-server>.<tailnet>.ts.net:8443`, visibile solo dai dispositivi della tailnet. La
  porta 8443 e non 443, perché sulla 443 dell'IP Tailscale c'è già Caddy. L'audio passa in UDP
  sulla tailnet, senza aprire porte. Per toglierlo: `tailscale serve --https=8443 off`.
- **Da un computer**, con un tunnel SSH: `ssh -L 8002:localhost:8002 server`, poi
  <http://localhost:8002>. Il computer deve poter raggiungere il server anche in UDP (sulla stessa
  tailnet funziona).
- **Da internet**: la copia pubblica (sopra), con il tunnel e il TURN di Cloudflare.
- **Docker**: `network_mode: host` (vedi `docker-compose.vps.yml`), per lo stesso motivo delle porte
  UDP.

## Il numero di telefono

Chi non usa il sito può chiamare un numero vero, da qualsiasi telefono: lo **0733 145 0210**
(Ehiweb). Risponde lo stesso assistente, con la stessa pipeline: cambia solo il trasporto
dell'audio.

```
telefono ──▶ operatore VoIP ──SIP──▶ Asterisk ──WebSocket (PCM 16 kHz)──▶ server /telefono
                                    (centralino)                         VAD → chi parla → Whisper → Assistente → Piper
```

- **Asterisk** (`voce/centralino/`) riceve la telefonata e la passa al server con
  `Dial(WebSocket/voce/c(slin16))`: è `chan_websocket`, che esiste da Asterisk 22.6, quindi
  l'immagine compila la 22.12 (LTS); le distribuzioni hanno versioni più vecchie. Carica solo i
  moduli che servono (`modules.conf`), gira senza privilegi e in sola lettura.
- **Il server** (`telefono.py`) accetta su `/telefono` solo Asterisk, che si presenta
  con il segreto condiviso (`TELEFONO_SEGRETO`, in HTTP Basic). Ogni telefonata occupa una delle
  linee (`VOCE_CHIAMATE_MAX`, le stesse delle chiamate dal browser): se sono tutte occupate rifiuta,
  e Asterisk fa sentire il segnale di occupato.
- **Differenze dal browser.** Non c'è la chat: quello che non dice, l'assistente lo rimanda al
  sito. All'API arriva `canale: "telefono"`. Chi chiama parte da ospite (il numero di telefono non
  prova chi è) e risponde alle domande generali.
- **Accesso con il PIN.** Quando l'API risponde `accesso: true`, l'assistente aggiunge «Digita sul
  tastierino il tuo PIN telefonico, poi premi cancelletto». I tasti arrivano da Asterisk come
  eventi `DTMF_END`; l'asterisco ricomincia da capo. Con il PIN giusto dice «Grazie Mario, ti ho
  riconosciuto» e rifà la domanda che aveva chiesto l'accesso, questa volta con il token: la
  sessione (`AccessoConPin`) dura quanto la telefonata. Dopo tre PIN sbagliati rimanda al sito;
  se invece di digitare si parla, è una domanda nuova. Nei log c'è solo l'esito, mai le cifre.

Password e dati dell'operatore stanno nel file `.env` (in `.gitignore` e `.dockerignore`), che
`docker compose` passa al centralino; i file in `voce/centralino/conf/` sono modelli, e `avvio.sh` ci
mette i valori all'avvio.

### Provarlo senza numero

Il centralino accetta anche un **telefono di prova** nella tailnet: un'app SIP gratuita (per
esempio Linphone, su Android o iOS) con questo account:

| Campo | Valore |
|---|---|
| Nome utente | `prova` |
| Password | `TELEFONO_PASSWORD_PROVA` nel file `.env` |
| Dominio (server SIP) | l'indirizzo Tailscale della VPS (`IP_TAILNET`) |
| Trasporto | UDP |

Poi si compone un numero qualsiasi. Nelle regole della tailnet devono essere aperte le porte del
centralino (SIP 5060 e audio 10000-10019, UDP), come quelle dell'audio WebRTC:

```json
{"action": "accept", "src": ["autogroup:member"], "proto": "udp", "dst": ["tag:server:5060,10000-10019"]}
```

**Prova automatica**, senza telefono: Asterisk fa una telefonata finta che, dopo il saluto, dice
una domanda registrata e registra la risposta. Se c'è il file `pin`, dopo la richiesta
dell'assistente digita quelle cifre e il cancelletto, come un telefono vero.

```bash
# la domanda: PCM 16 bit, 16 kHz, mono, senza intestazione (per esempio «Le mie info»)
docker compose exec -T centralino sh -c 'cat > /run/centralino/prova/domanda.sln16' < domanda.sln16
# facoltativo: il PIN da digitare
docker compose exec -T centralino sh -c 'printf 123456 > /run/centralino/prova/pin'
docker compose exec centralino asterisk -C /run/centralino/conf/asterisk.conf \
    -rx "channel originate Local/s@assistente/n extension s@prova-automatica"
# dopo una quarantina di secondi, la risposta registrata
docker compose exec -T centralino cat /run/centralino/prova/risposta.wav > risposta.wav
```

Con «Le mie info» e il PIN, la risposta registrata è «Grazie Mario, ti ho riconosciuto.
Hai già fatto l'accesso: come posso esserti utile?».

### Collegare il numero vero

1. **Attivare un numero VoIP** con accesso SIP da un operatore italiano: per esempio EhiWeb ha
   numeri geografici a circa 2 €/mese. Servono un documento d'identità e un indirizzo: la legge
   chiede di identificare chi ha un numero.
2. **Scrivere nel file `.env`** i dati che l'operatore manda dopo l'attivazione: `OPERATORE_SERVER`
   (il server SIP), `OPERATORE_UTENTE` e `OPERATORE_PASSWORD`, e l'indirizzo pubblico del server
   in `OPERATORE_IP_PUBBLICO`. Poi `docker compose up -d centralino`.
3. **Il firewall** non va aperto. La registrazione e le chiamate in arrivo passano dal varco che
   Asterisk tiene aperto (`qualify_frequency`), senza aprire la 5062. L'audio dell'operatore
   entra perché l'assistente parla per primo (il saluto): il firewall, che tiene traccia delle
   connessioni, lascia passare la risposta dallo stesso indirizzo. Con Ehiweb (VivaVox, server
   `sip.vivavox.it`, codec G.711 A-law) anche l'audio passa da `79.98.45.133`. Per non dipendere
   dal saluto si possono aprire le porte UDP 10000-10019 solo dalle reti dell'operatore (Ehiweb:
   AS43989), nella security list di Oracle e in `iptables`.
4. **Controllare**: `docker compose exec centralino asterisk -C /run/centralino/conf/asterisk.conf
   -rx "pjsip show registrations"` deve dire `Registered`; poi si chiama il numero.

## Le altre entrate (sviluppi futuri)

- **Chiamate WhatsApp alla compagnia.** Meta non fa pagare le chiamate fatte dall'utente. Pipecat
  ha già un trasporto WhatsApp (`pipecat.transports.whatsapp`), anche lui su WebRTC. Servono però
  un account WhatsApp Business verificato, con un limite di almeno 2.000 conversazioni al giorno
  per avere le chiamate, e un numero dedicato. Chi chiama è un ospite, come al numero vero.

## I file

```
src/assistente/            il pacchetto Python
  server.py                mette insieme le parti: sito, accesso, voce; /salute
  config.py                le impostazioni, ASSISTENTE_… e VOCE_… (tutte in .env.example)
  rag/                     il collegamento con l'API dell'assistente (il RAG)
    client.py              il client dell'API (/turno, Server-Sent Events), per chat e voce
    finta.py               la finta API per le prove (finta-api)
  sito/                    il sito dimostrativo
    rotte.py               home page, documenti, pagina /a, chat scritta (/api/chat)
    pagina.py              le pagine e i messaggi della chat, fatti sul server con Jinja2
    testi.py               i testi, in italiano e in inglese
    documenti.py           i documenti da leggere nel sito, con le ancore per i link del RAG
    pagine/                i modelli Jinja2: base.html (testata e piede), pagina.html (la home
                           page), documenti.html, documento.html, messaggio.html,
                           amministrazione.html (la pagina /a)
    statico/               stile.css, assistente.js (pannello, chat e chiamata), accesso.js
                           (registrazione, accesso e polizze), amministrazione.js, logo e caratteri
  accesso/                 chi è l'utente
    utenti.py              l'anagrafe SQLite: utenti, polizze, impronte delle password
    sessioni.py            le sessioni, l'accesso con il PIN al telefono, i limiti ai tentativi
    google.py              l'accesso con Google (codice → ID token verificato)
    rotte.py               registrazione, accesso, uscita, polizze aggiunte e tolte
    amministrazione.py     la pagina /a per caricare gli utenti di prova
    esempio_utenti.json    lo stampino del JSON di /a
  voce/                    il canale voce
    canale.py              /api/config, /api/offer (WebRTC), /telefono, linee, registro
    chiamata.py            la pipeline di una chiamata (VAD → chi parla → Whisper → ponte → Piper)
    ponte.py               il ponte con l'API: turni, frasi di attesa, interruzioni, PIN
    parlato.py             dalla risposta scritta alle frasi da dire, in italiano o in inglese
    chi_parla.py           solo la voce di chi chiama: impronta della voce e VAD che la segue
    servizi.py             Whisper e Piper caricati una volta e condivisi
    remoti.py              i servizi di trascrizione nel cloud: stessa forma, si passa al successivo
    groq.py, azure.py      Whisper large-v3 su Groq (il primo dal sito), Azure Speech (al telefono)
    telefono.py            il protocollo di chan_websocket di Asterisk (audio e tasti)
    rete.py                indirizzi e porte UDP dell'audio, e la politica di bundle per il TURN
    turn.py                le credenziali del TURN di Cloudflare, per le chiamate da internet
    registro.py            il registro delle frasi
    prova.py               la chiamata di prova (prova-chiamata)
tests/                     pytest, diviso come il codice: sito/, accesso/, voce/, rag/, e il server
documenti/                 i documenti anonimizzati del gruppo, <area>/<nome>.md (nell'immagine)
documenti_drive/           il resto della cartella del Drive (zip, FAQ, script e registri
                           dell'anonimizzazione; due file hanno i nomi reali); precedente/ ha lo
                           zip di prima, con i doppioni. Solo sulla VPS, fuori da git
dati/                      sulla VPS: utenti e polizze (utenti.sqlite), condivisi dalle due copie;
                           fuori da git (con docker-compose.yml stanno nel volume «dati»)
voce/                      il canale voce fuori dal codice
  centralino/              Asterisk per il numero vero: Dockerfile, avvio.sh, conf/ (modelli)
  modelli/                 voci di Piper e impronte, scaricati per le prove in locale; fuori da git
  prove/                   le registrazioni di prova-chiamata; fuori da git
strumenti/
  cloudflare_pubblica.py   tunnel, nome e chiave TURN della copia pubblica su Cloudflare
documentazione/            la mappa dei componenti (index.html), su
                           https://doc.assicurazioni.matteorizzuto.com, e i loghi (loghi/)
                           (Caddy serve la cartella così com'è: basta modificare il file)
docker-compose.yml         per provarlo su qualsiasi macchina: sito e finta API
docker-compose.vps.yml     la VPS del progetto: copia privata e pubblica, tunnel, centralino
```

Restano fuori dal repository (`.gitignore`): il file `.env`, `dati/`, i modelli e le registrazioni
della voce, la tesi e la cartella del Drive del gruppo.
