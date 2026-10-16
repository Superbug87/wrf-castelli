#!/usr/bin/env bash
# Carica sul sito (FTP) le pagine della cartella sito/. Le credenziali arrivano dall'ambiente (segreti di GitHub):
#   FTP_HOST (es. ftp.pyquake.altervista.org), FTP_USER, FTP_PASSWORD, FTP_CARTELLA (es. 5archi; vuota = radice)
# Uso: carica_sito.sh FILE...
# Con TLS, se il server lo offre (--ssl: se non lo offre prosegue in chiaro). Nessuna credenziale finisce nel log.
set -euo pipefail
if [ -z "${FTP_HOST:-}" ] || [ -z "${FTP_USER:-}" ] || [ -z "${FTP_PASSWORD:-}" ]; then
  echo "::notice::Segreti FTP non impostati (FTP_HOST, FTP_USER, FTP_PASSWORD): niente caricamento sul sito."
  exit 0
fi
CARTELLA=${FTP_CARTELLA:-}; CARTELLA=${CARTELLA#/}; CARTELLA=${CARTELLA%/}
BASE="ftp://${FTP_HOST}${FTP_PORTA:+:$FTP_PORTA}/${CARTELLA:+$CARTELLA/}"
for f in "$@"; do
  curl --fail --silent --show-error --ssl --ftp-create-dirs --connect-timeout 30 --max-time 300 \
       --user "${FTP_USER}:${FTP_PASSWORD}" -T "$f" "${BASE}$(basename "$f")" \
    || { echo "!! Caricamento di $(basename "$f") non riuscito (controlla host, utente, password e cartella)"; exit 1; }
  echo "caricato: $(basename "$f") -> ${CARTELLA:-/}"
done
