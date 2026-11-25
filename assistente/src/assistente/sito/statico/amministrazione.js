"use strict";
// La pagina /a: la password di amministrazione, poi il JSON degli utenti di prova
// (accesso/amministrazione.py). Dopo ogni operazione riuscita la pagina si ricarica, con l'elenco nuovo.

(() => {
  const $ = (selettore) => document.querySelector(selettore);
  const T = JSON.parse($("#testi-script").textContent);
  const errore = $("#a-errore");

  function sbaglio(righe) {
    errore.replaceChildren(...[].concat(righe).map((r) => Object.assign(document.createElement("p"), { textContent: r })));
    errore.hidden = false;
  }

  async function manda(indirizzo, dati) {
    return fetch(indirizzo, {
      method: "POST",
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

  // L'esito del caricamento, dopo che la pagina si è ricaricata con l'elenco nuovo
  const esito = sessionStorage.getItem("a-esito");
  if (esito && $("#a-esito")) {
    sessionStorage.removeItem("a-esito");
    $("#a-esito").textContent = esito;
    $("#a-esito").hidden = false;
  }
})();
