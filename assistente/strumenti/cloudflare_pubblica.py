#!/usr/bin/env python3
"""Mette su internet la copia pubblica del sito (servizio «pubblica» del compose). Si può rilanciare: riusa ciò che c'è.

Su Cloudflare: il tunnel «assicurazioni» con la strada verso 127.0.0.1:8003, il record DNS del nome (CNAME verso il
tunnel, con il proxy di Cloudflare) e la chiave del TURN per l'audio. Il token del tunnel e la chiave TURN vanno nel
file .env (CLOUDFLARE_*), che il compose passa ai servizi; nulla si stampa.
L'account, la zona e il nome del sito stanno nel file .env (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_ZONA, CLOUDFLARE_NOME).
Il token API è CLOUDFLARE_API_TOKEN nell'ambiente o, se manca, CF_API_TOKEN in ~/.secrets/proxy.env (quello del
proxy della VPS). Per la chiave TURN gli serve anche il permesso Account → Calls → Edit: senza, il resto si fa lo
stesso e l'audio usa solo lo STUN.

Uso: python3 -I strumenti/cloudflare_pubblica.py, poi docker compose up -d
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TUNNEL = "assicurazioni"
SERVIZIO = "http://127.0.0.1:8003"
API = "https://api.cloudflare.com/client/v4"
# Il file .env del progetto, una cartella sopra questa
ENV = Path(__file__).resolve().parents[1] / ".env"


def _dal_file(file: Path) -> dict[str, str]:
    righe = file.read_text().splitlines() if file.exists() else []
    return {k.strip(): v.strip() for k, _, v in (r.partition("=") for r in righe) if v and not k.startswith("#")}


_progetto = _dal_file(ENV)
try:
    ACCOUNT = _progetto["CLOUDFLARE_ACCOUNT_ID"]
    ZONA = _progetto["CLOUDFLARE_ZONA"]
    NOME = _progetto["CLOUDFLARE_NOME"]
except KeyError as manca:
    sys.exit(f"Manca {manca} nel file .env (vedi .env.example)")
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN") or _dal_file(Path.home() / ".secrets/proxy.env").get("CF_API_TOKEN")
if not TOKEN:
    sys.exit("Manca il token API di Cloudflare (CLOUDFLARE_API_TOKEN)")


class ErroreApi(Exception):
    def __init__(self, metodo, percorso, errori):
        super().__init__(f"{metodo} {percorso}: {errori}")
        self.codici = {e.get("code") for e in errori or []}


def api(metodo, percorso, corpo=None):
    richiesta = urllib.request.Request(
        API + percorso, method=metodo, data=None if corpo is None else json.dumps(corpo).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta) as r:
            risposta = json.load(r)
    except urllib.error.HTTPError as e:
        risposta = json.load(e)
    if not risposta.get("success"):
        raise ErroreApi(metodo, percorso, risposta.get("errors"))
    return risposta["result"]


def leggi_env() -> dict[str, str]:
    return dict(r.split("=", 1) for r in ENV.read_text().splitlines() if "=" in r and not r.startswith("#"))


def salva_env(valori: dict[str, str]):
    """Sostituisce le righe di queste variabili nel file .env, o le aggiunge in fondo."""
    righe = ENV.read_text().splitlines()
    for chiave, valore in valori.items():
        nuova = f"{chiave}={valore}"
        posto = [i for i, r in enumerate(righe) if r.startswith(f"{chiave}=")]
        if posto:
            righe[posto[0]] = nuova
        else:
            if not any(r.startswith("CLOUDFLARE_") for r in righe):
                righe += ["", "# La copia pubblica del sito (cloudflare_pubblica.py): tunnel e TURN di Cloudflare"]
            righe.append(nuova)
    ENV.write_text("\n".join(righe) + "\n")


def tunnel() -> str:
    trovati = api("GET", f"/accounts/{ACCOUNT}/cfd_tunnel?name={TUNNEL}&is_deleted=false")
    if trovati:
        t = trovati[0]
        print("tunnel: già presente")
    else:
        t = api("POST", f"/accounts/{ACCOUNT}/cfd_tunnel", {"name": TUNNEL, "config_src": "cloudflare"})
        print("tunnel: creato")
    salva_env({"CLOUDFLARE_TUNNEL_TOKEN": api("GET", f"/accounts/{ACCOUNT}/cfd_tunnel/{t['id']}/token")})
    api("PUT", f"/accounts/{ACCOUNT}/cfd_tunnel/{t['id']}/configurations", {"config": {"ingress": [
        {"hostname": NOME, "service": SERVIZIO},
        {"service": "http_status:404"},
    ]}})
    print(f"tunnel: {NOME} → {SERVIZIO}")
    return t["id"]


def dns(id_tunnel: str):
    zona = api("GET", f"/zones?name={ZONA}")[0]["id"]
    record = {"type": "CNAME", "name": NOME, "content": f"{id_tunnel}.cfargotunnel.com", "proxied": True,
              "comment": "copia pubblica del sito assicurazioni (tunnel)"}
    vecchi = api("GET", f"/zones/{zona}/dns_records?name={NOME}")
    if vecchi:
        api("PUT", f"/zones/{zona}/dns_records/{vecchi[0]['id']}", record)
        print("DNS: aggiornato")
    else:
        api("POST", f"/zones/{zona}/dns_records", record)
        print("DNS: creato")


def chiave_turn():
    """Il segreto di una chiave TURN si vede solo quando la si crea: se quella nel file .env esiste ancora, resta."""
    try:
        chiavi = api("GET", f"/accounts/{ACCOUNT}/calls/turn_keys")
    except ErroreApi as e:
        if 10000 not in e.codici:
            raise
        print("TURN: NON configurato, al token manca il permesso Account → Calls → Edit (l'audio userà solo lo STUN)")
        return
    if leggi_env().get("CLOUDFLARE_TURN_KEY_ID") in {c["uid"] for c in chiavi}:
        print("TURN: chiave già presente")
        return
    nuova = api("POST", f"/accounts/{ACCOUNT}/calls/turn_keys", {"name": TUNNEL})
    salva_env({"CLOUDFLARE_TURN_KEY_ID": nuova["uid"], "CLOUDFLARE_TURN_KEY_TOKEN": nuova["secret"]})
    print("TURN: chiave creata")


def main():
    dns(tunnel())
    chiave_turn()


if __name__ == "__main__":
    try:
        main()
    except ErroreApi as e:
        sys.exit(str(e))
