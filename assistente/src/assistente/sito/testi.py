"""I testi della pagina in italiano e in inglese: ogni voce ha le due versioni affiancate.

I testi sono nostri e la pagina li mette così come sono: possono contenere <strong>, <em> e link.
I dati che arrivano da fuori (le risposte dell'API, i nomi, le polizze) passano invece dal modello
della pagina, che li protegge (pagina.py). {nome} è un valore che lo script inserisce dopo.
"""

from typing import NamedTuple


class Testo(NamedTuple):
    it: str
    en: str


TESTI: dict[str, Testo] = {
    "titolo": Testo("Velaria · Assicurazioni online", "Velaria · Online insurance"),
    "descrizione": Testo(
        "Velaria, compagnia assicurativa fittizia: sito dimostrativo con un assistente che "
        "risponde per scritto e a voce.",
        "Velaria, a fictional insurance company: a demo site with an assistant that answers in "
        "writing and by voice.",
    ),
    "salta": Testo("Vai al contenuto", "Skip to content"),
    "avviso_demo": Testo(
        "Sito dimostrativo per un progetto universitario (UniCam): Velaria è una compagnia "
        "fittizia.",
        "Demo site for a university project (UniCam): Velaria is a fictional company.",
    ),
    "logo": Testo("Velaria, pagina iniziale", "Velaria, home page"),
    "lingua": Testo("Lingua", "Language"),
    "menu": Testo("Principale", "Main"),
    "menu_prodotti": Testo("Prodotti", "Products"),
    "menu_assistente": Testo("Assistente", "Assistant"),
    "menu_sinistri": Testo("Sinistri", "Claims"),
    "menu_contatti": Testo("Contatti", "Contact"),
    "documenti": Testo("Documenti", "Documents"),
    "tutti_documenti": Testo("Tutti i documenti", "All documents"),
    "documenti_descrizione": Testo(
        "Condizioni di assicurazione, documenti informativi e moduli dei prodotti Velaria.",
        "Policy terms, information documents and forms for Velaria products (in Italian).",
    ),
    "documenti_aree": Testo("Aree dei documenti", "Document areas"),
    "faq": Testo("FAQ", "FAQ"),
    "faq_titolo": Testo("Domande frequenti", "Frequently asked questions"),
    "faq_descrizione": Testo(
        "Le risposte alle domande più frequenti su polizze, sinistri e prodotti Velaria.",
        "Answers to frequently asked questions about Velaria policies, claims and products (in "
        "Italian).",
    ),
    "faq_categorie": Testo("Categorie delle domande", "Question categories"),
    "faq_altre": Testo("Altre domande", "Other questions"),
    "briciole": Testo("Percorso", "Breadcrumb"),
    "accedi": Testo("Accedi", "Sign in"),
    "area_di": Testo("Area riservata di", "Personal area of"),
    "area": Testo("Area riservata", "Personal area"),
    "area_ciao": Testo("Ciao,", "Hi,"),
    "area_sotto": Testo(
        "Qui trovi i tuoi dati e le tue polizze.",
        "Here are your details and your policies.",
    ),
    "esci": Testo("Esci", "Sign out"),
    "dati": Testo("I tuoi dati", "Your details"),
    "dati_nome": Testo("Nome e cognome", "Full name"),
    "dati_cf": Testo("Codice fiscale", "Tax code"),
    "dati_email": Testo("Email", "Email"),
    "dati_telefono": Testo("Telefono", "Phone"),
    "dati_indirizzo": Testo("Indirizzo", "Address"),
    "dati_pin": Testo("PIN telefonico", "Phone PIN"),
    "nota_pin": Testo(
        'Quando chiami lo <a href="tel:+3907331450210">0733 145 0210</a> e l\'assistente te lo '
        "chiede, digita il PIN sul tastierino e poi cancelletto.",
        'When you call <a href="tel:+3907331450210">+39 0733 145 0210</a> and the assistant '
        "asks for it, type the PIN on the keypad, then the hash key.",
    ),
    "polizze": Testo("Le tue polizze", "Your policies"),
    "polizza_n": Testo("Polizza n.", "Policy no."),
    "polizza_attiva": Testo("Attiva", "Active"),
    "polizza_scadenza": Testo("Scadenza", "Expiry date"),
    "polizza_premio": Testo("Premio annuo", "Annual premium"),
    "polizza_garanzie": Testo("Garanzie", "Cover"),
    "aggiungi_polizza": Testo("Aggiungi una polizza", "Add a policy"),
    "togli_polizza": Testo("Togli", "Remove"),
    "nessuna_polizza": Testo("Non hai ancora polizze.", "You have no policies yet."),
    "campo_prodotto": Testo("Prodotto", "Product"),
    "campo_numero": Testo("Numero di polizza", "Policy number"),
    "campo_oggetto": Testo("Cosa assicura", "What it covers"),
    "campo_premio": Testo("Premio annuo (€)", "Annual premium (€)"),
    "campo_garanzie": Testo("Garanzie, una per riga", "Cover, one per line"),
    "salva_polizza": Testo("Aggiungi", "Add"),
    "eroe_sopra": Testo(
        "Assicurazioni online · Gruppo Altaire",
        "Online insurance · Altaire Group",
    ),
    "eroe_titolo": Testo(
        "Protezione chiara <em>a portata di voce.</em>",
        "Clear protection, <em>just a voice away.</em>",
    ),
    "eroe_intro": Testo(
        "Auto, casa, vita e previdenza. E un assistente che risponde alle tue domande per "
        "scritto o a voce: dal browser, senza app, oppure al telefono.",
        "Car, home, life and pensions. And an assistant that answers your questions in writing "
        "or by voice: in your browser, with no apps, or over the phone.",
    ),
    "scrivi_assistente": Testo("Scrivi all'assistente", "Write to the assistant"),
    "parla_assistente": Testo("Parla con l'assistente", "Talk to the assistant"),
    "chiama_etichetta": Testo("Oppure chiama l'assistente", "Or call the assistant (in Italian)"),
    "numero_assistente": Testo("0733 145 0210", "+39 0733 145 0210"),
    "punto_sinistri": Testo("Denuncia dei sinistri online, h24", "Report claims online, 24/7"),
    "punto_soccorso": Testo("Soccorso stradale h24", "24/7 roadside assistance"),
    "anteprima_nome": Testo("Assistente Velaria", "Velaria Assistant"),
    "anteprima_stato": Testo("In linea", "Online"),
    "anteprima_bot": Testo(
        "Ciao, sono l'assistente automatico della compagnia, dimmi pure la tua domanda.",
        "Hi, I'm the company's automated assistant: go ahead and ask your question.",
    ),
    "anteprima_tu": Testo("Come denuncio un sinistro?", "How do I report a claim?"),
    "anteprima_ascolto": Testo("Ti ascolto…", "Listening…"),
    "prodotti_sopra": Testo("I prodotti", "Products"),
    "prodotti_titolo": Testo("Cosa vuoi proteggere?", "What do you want to protect?"),
    "auto_titolo": Testo("Auto e veicoli", "Cars and vehicles"),
    "auto_testo": Testo(
        "La responsabilità civile è sempre compresa; il resto lo scegli tu: furto e incendio, "
        "Minikasko o Kasko, cristalli, assistenza stradale. Il contratto dura un anno e non si "
        "rinnova da solo.",
        "Third-party liability is always included; the rest is up to you: theft and fire, "
        "Minikasko or Kasko, windows, roadside assistance. The contract lasts one year and does "
        "not renew automatically.",
    ),
    "casa_titolo": Testo("Casa e famiglia", "Home and family"),
    "casa_testo": Testo(
        "Danni al fabbricato e al contenuto, furto, responsabilità civile della famiglia e "
        "pronto intervento in casa. In viaggio: spese mediche, assistenza alla persona e "
        "assistenza legale.",
        "Damage to the building and its contents, theft, family liability and emergency home "
        "repairs. When travelling: medical expenses, personal assistance and legal assistance.",
    ),
    "vita_titolo": Testo("Vita e risparmio", "Life and savings"),
    "vita_testo": Testo(
        "Un capitale ai tuoi beneficiari se ti succede qualcosa, con coperture complementari a "
        "scelta. Per il risparmio, un piano multiramo a premi ricorrenti di 10, 15 o 20 anni.",
        "A lump sum for your beneficiaries if something happens to you, with optional extra "
        "cover. For savings, a multi-line plan with regular premiums over 10, 15 or 20 years.",
    ),
    "previdenza_titolo": Testo("Previdenza", "Pensions"),
    "previdenza_testo": Testo(
        "Un piano individuale pensionistico per costruire una pensione complementare, vigilato "
        "dalla COVIP. L'importo dipende da quanto versi e dai rendimenti della gestione.",
        "An individual pension plan to build a supplementary pension, supervised by COVIP. The "
        "amount depends on how much you pay in and on the fund's returns.",
    ),
    "assistente_sopra": Testo("L'assistente", "The assistant"),
    "assistente_titolo": Testo("Chiedi come preferisci", "Ask your way"),
    "scrivi_titolo": Testo("Scrivi", "Write"),
    "scrivi_testo": Testo(
        "Fai la tua domanda nella chat, con parole tue. Mentre lavora, l'assistente ti dice cosa "
        "sta facendo.",
        "Ask your question in the chat, in your own words. While it works, the assistant tells "
        "you what it is doing.",
    ),
    "parla_titolo": Testo("Parla", "Talk"),
    "parla_testo": Testo(
        "Premi il microfono e parla: ti ascolta e ti risponde a voce. Nella chat restano la tua "
        "domanda e la risposta scritta.",
        "Press the microphone and speak: it listens and answers out loud. Your question and the "
        "written answer stay in the chat.",
    ),
    "chiama_titolo": Testo("Chiama", "Call"),
    "chiama_testo": Testo(
        'Da qualsiasi telefono, allo <a href="tel:+3907331450210">0733 145 0210</a>: risponde '
        "lo stesso assistente. Per i dati delle tue polizze ti chiede il PIN telefonico.",
        'From any phone, on <a href="tel:+3907331450210">+39 0733 145 0210</a>: the same '
        "assistant answers, in Italian. For your policy details it asks for your phone PIN.",
    ),
    "privato_titolo": Testo("In privato", "Private"),
    "privato_testo": Testo(
        "La voce non viene registrata: resta solo il testo della conversazione, con i dati "
        "personali mascherati.",
        "Your voice is not recorded: only the text of the conversation is kept, with personal "
        "data masked.",
    ),
    "privato_registra": Testo(
        "In questo periodo di prova la voce viene registrata, con il testo che ne ha capito "
        "l'assistente, per migliorare il riconoscimento.",
        "During this trial period your voice is recorded, together with what the assistant "
        "understood, to improve recognition.",
    ),
    "prova_assistente": Testo("Prova l'assistente", "Try the assistant"),
    "sinistri_sopra": Testo("Sinistri", "Claims"),
    "sinistri_titolo": Testo("Hai avuto un incidente?", "Had an accident?"),
    "passo_sicurezza": Testo(
        "<strong>Mettiti in sicurezza.</strong> Indossa il giubbotto catarifrangente prima di "
        "scendere e, se ci sono feriti, chiama la Polizia Stradale o i Carabinieri.",
        "<strong>Get to safety.</strong> Put on your high-visibility vest before getting out "
        "and, if anyone is injured, call the Traffic Police or the Carabinieri.",
    ),
    "passo_documenta": Testo(
        "<strong>Documenta.</strong> Raccogli i dati dei testimoni e fotografa i luoghi, i danni "
        "e le targhe dei veicoli.",
        "<strong>Document it.</strong> Take the witnesses' details and photograph the scene, the "
        "damage and the vehicles' number plates.",
    ),
    "passo_modulo": Testo(
        "<strong>Compila il Modulo Blu</strong> con la controparte e firmatelo entrambi: vale "
        "come denuncia del sinistro.",
        "<strong>Fill in the Blue Form</strong> with the other party and both sign it: it counts "
        "as your claim report.",
    ),
    "passo_denuncia": Testo(
        "<strong>Denuncia entro 3 giorni</strong> con l'app Velaria+, online sul sito o "
        "scrivendo a sinistri@example.com.",
        "<strong>Report it within 3 days</strong> with the Velaria+ app, online on the website "
        "or by writing to sinistri@example.com.",
    ),
    "nota_sinistri": Testo(
        "In una carrozzeria convenzionata ripari il veicolo senza anticipare denaro.",
        "At a partner body shop you can have your vehicle repaired without paying up front.",
    ),
    "assistente_telefono": Testo("Assistente al telefono", "Phone assistant"),
    "orario_assistente": Testo("h24", "24/7 · in Italian"),
    "contatti_sopra": Testo("Contatti", "Contact"),
    "contatti_titolo": Testo("Siamo qui", "We're here"),
    "clienti": Testo("Assistenza clienti", "Customer service"),
    "reclami": Testo("Reclami", "Complaints"),
    "reclami_ufficio": Testo(
        "Servizio Tutela Rischi – Unità Quality",
        "Risk Protection Service – Quality Unit",
    ),
    "reclami_risposta": Testo("Risposta entro 45 giorni", "Reply within 45 days"),
    "sede": Testo("Sede legale", "Registered office"),
    "pec": Testo("PEC pec@example.com", "Certified email (PEC) pec@example.com"),
    "piede_dati": Testo(
        "Velaria S.p.A. · Gruppo Altaire · Via Esempio, 1 – 00000 Città · Iscritta all'Albo "
        "delle imprese di assicurazione n. 0.00000 · Partita IVA 00000000000",
        "Velaria S.p.A. · Altaire Group · Via Esempio, 1 – 00000 Città · Entered in the Register "
        "of insurance companies no. 0.00000 · VAT no. 00000000000",
    ),
    "piede_avvertenza": Testo(
        "Sito dimostrativo realizzato per il progetto del corso Complex Systems Design "
        "dell'Università di Camerino. Velaria, il Gruppo Altaire, i prodotti e i recapiti sono "
        "fittizi.",
        "Demo site built for the Complex Systems Design course project at the University of "
        "Camerino. Velaria, the Altaire Group, the products and the contact details are "
        "fictional.",
    ),
    "chiudi": Testo("Chiudi", "Close"),
    "accesso_titolo": Testo("La tua area riservata", "Your personal area"),
    "accesso_sotto": Testo(
        "Le tue polizze e i tuoi dati, e un assistente che sa chi sei.",
        "Your policies and your details, and an assistant that knows who you are.",
    ),
    "accedi_google": Testo("Accedi con Google", "Sign in with Google"),
    "campo_utente": Testo("Utente", "Username"),
    "campo_password": Testo("Password", "Password"),
    "oppure": Testo("oppure", "or"),
    "registrati": Testo("Registrati", "Sign up"),
    "crea_account": Testo("Crea l'account", "Create account"),
    "campo_nome": Testo("Nome", "First name"),
    "campo_cognome": Testo("Cognome (facoltativo)", "Last name (optional)"),
    "campo_email": Testo("Email (facoltativa)", "Email (optional)"),
    "campo_utente_nuovo": Testo(
        "Utente (3-40 caratteri: lettere, cifre, . _ -)",
        "Username (3-40 characters: letters, digits, . _ -)",
    ),
    "campo_password_nuova": Testo(
        "Password (almeno 8 caratteri)", "Password (at least 8 characters)"
    ),
    "amministrazione": Testo("Amministrazione", "Administration"),
    "utenti_di_prova": Testo("Utenti di prova", "Test users"),
    "json_utenti": Testo("JSON degli utenti", "Users JSON"),
    "carica": Testo("Carica", "Upload"),
    "usa_esempio": Testo("Usa l'esempio", "Use the example"),
    "formato_json": Testo("Formato", "Format"),
    "utenti": Testo("Utenti", "Users"),
    "polizze_numero": Testo("Polizze", "Policies"),
    "solo_google": Testo("(solo Google)", "(Google only)"),
    "azioni": Testo("Azioni", "Actions"),
    "modifica": Testo("Modifica", "Edit"),
    "elimina": Testo("Elimina", "Delete"),
    "elimina_tutti": Testo("Elimina tutti", "Delete all"),
    "modifica_utente": Testo("Modifica utente", "Edit user"),
    "campo_password_vuota": Testo(
        "Nuova password (vuota: resta quella di prima)",
        "New password (empty: keep the current one)",
    ),
    "salva": Testo("Salva", "Save"),
    "nota_accesso": Testo("Dati e polizze sono di prova.", "Details and policies are sample data."),
    "assistente": Testo("Assistente", "Assistant"),
    "assistente_nome": Testo("Assistente Velaria", "Velaria Assistant"),
    "assistente_automatico": Testo("Assistente automatico", "Automated assistant"),
    "chiudi_assistente": Testo("Chiudi l'assistente", "Close the assistant"),
    "conversazione": Testo("Conversazione", "Conversation"),
    "benvenuto": Testo(
        "Ciao, sono l'assistente automatico di Velaria. Scrivimi la tua domanda, oppure premi il "
        "microfono e parlami.",
        "Hi, I'm Velaria's automated assistant. Write your question, or press the microphone and "
        "talk to me.",
    ),
    "riattacca": Testo("Riattacca", "Hang up"),
    "tua_domanda": Testo("La tua domanda", "Your question"),
    "scrivi_domanda": Testo("Scrivi una domanda…", "Write a question…"),
    "invia": Testo("Invia", "Send"),
    "assistente_nota": Testo(
        "Ti risponde un sistema automatico. La voce non viene registrata.",
        "You are talking to an automated system. Your voice is not recorded.",
    ),
    "nota_registra": Testo(
        "Ti risponde un sistema automatico. Per le prove, la voce viene registrata.",
        "You are talking to an automated system. For testing, your voice is recorded.",
    ),
    "non_risponde": Testo(
        "Il servizio non risponde: riprova tra poco.",
        "The service is not responding: please try again shortly.",
    ),
    "occupato": Testo(
        "Tutte le linee sono occupate: riprova tra poco, oppure scrivi nella chat.",
        "All lines are busy: please try again shortly, or write in the chat.",
    ),
    "operatore": Testo(
        "Ti risponderà un operatore, qui nella chat.",
        "An agent will reply to you here in the chat.",
    ),
    "fonti": Testo("Fonti", "Sources"),
    "ci_penso": Testo("Ci penso", "Thinking"),
    "permesso_microfono": Testo(
        "Chiedo il permesso del microfono…",
        "Asking for permission to use the microphone…",
    ),
    "solo_https": Testo(
        "Il microfono funziona solo in HTTPS.",
        "The microphone only works over HTTPS.",
    ),
    "collego": Testo("Collego…", "Connecting…"),
    "in_linea": Testo("In linea: parla pure", "Connected: go ahead and speak"),
    "interrotta": Testo("La chiamata si è interrotta.", "The call was interrupted."),
    "voce_non_risponde": Testo(
        "Il server della voce non risponde.",
        "The voice server is not responding.",
    ),
    "iniziata": Testo("Chiamata iniziata", "Call started"),
    "terminata": Testo("Chiamata terminata", "Call ended"),
    "permesso_negato": Testo(
        "Serve il permesso di usare il microfono.",
        "Permission to use the microphone is needed.",
    ),
    "accesso_eseguito": Testo("Accesso eseguito come {nome}.", "Signed in as {nome}."),
    "richiama": Testo(
        " Per usarlo anche al telefono, riattacca e richiama.",
        " To use it on the call too, hang up and call again.",
    ),
    "uscito": Testo(
        "Sei uscito dall'area riservata.",
        "You have signed out of your personal area.",
    ),
    "accesso_annullato": Testo("Accesso annullato.", "Sign-in cancelled."),
    "accesso_non_riuscito": Testo(
        "Accesso non riuscito: riprova.",
        "Sign-in failed: please try again.",
    ),
    "password_sbagliata": Testo("Utente o password sbagliati.", "Wrong username or password."),
    "password_errata": Testo("Password sbagliata.", "Wrong password."),
    "utente_gia_usato": Testo(
        "Questo nome utente è già usato: scegline un altro.",
        "This username is already taken: please choose another.",
    ),
    "email_gia_usata": Testo(
        "Questa email è già usata da un altro account.",
        "This email is already used by another account.",
    ),
    "registrazione_non_valida": Testo(
        "Registrazione non riuscita: controlla i campi e riprova.",
        "Sign-up failed: check the fields and try again.",
    ),
    "troppe_registrazioni": Testo(
        "Troppe registrazioni in poco tempo: riprova più tardi.",
        "Too many sign-ups in a short time: please try again later.",
    ),
    "troppi_tentativi": Testo(
        "Troppi tentativi: riprova tra qualche minuto.",
        "Too many attempts: please try again in a few minutes.",
    ),
    "polizza_non_salvata": Testo(
        "Polizza non salvata: controlla i campi e riprova.",
        "Policy not saved: check the fields and try again.",
    ),
    "conferma_togli": Testo("Togliere la polizza n. {numero}?", "Remove policy no. {numero}?"),
    "json_non_valido": Testo("JSON non valido: {errore}", "Invalid JSON: {errore}"),
    "conferma_elimina": Testo(
        "Eliminare {nome} e le sue polizze?", "Delete {nome} and their policies?"
    ),
    "conferma_elimina_tutti": Testo(
        "Eliminare tutti gli utenti ({quanti}), con le loro polizze? Non si può annullare.",
        "Delete all users ({quanti}) and their policies? This cannot be undone.",
    ),
    "utenti_caricati": Testo(
        "Fatto. Utenti creati: {creati}; sostituiti: {sostituiti}.",
        "Done. Users created: {creati}; replaced: {sostituiti}.",
    ),
    "google_non_risponde": Testo(
        "Google non risponde: riprova tra poco.",
        "Google is not responding: please try again shortly.",
    ),
    "google_non_configurato": Testo(
        "L'accesso con Google non è configurato.",
        "Sign-in with Google is not configured.",
    ),
    "popup_bloccato": Testo(
        "Il browser ha bloccato la finestra di Google: consentila e riprova.",
        "Your browser blocked the Google window: allow it and try again.",
    ),
}

# I testi che servono agli script della pagina: chiamata, accesso, errori di rete
DEGLI_SCRIPT = (
    "non_risponde",
    "occupato",
    "riattacca",
    "parla_assistente",
    "permesso_microfono",
    "solo_https",
    "collego",
    "in_linea",
    "interrotta",
    "voce_non_risponde",
    "iniziata",
    "terminata",
    "permesso_negato",
    "accesso_eseguito",
    "richiama",
    "uscito",
    "accesso_annullato",
    "accesso_non_riuscito",
    "google_non_risponde",
    "google_non_configurato",
    "popup_bloccato",
    "password_sbagliata",
    "password_errata",
    "utente_gia_usato",
    "email_gia_usata",
    "registrazione_non_valida",
    "troppe_registrazioni",
    "troppi_tentativi",
    "polizza_non_salvata",
    "conferma_togli",
    "json_non_valido",
    "utenti_caricati",
    "conferma_elimina",
    "conferma_elimina_tutti",
)
