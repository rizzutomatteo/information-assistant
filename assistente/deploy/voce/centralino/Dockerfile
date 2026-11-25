# Il centralino: Asterisk 22 (LTS). Si compila perché le distribuzioni hanno versioni senza
# chan_websocket, il canale che passa l'audio delle telefonate al server della voce (dalla 22.6).
FROM ubuntu:24.04 AS compila

ARG VERSIONE=22.12.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates wget bzip2 patch pkg-config python3 \
        libedit-dev libjansson-dev libsqlite3-dev uuid-dev libxml2-dev libssl-dev \
        libsrtp2-dev libcurl4-openssl-dev libspeexdsp-dev

WORKDIR /sorgenti
RUN wget -q https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${VERSIONE}.tar.gz \
        https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${VERSIONE}.sha256 \
    && sha256sum -c asterisk-${VERSIONE}.sha256 \
    && tar xzf asterisk-${VERSIONE}.tar.gz --strip-components=1

# Niente suoni né musica d'attesa da scaricare, e niente documentazione dei moduli (serve solo
# alla console di Asterisk e, senza XSLT, riempie il log di avvisi): il centralino non li usa
RUN ./configure --with-pjproject-bundled --disable-xmldoc > /dev/null \
    && make menuselect.makeopts \
    && menuselect/menuselect --disable BUILD_NATIVE --disable CORE-SOUNDS-EN-GSM \
        --disable MOH-OPSOUND-WAV menuselect.makeopts \
    && make -j"$(nproc)" > /dev/null \
    && make install DESTDIR=/radice > /dev/null


FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        libedit2 libjansson4 libsqlite3-0 libuuid1 libxml2 libssl3t64 libsrtp2-1 \
        libcurl4t64 libspeexdsp1 gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY --from=compila /radice/usr /usr
RUN ldconfig && useradd --system --uid 900 --home /var/lib/asterisk asterisk

# I modelli della configurazione: avvio.sh ci mette i valori dell'ambiente (password, indirizzi)
COPY conf /etc/asterisk-modelli
COPY avvio.sh /usr/local/bin/avvio-centralino

USER asterisk
ENTRYPOINT ["avvio-centralino"]
