#!/bin/sh
# Prepara la configurazione con i valori dell'ambiente, poi avvia Asterisk in primo piano.
# Tutto ciò che Asterisk scrive sta in /run/centralino (in memoria: il container è in sola lettura).
set -eu

: "${TELEFONO_IP:?serve l'indirizzo su cui ascoltare (quello della tailnet)}"
: "${TELEFONO_SEGRETO:?serve il segreto condiviso con il server della voce}"
: "${TELEFONO_PASSWORD_PROVA:?serve la password del telefono di prova}"
export VOCE_URL="${VOCE_URL:-ws://127.0.0.1:8002/telefono}"

QUI=/run/centralino
mkdir -p "$QUI/conf" "$QUI/db" "$QUI/spool" "$QUI/log" "$QUI/run" "$QUI/prova"

# Solo queste variabili: il resto dei ${…} è dialplan di Asterisk e deve restare com'è
VARIABILI='$TELEFONO_IP $TELEFONO_SEGRETO $TELEFONO_PASSWORD_PROVA $VOCE_URL
$OPERATORE_SERVER $OPERATORE_UTENTE $OPERATORE_PASSWORD $OPERATORE_IP_PUBBLICO'

for modello in /etc/asterisk-modelli/*.conf; do
    envsubst "$VARIABILI" < "$modello" > "$QUI/conf/$(basename "$modello")"
done

# Il numero vero si collega solo quando ci sono i dati dell'operatore
if [ -n "${OPERATORE_UTENTE:-}" ]; then
    : "${OPERATORE_SERVER:?serve il server SIP dell'operatore}"
    : "${OPERATORE_PASSWORD:?serve la password SIP dell'operatore}"
    : "${OPERATORE_IP_PUBBLICO:?serve l'indirizzo pubblico del server}"
    envsubst "$VARIABILI" < /etc/asterisk-modelli/operatore/pjsip_operatore.conf \
        > "$QUI/conf/pjsip_operatore.conf"
fi

exec asterisk -f -C "$QUI/conf/asterisk.conf"
