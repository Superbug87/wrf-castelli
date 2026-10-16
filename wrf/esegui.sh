#!/usr/bin/env bash
# Uso:
#   esegui.sh prepara CICLO ORE_TOTALI        scarica GFS, ungrib, metgrid, real.exe
#   esegui.sh modello CICLO DA_ORA A_ORA      wrf.exe da DA_ORA ad A_ORA (ore dall'inizio del ciclo);
#                                             DA_ORA > 0 riprende dal restart dell'ultimo segmento
set -euo pipefail
QUI=$(cd "$(dirname "$0")" && pwd)
INSTALL=${INSTALL:-$HOME/wrf-install}
GEO=${GEO:-$HOME/wrf-geo}
LAVORO=${LAVORO:-$HOME/lavoro}
export OMP_NUM_THREADS=1
cmd=${1:?comando}; CICLO=${2:?ciclo}

cartella_run() {
  mkdir -p "$LAVORO/run"
  cd "$LAVORO/run"
  [ -e wrf.exe ] || { cp -aL "$INSTALL/WRF/run/." .; cp -L "$INSTALL/WRF/wrf.exe" "$INSTALL/WRF/real.exe" .; }
}

esito_wrf() {  # $1 = file rsl da controllare
  if ! tail -n 5 "$1" | grep -q "SUCCESS COMPLETE"; then
    echo "!! Esecuzione non riuscita. Ultime righe di $1:"; tail -n 40 "$1"
    for f in rsl.error.*; do
      grep -l -iE "fatal|segmentation|cfl|error" "$f" >/dev/null 2>&1 && { echo "--- $f"; tail -n 20 "$f"; break; }
    done
    exit 1
  fi
}

case "$cmd" in
prepara)
  ORE=${3:?ore totali}
  mkdir -p "$LAVORO/WPS" "$LAVORO/gfs"
  cd "$LAVORO"
  echo "== GFS $CICLO, ore 0-$ORE"
  python3 "$QUI/scarica_gfs.py" --ciclo "$CICLO" --ore "$ORE" --out gfs
  df -h / | tail -n1

  echo "== WPS: ungrib e metgrid"
  cp -aL "$INSTALL/WPS/." WPS/
  cp "$GEO"/geo_em.d0*.nc WPS/
  cd WPS
  python3 "$QUI/config.py" wps --ciclo "$CICLO" --ore "$ORE" > namelist.wps
  ./link_grib.csh ../gfs/gfs.t*
  ln -sf ungrib/Variable_Tables/Vtable.GFS Vtable
  ./ungrib.exe > ungrib.log 2>&1 || { tail -n 40 ungrib.log; exit 1; }
  rm -rf ../gfs GRIBFILE.*
  ./metgrid.exe > metgrid.log 2>&1 || { tail -n 40 metgrid.log; exit 1; }
  rm -f GFS:*
  ls met_em.d0* | head -n 3
  read -r NLEV NSOIL < <(python3 "$QUI/config.py" metgrid-info "$(ls met_em.d01.* | head -n1)")
  echo "livelli metgrid: $NLEV, livelli suolo: $NSOIL"

  echo "== real.exe"
  cartella_run
  ln -sf ../WPS/met_em.d0* .
  python3 "$QUI/config.py" input --ciclo "$CICLO" --da 0 --a "$ORE" --nlev "$NLEV" --nsoil "$NSOIL" > namelist.input
  rm -f rsl.*
  mpirun -np 1 ./real.exe > real.log 2>&1 || { tail -n 40 real.log; tail -n 30 rsl.error.0000 || true; exit 1; }
  esito_wrf rsl.error.0000
  ls -la wrfinput_d0* wrfbdy_d01
  rm -rf "$LAVORO/WPS"
  ;;
modello)
  DA=${3:?da ora}; A=${4:?a ora}
  cartella_run
  if [ "$DA" -gt 0 ]; then                     # ripresa: servono wrfinput, wrfbdy e il restart del segmento prima
    tar -xzf "$LAVORO/stato.tgz" -C "$LAVORO/run"
  fi
  python3 "$QUI/config.py" input --ciclo "$CICLO" --da "$DA" --a "$A" > namelist.input
  rm -f rsl.*
  echo "== wrf.exe da +${DA} h a +${A} h su $(nproc) processori ($(date -u +%H:%M) UTC)"
  mpirun -np "$(nproc)" ./wrf.exe > wrf.log 2>&1 || { tail -n 40 wrf.log; esito_wrf rsl.error.0000; exit 1; }
  esito_wrf rsl.error.0000
  echo "fine ($(date -u +%H:%M) UTC)"
  ls -la wrfout_d03_* wrfrst_d03_* 2>/dev/null | tail -n 8 || true
  # i nomi dei file di WRF contengono ":" e GitHub non li accetta come allegati: li impacchettiamo
  FINE=$(date -u -d "${CICLO:0:8} ${CICLO:8:2}:00 UTC + ${A} hours" +%Y-%m-%d_%H:%M:%S)
  tar -czf "$LAVORO/stato.tgz" wrfinput_d0* wrfbdy_d01 wrfrst_d0*_"$FINE"
  tar -czf "$LAVORO/uscite.tgz" wrfout_d03_* wrfxtrm_d03_*
  ls -la "$LAVORO"/*.tgz
  ;;
*)
  echo "comando sconosciuto: $cmd"; exit 2 ;;
esac
