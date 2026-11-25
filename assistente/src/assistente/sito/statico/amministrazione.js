"use strict";
// La pagina /a: la password di amministrazione, poi il JSON degli utenti di prova, e per ogni
// utente «Modifica» ed «Elimina» (accesso/amministrazione.py). Dopo ogni operazione la pagina si
// ricarica, con l'elenco nuovo.

(() => {
  const $ = (selettore) => document.querySelector(selettore);
  const T = JSON.parse($("#testi-script").textContent);
  const errore = $("#a-errore");
  // I campi dell'utente nella finestra «Modifica», come nel JSON (la password a parte)
  const CAMPI = ["utente", "nome", "cognome", "email", "pin_telefono", "codice_fiscale", "telefono", "indirizzo"];

  function sbaglio(righe, dove = errore) {
    dove.replaceChildren(...[].concat(righe).map((r) => Object.assign(document.createElement("p"), { textContent: r })));
    dove.hidden = false;
  }

  async function manda(indirizzo, dati, metodo = "POST") {
    return fetch(indirizzo, {
      method: metodo,
      headers: { "Content-Type": "application/json" },
      body: dati === undefined ? undefined : JSON.stringify(dati),
    });
  }

  // Gli errori di FastAPI: per il 422 l'elenco dei campi sbagliati («utenti.0.polizze.1.scadenza»)
  async function errori(risposta) {
    const { detail } = await risposta.json().catch(() => ({}));
    if (Array.isArray(detail)) return detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`);
    return detail || T.accesso_non_riuscito;
  }

  $("#a-accesso")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    errore.hidden = true;
    const risposta = await manda("api/a/accesso", Object.fromEntries(new FormData(e.target)));
    if (risposta.ok) location.reload();
    else sbaglio(risposta.status === 429 ? T.troppi_tentativi : T.password_errata);
  });

  $("#a-utenti")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    errore.hidden = true;
    $("#a-esito").hidden = true;
    let dati;
    try {
      dati = JSON.parse(e.target.json.value);
    } catch (err) {
      sbaglio(T.json_non_valido.replace("{errore}", err.message));
      return;
    }
    const risposta = await manda("api/a/utenti", dati);
    if (!risposta.ok) {
      sbaglio(await errori(risposta));
      return;
    }
    const { creati, sostituiti } = await risposta.json();
    sessionStorage.setItem("a-esito", T.utenti_caricati.replace("{creati}", creati).replace("{sostituiti}", sostituiti));
    location.reload();
  });

  $("#a-usa-esempio")?.addEventListener("click", () => {
    $("#a-utenti").json.value = $("#a-esempio").textContent;
  });

  $("#a-esci")?.addEventListener("click", async () => {
    await manda("api/a/uscita").catch(() => {});
    location.reload();
  });

  // --- Modifica ed eliminazione ------------------------------------------------------------

  const finestra = $("#a-finestra");
  const modulo = $("#a-modifica");
  const polizze = $("#a-polizze");
  const erroreModifica = $("#a-errore-modifica");
  const utenti = JSON.parse($("#a-dati")?.textContent || "{}");
  let daModificare = null;

  function aggiungiPolizza(polizza = {}) {
    const riquadro = $("#a-polizza").content.firstElementChild.cloneNode(true);
    polizze.append(riquadro);
    for (const [nome, valore] of Object.entries(polizza)) {
      riquadro.elements[nome].value = nome === "garanzie" ? valore.join("\n") : valore;
    }
    return riquadro;
  }

  function apriModifica(id) {
    const utente = utenti[id];
    daModificare = id;
    modulo.reset();
    for (const nome of CAMPI) modulo.elements[nome].value = utente[nome];
    polizze.replaceChildren();
    utente.polizze.forEach((p) => aggiungiPolizza(p));
    erroreModifica.hidden = true;
    finestra.showModal();
  }

  // Le polizze si leggono riquadro per riquadro: i campi hanno gli stessi nomi in ognuno
  function datiDelModulo() {
    const dati = Object.fromEntries(CAMPI.map((nome) => [nome, modulo.elements[nome].value]));
    if (modulo.elements.password.value) dati.password = modulo.elements.password.value;
    dati.polizze = [...polizze.children].map((riquadro) => {
      const polizza = Object.fromEntries([...riquadro.elements].filter((c) => c.name).map((c) => [c.name, c.value]));
      polizza.garanzie = polizza.garanzie.split("\n").map((g) => g.trim()).filter(Boolean);
      return polizza;
    });
    return dati;
  }

  modulo?.addEventListener("submit", async (e) => {
    e.preventDefault();
    erroreModifica.hidden = true;
    const risposta = await manda(`api/a/utenti/${daModificare}`, datiDelModulo(), "PUT");
    if (risposta.ok) location.reload();
    else sbaglio(await errori(risposta), erroreModifica);
  });

  $("#a-nuova-polizza")?.addEventListener("click", () => {
    aggiungiPolizza().scrollIntoView({ block: "nearest" });
  });

  polizze?.addEventListener("click", (e) => {
    e.target.closest("[data-togli-polizza]")?.closest(".a-polizza").remove();
  });

  // Solo la croce (o Esc) chiude: un clic fuori per sbaglio farebbe perdere le modifiche
  finestra?.addEventListener("click", (e) => {
    if (e.target.closest("[data-chiudi-finestra]")) finestra.close();
  });

  // Se qualcosa va storto (sessione scaduta, utente già eliminato dall'altra copia del sito),
  // la pagina ricaricata mostra com'è adesso
  async function elimina(indirizzo, conferma) {
    if (!confirm(conferma)) return;
    await fetch(indirizzo, { method: "DELETE" }).catch(() => {});
    location.reload();
  }

  document.addEventListener("click", (e) => {
    const modifica = e.target.closest("[data-modifica]");
    const uno = e.target.closest("[data-elimina]");
    const tutti = e.target.closest("#a-elimina-tutti");
    if (modifica) apriModifica(modifica.dataset.modifica);
    else if (uno) elimina(`api/a/utenti/${uno.dataset.elimina}`, T.conferma_elimina.replace("{nome}", uno.dataset.nome));
    else if (tutti) elimina("api/a/utenti", T.conferma_elimina_tutti.replace("{quanti}", tutti.dataset.quanti));
  });

  // L'esito del caricamento, dopo che la pagina si è ricaricata con l'elenco nuovo
  const esito = sessionStorage.getItem("a-esito");
  if (esito && $("#a-esito")) {
    sessionStorage.removeItem("a-esito");
    $("#a-esito").textContent = esito;
    $("#a-esito").hidden = false;
  }
})();
