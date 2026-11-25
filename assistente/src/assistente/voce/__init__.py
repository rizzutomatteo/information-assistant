"""Il canale voce: le chiamate dal sito (WebRTC) e le telefonate dal numero vero (Asterisk).

canale.py     gli endpoint (/api/config, /api/offer, /telefono), le linee, il registro
chiamata.py   la pipeline di una chiamata (VAD → chi parla → Whisper → ponte → Piper)
ponte.py      il ponte con l'API dell'assistente: turni, frasi di attesa, interruzioni, PIN
parlato.py    dalla risposta scritta alle frasi da dire, in italiano o in inglese
chi_parla.py  solo la voce di chi chiama: impronta della voce e VAD che segue il suo volume
servizi.py    Whisper e Piper caricati una volta e condivisi
remoti.py     i servizi di trascrizione nel cloud: groq.py (dal sito), azure.py (al telefono)
telefono.py   il protocollo di chan_websocket di Asterisk (audio e tasti)
rete.py       indirizzi e porte UDP dell'audio, e la politica di bundle che fa andare il TURN
turn.py       le credenziali del TURN di Cloudflare, per le chiamate da internet
registro.py   il registro delle frasi per le prove
prova.py      la chiamata di prova (prova-chiamata)
"""
