"use strict";
// La registrazione, l'accesso e le polizze di chi è entrato.
// Nella finestra ci sono due schede: «Registrati» crea un account (api/registrazione) ed entra
// subito; «Accedi» entra con utente e password (api/accesso/password). Oppure Google: il
// pulsante «Accedi con Google» apre una finestra di Google (Google Identity Services, modello
// «codice»); alla fine Google dà alla pagina un codice monouso, che va al server (api/accesso):
// è il server a scambiarlo con Google e a verificare chi è entrato. La sessione sta in un cookie HttpOnly, che
// la pagina non vede.
// L'area riservata la fa il server (pagina.py). Dopo l'accesso, dopo l'uscita e dopo ogni polizza
// aggiunta o tolta la pagina ne riprende dal server solo le parti che cambiano: chat e chiamata
// restano come sono.
// Ogni elemento con data-accedi apre la finestra (anche il pulsante che l'assistente mette nella
// chat). Quando l'utente entra o esce, la pagina riceve gli eventi «velaria:accesso» e
// «velaria:uscita».

(() => {
  const $ = (selettore) => document.querySelector(selettore);
  const T = JSON.parse($("#testi-script").textContent);
  const finestra = $("#finestra-accesso");
  const pulsanteGoogle = $("#pulsante-google");
  const errore = $("#errore-accesso");
  const finestraPolizza = $("#finestra-polizza");
  const moduloPolizza = $("#modulo-polizza");
  const errorePolizza = $("#errore-polizza");
  // Le parti della pagina che dipendono dall'accesso
  const PARTI = ["area", "pulsante-accedi", "pulsante-area"];

  async function aggiorna() {
    const pagina = new DOMParser().parseFromString(await (await fetch("./")).text(), "text/html");
    for (const id of PARTI) document.getElementById(id).replaceWith(pagina.getElementById(id));
  }

  function sbaglio(messaggio, dove = errore) {
    dove.textContent = messaggio;
    dove.hidden = false;
  }

  async function entrato(risposta) {
    const utente = await risposta.json();
    await aggiorna();
    finestra.close();
    $("#area").scrollIntoView({ behavior: "smooth", block: "start" });
    document.dispatchEvent(new CustomEvent("velaria:accesso", { detail: utente }));
  }

  // Le schede «Accedi» e «Registrati»
  function scheda(id) {
    errore.hidden = true;
    for (const pulsante of finestra.querySelectorAll("[data-scheda]")) {
      const scelta = pulsante.dataset.scheda === id;
      pulsante.setAttribute("aria-selected", String(scelta));
      $("#" + pulsante.dataset.scheda).hidden = !scelta;
    }
  }
  for (const pulsante of finestra.querySelectorAll("[data-scheda]")) {
    pulsante.addEventListener("click", () => scheda(pulsante.dataset.scheda));
  }

  // Un account nuovo: il server lo crea e apre già la sessione
  $("#modulo-registrazione").addEventListener("submit", async (e) => {
    e.preventDefault();
    errore.hidden = true;
    const dati = Object.fromEntries(new FormData(e.target));
    try {
      const risposta = await fetch("api/registrazione", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dati),
      });
      if (risposta.status === 409) {
        const { detail } = await risposta.json();
        throw new Error(detail.campo === "email" ? T.email_gia_usata : T.utente_gia_usato);
      }
      if (risposta.status === 429) throw new Error(T.troppe_registrazioni);
      if (!risposta.ok) throw new Error(T.registrazione_non_valida);
      e.target.reset();
      await entrato(risposta);
    } catch (err) {
      sbaglio(err.message);
    }
  });

  // Utente e password
  $("#modulo-password").addEventListener("submit", async (e) => {
    e.preventDefault();
    errore.hidden = true;
    const dati = Object.fromEntries(new FormData(e.target));
    try {
      const risposta = await fetch("api/accesso/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dati),
      });
      if (risposta.status === 401) throw new Error(T.password_sbagliata);
      if (risposta.status === 429) throw new Error(T.troppi_tentativi);
      if (!risposta.ok) throw new Error(T.accesso_non_riuscito);
      e.target.reset();
      await entrato(risposta);
    } catch (err) {
      sbaglio(err.message);
    }
  });

  // La finestra di Google ha finito: con il codice il server verifica l'utente e apre la sessione
  async function entraConGoogle({ code, error }) {
    errore.hidden = true;
    try {
      if (!code) throw new Error(error === "access_denied" ? T.accesso_annullato : T.accesso_non_riuscito);
      const risposta = await fetch("api/accesso", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codice: code }),
      });
      if (!risposta.ok) {
        throw new Error(risposta.status === 503 ? T.google_non_configurato : T.accesso_non_riuscito);
      }
      await entrato(risposta);
    } catch (err) {
      sbaglio(err.message);
    }
  }

  async function esci() {
    await fetch("api/uscita", { method: "POST" }).catch(() => {});
    await aggiorna();
    $("#pulsante-accedi").focus();
    document.dispatchEvent(new CustomEvent("velaria:uscita"));
  }

  function caricaScript(indirizzo) {
    return new Promise((fatto, fallito) => {
      const script = document.createElement("script");
      script.src = indirizzo;
      script.onload = fatto;
      script.onerror = () => fallito(new Error(T.google_non_risponde));
      document.head.append(script);
    });
  }

  // Il client di Google si prepara la prima volta che si apre la finestra: fino ad allora la
  // pagina non carica niente da Google
  let clientGoogle = null;
  let preparazione = null;

  async function preparaGoogle() {
    const clientId = pulsanteGoogle.dataset.client;
    await caricaScript("https://accounts.google.com/gsi/client");
    clientGoogle = google.accounts.oauth2.initCodeClient({
      client_id: clientId,
      scope: "openid email profile",
      ux_mode: "popup",
      callback: entraConGoogle,
      // La finestra non si è aperta (popup bloccato) o è stata chiusa prima della fine
      error_callback: ({ type }) => {
        if (type === "popup_failed_to_open") sbaglio(T.popup_bloccato);
      },
    });
    pulsanteGoogle.disabled = false;
  }

  function apri() {
    scheda("modulo-password");
    finestra.showModal();
    // Senza client ID il pulsante di Google non c'è: si entra solo con utente e password
    if (!pulsanteGoogle) return;
    preparazione ??= preparaGoogle().catch((err) => {
      preparazione = null; // alla prossima apertura si riprova
      sbaglio(err.message);
    });
  }

  pulsanteGoogle?.addEventListener("click", () => {
    errore.hidden = true;
    clientGoogle.requestCode();
  });

  // Una polizza nuova: la salva il server, poi si riprende l'area
  moduloPolizza.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorePolizza.hidden = true;
    const dati = Object.fromEntries(new FormData(moduloPolizza));
    dati.garanzie = dati.garanzie.split("\n").map((g) => g.trim()).filter(Boolean);
    try {
      const risposta = await fetch("api/polizze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dati),
      });
      if (!risposta.ok) throw new Error(T.polizza_non_salvata);
      await aggiorna();
      finestraPolizza.close();
    } catch (err) {
      sbaglio(err.message, errorePolizza);
    }
  });

  async function togli(pulsante) {
    if (!confirm(T.conferma_togli.replace("{numero}", pulsante.dataset.numero))) return;
    await fetch(`api/polizze/${pulsante.dataset.togliPolizza}`, { method: "DELETE" }).catch(() => {});
    await aggiorna();
  }

  // Chiusura delle finestre: il pulsante con la croce, o un clic fuori (sullo sfondo)
  for (const f of [finestra, finestraPolizza]) {
    f.addEventListener("click", (e) => {
      if (e.target === f || e.target.closest("[data-chiudi-finestra]")) f.close();
    });
  }

  // Anche gli elementi che arrivano dopo: il pulsante nella chat, l'area riservata
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-accedi]")) apri();
    else if (e.target.closest("#esci")) esci();
    else if (e.target.closest("[data-nuova-polizza]")) {
      moduloPolizza.reset();
      errorePolizza.hidden = true;
      finestraPolizza.showModal();
    } else if (e.target.closest("[data-togli-polizza]")) togli(e.target.closest("[data-togli-polizza]"));
  });
})();
