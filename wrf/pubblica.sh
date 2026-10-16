#!/usr/bin/env bash
# Pubblica le immagini nel ramo "risultati" del repository (cartella ultimo/ + archivio per data).
# Uso: pubblica.sh CARTELLA_IMMAGINI CICLO
set -euo pipefail
IMG=$(cd "${1:?cartella immagini}" && pwd); CICLO=${2:?ciclo}
REPO_URL=${REPO_URL:-"https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"}
T=$(mktemp -d)
cd "$T"
git init -q
git remote add origin "$REPO_URL"
if git fetch -q --depth 1 origin risultati 2>/dev/null; then git checkout -q -b risultati FETCH_HEAD; else git checkout -q --orphan risultati; fi
rm -rf ultimo; mkdir -p ultimo "archivio/$CICLO"
cp "$IMG"/*.png ultimo/
cp "$IMG"/*.png "archivio/$CICLO/"
{
  PIL=${PILOTA:-ecmwf}; echo "# Ultima previsione WRF — ciclo ${PIL^^} ${CICLO:0:8} ${CICLO:8:2}Z"
  echo
  echo "> Esperimento personale, **non un servizio ufficiale**: può sbagliare e non sostituisce bollettini e allerte della Protezione Civile e dell'Aeronautica Militare. Nessuna garanzia."
  if [ "${PIL}" = "gfs" ]; then FONTE="NOAA/NCEP GFS"; else FONTE="ECMWF IFS open data (CC BY 4.0, dati modificati)"; fi
  echo ">"
  echo "> Dati di partenza: ${FONTE}. Modello: WRF (NCAR). Temperatura del mare: MUR SST (NASA JPL), quando disponibile. Stazioni: Weather Underground, usate solo dentro il modello e non ripubblicate. Fonti e licenze: [README del progetto](https://github.com/${GITHUB_REPOSITORY:-utente/repo}#fonti-dei-dati-e-licenze)."
  echo
  for f in ultimo/*.png; do echo "![$(basename "$f" .png)]($f)"; echo; done
} > README.md
# l'archivio tiene solo gli ultimi 14 giorni
ls -1d archivio/*/ 2>/dev/null | head -n -14 | xargs -r rm -rf
git config user.name "github-actions"; git config user.email "actions@users.noreply.github.com"
git add -A
git commit -q -m "Previsione WRF $CICLO" || { echo "niente da pubblicare"; exit 0; }
git push -q origin risultati
echo "pubblicato nel ramo risultati"
