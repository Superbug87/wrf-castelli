#!/usr/bin/env bash
# Dati statici (terreno, uso del suolo, suoli): scarica i dati geografici NCAR, lancia geogrid
# e conserva solo i piccoli file geo_em.d0*.nc (messi in cache: si fa una volta sola).
set -euo pipefail
QUI=$(cd "$(dirname "$0")" && pwd)
INSTALL=${INSTALL:-$HOME/wrf-install}
GEO=${GEO:-$HOME/wrf-geo}
GEOG=$HOME/dati-geografici
URL=https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_high_res_mandatory.tar.gz

# liberiamo spazio sul runner: i dati geografici scompattati sono parecchi GB
sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL || true
df -h / | tail -n1

mkdir -p "$GEOG" "$GEO"
echo "== download dei dati geografici (in streaming)"
curl -fL --retry 8 --retry-delay 15 --retry-all-errors "$URL" | tar -xz -C "$GEOG"
TOPO=$(find "$GEOG" -maxdepth 3 -type d -name topo_gmted2010_30s | head -n1)
[ -n "$TOPO" ] || { echo "topo_gmted2010_30s non trovato nell'archivio:"; ls -R "$GEOG" | head -n 40; exit 1; }
GEOG_PATH=$(dirname "$TOPO")
echo "dati geografici in: $GEOG_PATH"; ls "$GEOG_PATH"

# quota 30 m (Copernicus) e/o uso del suolo 10 m (WorldCover) al posto dei dati di serie (900 m / 500 m).
# DATI_FINI: "suolo" (default), "dem", "dem,suolo" oppure "0" per nessuno.
# I dati fini coprono solo l'area del dominio a 1 km (suolo) o dei domini a 3 km (quota): geogrid non riempie da solo
# il resto con i dati di serie, quindi si usano solo per i domini che stanno dentro l'area (vedi RES sotto).
DATI_FINI=${DATI_FINI:-suolo}
RES=default
if [ "$DATI_FINI" != 0 ]; then
  echo "== dati fini: $DATI_FINI"
  python3 -m pip install --quiet rasterio numpy scipy
  python3 "$QUI/dati_fini.py" --out "$GEOG_PATH" --parti "$DATI_FINI"
  case "$DATI_FINI" in
    dem,suolo|suolo,dem) echo "quota e suolo fini insieme non sono supportati (stessa chiave 'fine' con aree diverse)"; exit 1 ;;
    suolo) RES=default,default,fine+default ;;          # il suolo a 10 m copre solo il dominio a 1 km
    *dem*) RES=default,fine+default,fine+default ;;      # la quota a 30 m copre i domini a 3 e 1 km
  esac
fi

W=$HOME/lavoro-geogrid
rm -rf "$W"; mkdir -p "$W"
cp -aL "$INSTALL/WPS/." "$W/"
cd "$W"
if [ "$DATI_FINI" != 0 ]; then
  python3 "$QUI/dati_fini.py" --tabella geogrid/GEOGRID.TBL --parti "$DATI_FINI"
fi
python3 "$QUI/config.py" wps --ciclo 2026010100 --ore 6 --geog "$GEOG_PATH" --res "$RES" > namelist.wps
./geogrid.exe > geogrid.log 2>&1 || { tail -n 60 geogrid.log; exit 1; }
tail -n 3 geogrid.log
ls geo_em.d0*.nc
cp geo_em.d0*.nc "$GEO/"
du -sh "$GEO"
