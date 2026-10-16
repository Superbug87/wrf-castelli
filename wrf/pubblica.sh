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
  echo "# Ultima previsione WRF — ciclo GFS ${CICLO:0:8} ${CICLO:8:2}Z"
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
