"use strict";
// L'assistente della pagina, in due modi che finiscono nello stesso pannello:
//   - scritto: POST api/chat, la risposta arriva come Server-Sent Events (la domanda, gli stati,
//     poi la risposta);
//   - a voce: una chiamata WebRTC al server della voce (api/config, api/offer); trascrizione,
//     stati e risposta arrivano sul canale dati.
// I messaggi li fa il server (pagina.py), nella lingua della pagina: ogni evento porta «html», da
// aggiungere alla conversazione, e «attesa», la riga sotto. Qui si mettono nella pagina così come
// sono. I testi dello script sono nella pagina, in #testi-script.

(() => {
  const $ = (selettore) => document.querySelector(selettore);
  const T = JSON.parse($("#testi-script").textContent);
  const lingua = document.documentElement.lang;
  const pannello = $("#assistente");
  const lanciatore = $("#lanciatore");
  const messaggi = $("#messaggi");
  const statoEl = $("#assistente-stato");
  const modulo = $("#scrivi");
  const campo = $("#domanda");
  const invia = $("#invia");
  const barraChiamata = $("#chiamata");
  const statoChiamata = $("#chiamata-stato");
  const audio = $("#audio");
  const pulsantiVoce = document.querySelectorAll("[data-chiama]");
  const bandiere = document.querySelectorAll(".lingua");

  // Lo stesso identificativo per chat e voce: per l'API sono una conversazione sola
  const sessione = (() => {
    try {
      let id = sessionStorage.getItem("sessione-assistente");
      if (!id) {
        id = crypto.randomUUID();
        sessionStorage.setItem("sessione-assistente", id);
      }
      return id;
    } catch {
      return crypto.randomUUID();
    }
  })();

  // --- Pannello -----------------------------------------------------------------------

  function apri() {
    pannello.hidden = false;
    lanciatore.setAttribute("aria-expanded", "true");
    campo.focus();
  }

  function chiudi() {
    pannello.hidden = true;
    lanciatore.setAttribute("aria-expanded", "false");
    lanciatore.focus();
  }

  lanciatore.addEventListener("click", () => (pannello.hidden ? apri() : chiudi()));
  pannello.querySelector("[data-chiudi]").addEventListener("click", chiudi);
  pannello.addEventListener("keydown", (e) => { if (e.key === "Escape") chiudi(); });
  document.querySelectorAll("[data-apri-assistente]").forEach((b) => b.addEventListener("click", apri));

  // --- Messaggi -----------------------------------------------------------------------

  function scorri() {
    messaggi.scrollTop = messaggi.scrollHeight;
  }

  function stato(testo) {
    statoEl.textContent = testo || "";
    statoEl.hidden = !testo;
  }

  // Un evento della chat o della chiamata, con i campi che il server aggiunge per la pagina
  function mostra({ html, attesa }) {
    if (html) {
      messaggi.insertAdjacentHTML("beforeend", html);
      scorri();
    }
    if (attesa !== undefined) stato(attesa);
  }

  // I messaggi di questo script (la chiamata, l'accesso, la rete): solo testo
  function avviso(testo, classe = "avviso") {
    const div = document.createElement("div");
    div.className = `messaggio ${classe}`;
    div.append(Object.assign(document.createElement("p"), { textContent: testo }));
    messaggi.append(div);
    scorri();
  }

  // --- Chat scritta -------------------------------------------------------------------

  // Legge un flusso Server-Sent Events: un evento per ogni blocco separato da una riga vuota
  async function* eventi(corpo) {
    const lettore = corpo.pipeThrough(new TextDecoderStream()).getReader();
    let resto = "";
    for (;;) {
      const { value, done } = await lettore.read();
      if (done) return;
      resto += value.replace(/\r\n/g, "\n");
      const blocchi = resto.split("\n\n");
      resto = blocchi.pop();
      for (const blocco of blocchi) {
        const dati = blocco.split("\n").filter((r) => r.startsWith("data:")).map((r) => r.slice(5).replace(/^ /, ""));
        if (dati.length) yield JSON.parse(dati.join("\n"));
      }
    }
  }

  let inAttesa = false;

  async function chiedi(testo) {
    inAttesa = true;
    invia.disabled = true;
    let arrivati = 0;
    try {
      const risposta = await fetch("api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ messaggio: testo, sessione, lingua }),
      });
      if (!risposta.ok || !risposta.body) throw new Error(`HTTP ${risposta.status}`);
      for await (const dati of eventi(risposta.body)) {
        arrivati += 1;
        mostra(dati);
      }
    } catch {
      // La domanda non è arrivata al server: torna nel campo, per riprovare
      if (!arrivati && !campo.value) campo.value = testo;
      avviso(T.non_risponde, "errore");
    } finally {
      inAttesa = false;
      invia.disabled = false;
      stato("");
    }
  }

  function adattaAltezza() {
    campo.style.height = "auto";
    campo.style.height = `${campo.scrollHeight}px`;
  }

  modulo.addEventListener("submit", (e) => {
    e.preventDefault();
    const testo = campo.value.trim();
    if (!testo || inAttesa) return;
    campo.value = "";
    adattaAltezza();
    chiedi(testo);
  });
  campo.addEventListener("input", adattaAltezza);
  // Invio manda, Maiuscolo+Invio va a capo
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      modulo.requestSubmit();
    }
  });

  // --- Chiamata a voce ----------------------------------------------------------------

  const pulsanteRiattacca = pannello.querySelector("[data-riattacca]");
  // La chiamata in corso: { pc, microfono, contesto, livelloTu, livelloAssistente, animazione }
  let chiamata = null;
  let inCollegamento = false;

  function attesaCandidati(pc, massimo) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((fatto) => {
      pc.addEventListener("icegatheringstatechange", () => {
        if (pc.iceGatheringState === "complete") fatto();
      });
      setTimeout(fatto, massimo);
    });
  }

  // Il volume di un flusso audio, da 0 a circa 1, per far muovere le onde
  function misuratore(contesto, flusso) {
    const analisi = contesto.createAnalyser();
    analisi.fftSize = 512;
    contesto.createMediaStreamSource(flusso).connect(analisi);
    const campioni = new Uint8Array(analisi.fftSize);
    return () => {
      analisi.getByteTimeDomainData(campioni);
      let somma = 0;
      for (const v of campioni) somma += ((v - 128) / 128) ** 2;
      return Math.sqrt(somma / campioni.length);
    };
  }

  function animaOnde() {
    if (!chiamata) return;
    const tu = chiamata.livelloTu();
    const assistente = chiamata.livelloAssistente ? chiamata.livelloAssistente() : 0;
    barraChiamata.style.setProperty("--livello", Math.min(1, Math.max(tu, assistente) * 5).toFixed(2));
    barraChiamata.classList.toggle("parla-assistente", assistente > tu && assistente > 0.02);
    chiamata.animazione = requestAnimationFrame(animaOnde);
  }

  function mostraChiamata(attiva) {
    barraChiamata.hidden = !attiva;
    document.body.classList.toggle("in-chiamata", attiva);
    pulsantiVoce.forEach((b) => {
      b.setAttribute("aria-pressed", String(attiva));
      b.setAttribute("aria-label", attiva ? T.riattacca : T.parla_assistente);
    });
    // Cambiare lingua ricarica la pagina, e la chiamata cadrebbe
    bandiere.forEach((b) => { b.disabled = attiva; });
  }

  async function chiama() {
    chiamata = {};
    mostraChiamata(true);
    statoChiamata.textContent = T.permesso_microfono;
    if (!window.isSecureContext) throw new Error(T.solo_https);
    chiamata.microfono = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    chiamata.contesto = new AudioContext();
    chiamata.livelloTu = misuratore(chiamata.contesto, chiamata.microfono);

    statoChiamata.textContent = T.collego;
    const { ice } = await (await fetch("api/config")).json();
    const pc = new RTCPeerConnection({ iceServers: ice || [] });
    chiamata.pc = pc;

    const canale = pc.createDataChannel("messaggi");
    canale.onmessage = (e) => {
      try {
        mostra(JSON.parse(e.data));
      } catch { /* un messaggio non per la chat */ }
    };
    pc.addTransceiver(chiamata.microfono.getAudioTracks()[0], { direction: "sendrecv" });
    pc.ontrack = (e) => {
      const flusso = e.streams[0] || new MediaStream([e.track]);
      audio.srcObject = flusso;
      audio.play().catch(() => {});
      if (chiamata) chiamata.livelloAssistente = misuratore(chiamata.contesto, flusso);
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") statoChiamata.textContent = T.in_linea;
      if (["failed", "closed"].includes(pc.connectionState)) riattacca(T.interrotta);
    };

    await pc.setLocalDescription(await pc.createOffer());
    await attesaCandidati(pc, 2500);
    const risposta = await fetch("api/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
        // La chiamata resta nella lingua in cui è partita
        request_data: { sessione, lingua },
      }),
    });
    if (!risposta.ok) throw new Error(risposta.status === 503 ? T.occupato : T.voce_non_risponde);
    const { sdp, type } = await risposta.json();
    await pc.setRemoteDescription({ sdp, type });
    avviso(T.iniziata);
    animaOnde();
  }

  // Chiude tutto ciò che la chiamata ha aperto, anche se si è fermata a metà collegamento
  function riattacca(motivo) {
    if (chiamata) {
      const { pc, microfono, contesto, animazione } = chiamata;
      chiamata = null;
      if (pc) {
        pc.onconnectionstatechange = null;
        pc.close();
      }
      if (microfono) microfono.getTracks().forEach((t) => t.stop());
      if (animazione) cancelAnimationFrame(animazione);
      if (contesto) contesto.close();
    }
    audio.srcObject = null;
    mostraChiamata(false);
    stato("");
    avviso(motivo || T.terminata, motivo ? "errore" : "avviso");
  }

  pulsantiVoce.forEach((b) => b.addEventListener("click", async () => {
    apri();
    if (inCollegamento) return;
    if (chiamata) return riattacca();
    // Mentre si collega non si riattacca: si aspetta che il collegamento riesca o fallisca
    inCollegamento = pulsanteRiattacca.disabled = true;
    try {
      await chiama();
    } catch (e) {
      riattacca(e.name === "NotAllowedError" ? T.permesso_negato : e.message);
    } finally {
      inCollegamento = pulsanteRiattacca.disabled = false;
    }
  }));
  pulsanteRiattacca.addEventListener("click", () => riattacca());

  // --- Accesso ------------------------------------------------------------------------

  // Una chiamata già in corso resta da ospite: il server legge l'accesso quando la chiamata parte
  document.addEventListener("velaria:accesso", (e) => {
    avviso(T.accesso_eseguito.replace("{nome}", e.detail.nome) + (chiamata ? T.richiama : ""));
  });
  document.addEventListener("velaria:uscita", () => avviso(T.uscito));

  // --- Lingua -------------------------------------------------------------------------

  // Una bandiera ricarica la pagina nell'altra lingua: la conversazione (senza il benvenuto, che
  // il server rifà nella lingua nuova) e il pannello aperto passano alla pagina nuova
  const CONVERSAZIONE = "conversazione-assistente";

  $(".lingue").addEventListener("submit", () => {
    const html = [...messaggi.children].slice(1).map((m) => m.outerHTML).join("");
    try {
      sessionStorage.setItem(CONVERSAZIONE, JSON.stringify({ html, aperto: !pannello.hidden }));
    } catch { /* senza memoria del browser la conversazione riparte da capo */ }
  });

  try {
    const salvata = JSON.parse(sessionStorage.getItem(CONVERSAZIONE));
    sessionStorage.removeItem(CONVERSAZIONE);
    if (salvata) {
      messaggi.insertAdjacentHTML("beforeend", salvata.html);
      if (salvata.aperto) apri();
      scorri();
    }
  } catch { /* come sopra */ }
})();
