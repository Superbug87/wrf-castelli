#!/usr/bin/env bash
# Pubblica le immagini nel ramo "risultati" del repository:
#   ultimo/            i fogli di sintesi dell'ultima previsione
#   archivio/<ciclo>/  i fogli degli ultimi 28 cicli
#   orarie/            una immagine per ora e variabile degli ultimi 2 cicli + indice.json (lo legge la pagina del sito)
# Il ramo viene riscritto con un solo commit a ogni pubblicazione: la storia non si accumula (le immagini pesano).
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
cp "$IMG"/*.csv "archivio/$CICLO/" 2>/dev/null || true       # statistiche del confronto con il radar, solo nell'archivio
if [ -f "$IMG/orarie/indice.json" ]; then
  mkdir -p orarie
  for d in "$IMG"/orarie/*/; do rm -rf "orarie/$(basename "$d")"; cp -r "$d" "orarie/$(basename "$d")"; done
  cp "$IMG/orarie/indice.json" orarie/indice.json
  # si tengono i 2 cicli piu' recenti: chi ha ancora in memoria il vecchio indice non trova immagini sparite
  ls -1d orarie/*/ 2>/dev/null | sort | head -n -2 | xargs -r rm -rf
fi
{
  PIL=${PILOTA:-ecmwf}; echo "# Ultima previsione WRF — ciclo ${PIL^^} ${CICLO:0:8} ${CICLO:8:2}Z"
  echo
  echo "> Esperimento personale, **non un servizio ufficiale**: può sbagliare e non sostituisce bollettini e allerte della Protezione Civile e dell'Aeronautica Militare. Nessuna garanzia."
  if [ "${PIL}" = "gfs" ]; then FONTE="NOAA/NCEP GFS"; else FONTE="ECMWF IFS open data (CC BY 4.0, dati modificati)"; fi
  echo ">"
  echo "> Dati di partenza: ${FONTE}. Modello: WRF (NCAR). Temperatura del mare: MUR SST (NASA JPL), quando disponibile. Stazioni: Weather Underground, usate solo dentro il modello e non ripubblicate. Fonti e licenze: [README del progetto](https://github.com/${GITHUB_REPOSITORY:-utente/repo}#fonti-dei-dati-e-licenze)."
  if ls ultimo/radar_*.png >/dev/null 2>&1; then
    echo ">"
    echo "> Le immagini «radar_*» contengono dati Radar-DPC, Dipartimento della Protezione Civile (radar.protezionecivile.it), licenza [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): le immagini ricavate da quei dati hanno la stessa licenza."
  fi
  if [ -f orarie/indice.json ]; then echo; echo "Una immagine per ogni ora e variabile: cartella [orarie/](orarie/), elenco in [indice.json](orarie/indice.json)."; fi
  echo
  for f in ultimo/*.png; do echo "![$(basename "$f" .png)]($f)"; echo; done
} > README.md
# l'archivio tiene solo gli ultimi 28 cicli (14 giorni con due cicli al giorno)
ls -1d archivio/*/ 2>/dev/null | head -n -28 | xargs -r rm -rf
git config user.name "github-actions"; git config user.email "actions@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then echo "niente da pubblicare"; exit 0; fi
if git rev-parse -q --verify HEAD >/dev/null; then git checkout -q --orphan nuovo; fi   # un solo commit: la storia delle immagini non si accumula
git commit -q -m "Previsione WRF $CICLO"
git push -q --force origin HEAD:refs/heads/risultati
echo "pubblicato nel ramo risultati"
