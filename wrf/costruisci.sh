#!/usr/bin/env bash
# Compila WRF e WPS e lascia in $INSTALL solo ciò che serve per girare (cartella messa in cache).
set -euo pipefail
WRF_TAG=${WRF_TAG:-v4.7.0}
WPS_TAG=${WPS_TAG:-v4.7.0}
INSTALL=${INSTALL:-$HOME/wrf-install}
SRC=${SRC:-$HOME/wrf-src}
NC=$HOME/netcdf-combinato
NPROC=$(nproc)

mkdir -p "$SRC" "$INSTALL" "$NC/include" "$NC/lib"
# Su Debian/Ubuntu netCDF-C e netCDF-Fortran stanno in posti diversi: le riuniamo in una cartella sola
ln -sf /usr/include/netcdf* "$NC/include/"
ln -sf /usr/lib/x86_64-linux-gnu/libnetcdf* "$NC/lib/"
export NETCDF="$NC"
export NETCDF_classic=1
export WRFIO_NCD_LARGE_FILE_SUPPORT=1
export JASPERLIB=/usr/lib/x86_64-linux-gnu
export JASPERINC=/usr/include

cd "$SRC"
[ -d WRF ] || git clone --depth 1 --branch "$WRF_TAG" https://github.com/wrf-model/WRF.git
[ -d WPS ] || git clone --depth 1 --branch "$WPS_TAG" https://github.com/wrf-model/WPS.git

echo "== WRF: configure"
cd "$SRC/WRF"
OPT=$(./configure < /dev/null 2>/dev/null | grep -E 'GNU \(gfortran/gcc\)' | grep -oP '\d+(?=\.\s+\(dmpar\))' | head -n1 || true)
OPT=${OPT:-34}
echo "opzione scelta: $OPT (gfortran, dmpar), nesting basic"
printf '%s\n1\n' "$OPT" | ./configure > configure.log 2>&1 || { tail -n 40 configure.log; exit 1; }

echo "== WRF: compile em_real (puo' richiedere 40-90 minuti)"
./compile -j "$NPROC" em_real > compile.log 2>&1 || true
if [ ! -s main/wrf.exe ] || [ ! -s main/real.exe ]; then
  echo "Compilazione di WRF fallita, ultime righe:"; tail -n 60 compile.log; exit 1
fi

echo "== WPS: configure + compile"
cd "$SRC/WPS"
export WRF_DIR="$SRC/WRF"
OPT=$(./configure < /dev/null 2>/dev/null | grep -E 'gfortran +\(serial\)' | grep -v NO_GRIB2 | grep -oP '^\s*\K\d+' | head -n1 || true)
OPT=${OPT:-1}
echo "opzione scelta: $OPT (gfortran, serial, GRIB2)"
echo "$OPT" | ./configure > configure.log 2>&1 || { tail -n 40 configure.log; exit 1; }
./compile > compile.log 2>&1 || true
for e in geogrid.exe ungrib.exe metgrid.exe; do
  [ -s "$e" ] || { echo "WPS: manca $e, ultime righe:"; tail -n 60 compile.log; exit 1; }
done

echo "== installazione in $INSTALL"
rm -rf "$INSTALL"; mkdir -p "$INSTALL/WRF/run" "$INSTALL/WPS/geogrid" "$INSTALL/WPS/metgrid" "$INSTALL/WPS/ungrib/Variable_Tables"
cp -L "$SRC/WRF/main/wrf.exe" "$SRC/WRF/main/real.exe" "$INSTALL/WRF/"
cp -aL "$SRC/WRF/run/." "$INSTALL/WRF/run/"
rm -f "$INSTALL"/WRF/run/*.exe "$INSTALL"/WRF/run/namelist.input
cp -L "$SRC"/WPS/{geogrid,ungrib,metgrid}.exe "$SRC/WPS/link_grib.csh" "$INSTALL/WPS/"
cp -L "$SRC/WPS/geogrid/GEOGRID.TBL.ARW" "$INSTALL/WPS/geogrid/GEOGRID.TBL"
cp -L "$SRC/WPS/metgrid/METGRID.TBL.ARW" "$INSTALL/WPS/metgrid/METGRID.TBL"
cp -L "$SRC/WPS/ungrib/Variable_Tables/Vtable.GFS" "$INSTALL/WPS/ungrib/Variable_Tables/"
du -sh "$INSTALL"
echo "fatto"
