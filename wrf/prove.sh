#!/usr/bin/env bash
# Collaudo di tutto quello che si puo' provare senza far girare WRF (pochi minuti, nessuna chiave).
# Lo lancia GitHub a ogni modifica (.github/workflows/prova.yml); si puo' lanciare anche a mano:
#   bash wrf/prove.sh [CARTELLA]        (default: una cartella temporanea)
# Con PROVA_RADAR=1 prova anche il radar vero (serve internet).
set -euo pipefail
QUI=$(cd "$(dirname "$0")" && pwd)
RADICE=$(dirname "$QUI")
T=${1:-$(mktemp -d)}
mkdir -p "$T"
cd "$RADICE"
passo() { echo; echo "== $*"; }

passo "sintassi Python e nomi non definiti"
python3 -m py_compile wrf/*.py previsioni_castelli.py
python3 -m pyflakes wrf/*.py previsioni_castelli.py

passo "script bash"
shellcheck -S warning wrf/*.sh

passo "compilazione a tappe: avanzamento, tempo massimo e guardiano (comandi inventati)"
bash wrf/prova_costruzione.sh "$T/costruzione"

passo "domini e namelist (riletti con f90nml)"
python3 wrf/dominio.py
python3 - <<'EOF'
import subprocess, f90nml
def nml(*a):
    return f90nml.reads(subprocess.check_output(["python3", "wrf/config.py", *a], text=True))
w = nml("wps", "--ciclo", "2026101600", "--ore", "48", "--sst")
assert w["metgrid"]["fg_name"] == ["ECMWF", "SST"], w["metgrid"]["fg_name"]
fine = None
for da, a in ((0, 16), (16, 32), (32, 48)):
    n = nml("input", "--ciclo", "2026101600", "--da", str(da), "--a", str(a), "--obs-minuti", "530")
    tc = n["time_control"]
    assert tc["restart"] == (da > 0) and tc["run_hours"] == a - da and tc["restart_interval"] == (a - da) * 60
    inizio = (tc["start_day"][0], tc["start_hour"][0])
    assert fine is None or inizio == fine, "un segmento non riparte dove finisce il precedente"
    fine = (tc["end_day"][0], tc["end_hour"][0])
    assert n["fdda"]["fdda_end"][0] == 530.0
print("namelist ok")
EOF

passo "file WRF e geo_em inventati"
python3 wrf/prova_sintetica.py --out "$T/sint" --geo "$T/geo"

passo "stazioni per il nudging (inventate) e rilettura con i formati di WRF"
python3 wrf/stazioni_wrf.py --prova --ciclo 2026101600 --geo "$T/geo" --out "$T/obs"
gfortran wrf/leggi_obs.f90 -o "$T/leggi_obs"
for f in "$T"/obs/OBS_DOMAIN101 "$T"/obs/OBS_DOMAIN201 "$T"/obs/OBS_DOMAIN301; do "$T/leggi_obs" "$f"; done

passo "temperatura del mare: formato intermedio di WPS riletto"
python3 - "$T" <<'EOF'
import struct, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "wrf")
import scarica_sst as s
lat, lon = np.linspace(39, 44.5, 23), np.linspace(9, 16.5, 31)
k = np.where(np.random.default_rng(0).random((23, 31)) > 0.3, 290.0, -1.0e30)
p = Path(sys.argv[1]) / "SST:2026-10-16_00"
s.scrivi_intermedio(p, "2026-10-16_00:00:00", lat, lon, k)
b = p.read_bytes(); pos = 0
def rec():
    global pos
    n = struct.unpack(">i", b[pos:pos + 4])[0]; r = b[pos + 4:pos + 4 + n]
    assert struct.unpack(">i", b[pos + 4 + n:pos + 8 + n])[0] == n; pos += n + 8; return r
assert struct.unpack(">i", rec())[0] == 5
h = rec(); assert h[:19] == b"2026-10-16_00:00:00" and h[60:69].strip() == b"SST"
nx, ny, iproj = struct.unpack(">iii", h[-12:]); assert (nx, ny, iproj) == (31, 23, 0)
rec(); rec()
z = np.frombuffer(rec(), ">f4").reshape(ny, nx); assert np.allclose(z, k) and pos == len(b)
print("SST ok")
EOF

passo "mappe da wrfout inventati"
python3 wrf/postprocess.py --uscite "$T/sint" --out "$T/mappe" --ciclo 2026101600 --senza-stazioni --da-ora 2026-10-16T08:00
[ "$(find "$T/mappe" -name '*.png' | wc -l)" -ge 9 ] || { echo "mancano mappe"; exit 1; }

passo "movimento della pioggia su un caso inventato"
python3 - <<'EOF'
import sys
sys.path.insert(0, "wrf")
import numpy as np
from scipy.ndimage import gaussian_filter, shift
import radar
rng = np.random.default_rng(0)
a = np.zeros((500, 500), "float32")
for _ in range(40):
    y, x = rng.integers(100, 400, 2)
    a[y - 6:y + 6, x - 8:x + 8] = rng.uniform(1, 20)
a = gaussian_filter(a, 3) * 3
v, _ = radar.movimento(a, shift(a, (6, 18), order=1), 6)
assert np.allclose(v, (3, 1), atol=0.2), v
v, _ = radar.movimento(a, shift(a, (1, 2), order=1), 6)
assert not v.any(), v
r = radar.estrapola(a, np.broadcast_to(np.float32([3, 1]), a.shape + (2,)).copy(), 6)
assert np.abs(r[150:350, 150:350] - shift(a, (6, 18), order=1)[150:350, 150:350]).max() < 0.5
print("movimento ok")
EOF

if [ "${PROVA_RADAR:-0}" = 1 ]; then
  passo "radar vero (Radar-DPC) con WRF inventato"
  python3 wrf/pioggia_radar.py --uscite "$T/sint" --out "$T/mappe" --ciclo 2026101600
fi

echo; echo "TUTTO OK  (file in $T)"
