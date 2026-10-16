#!/usr/bin/env python3
"""
postprocess.py - dal dominio a 1 km di WRF alle stesse mappe a fogli di previsioni_castelli.py.

  python wrf/postprocess.py --uscite cartella_con_wrfout --out mappe [--ciclo 2026101600]

Legge wrfout_d03_* (e wrfxtrm_d03_*, se ci sono, per le raffiche), calcola le grandezze che WRF non
scrive già pronte (temperatura a 850 hPa, pressione al livello del mare, umidità, CAPE, pioggia oraria),
le ricampiona su una griglia regolare lat/lon di ~0,5 km e disegna un'immagine per variabile.

Stime, da dichiarare sempre:
  - raffica = massimo orario del vento a 10 m (diagnostica di WRF) x 1,4
  - CAPE = parcella di superficie, salita pseudoadiabatica integrata a passi (non è wrf-python)
"""
import argparse
import glob
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["TZ"] = "Europe/Rome"      # datetime.now() delle funzioni di previsioni_castelli = ora locale
time.tzset()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from netCDF4 import Dataset, chartostring  # noqa: E402
from scipy.interpolate import LinearNDInterpolator  # noqa: E402
from scipy.spatial import Delaunay  # noqa: E402

import previsioni_castelli as pc  # noqa: E402

G0, RD, CP, LV, EPS = 9.80665, 287.04, 1004.0, 2.5e6, 0.622
KAPPA = RD / CP
FATTORE_RAFFICA = 1.4


# ----------------------------------------------------------------------------
# Fisica di base
# ----------------------------------------------------------------------------
def p_sat(T):
    """Pressione di saturazione (Pa), T in K (Bolton 1980)."""
    tc = T - 273.15
    return 611.2 * np.exp(17.67 * tc / (tc + 243.5))


def r_sat(T, p):
    e = p_sat(T)
    return EPS * e / np.maximum(p - e, 1.0)


def td_da_e(e):
    """Punto di rugiada (K) dalla tensione di vapore e (Pa)."""
    g = np.log(np.maximum(e, 1e-3) / 611.2)
    return 243.5 * g / (17.67 - g) + 273.15


def salita_umida(T, p_da, p_a, passi=8):
    """Integra la pseudoadiabatica da p_da a p_a (p_a <= p_da). Tutti array della stessa forma."""
    def dT_dlnp(t, p):
        r = r_sat(t, p)
        return (RD * t + LV * r) / (CP + LV * LV * r * EPS / (RD * t * t))

    T = T.copy()
    p = p_da.copy()
    h = np.log(p_a / p_da) / passi
    for _ in range(passi):
        k1 = dT_dlnp(T, p)
        k2 = dT_dlnp(T + 0.5 * h * k1, p * np.exp(0.5 * h))
        T = T + h * k2
        p = p * np.exp(h)
    return T


def cape_superficie(p, tk, w, z):
    """
    CAPE (J/kg) di una parcella partita dal livello più basso del modello.
    p (Pa), tk (K), w (rapporto di mescolanza, kg/kg), z (m, livelli di massa): forma (colonne, livelli).
    """
    n, nz = p.shape
    p0, T0, w0 = p[:, 0], tk[:, 0], w[:, 0]
    e0 = w0 * p0 / (EPS + w0)
    Td0 = np.minimum(td_da_e(e0), T0)
    T_lcl = 1.0 / (1.0 / (Td0 - 56.0) + np.log(T0 / Td0) / 800.0) + 56.0
    p_lcl = p0 * (T_lcl / T0) ** (1.0 / KAPPA)

    Tp = np.empty_like(tk)
    wp = np.empty_like(tk)
    Tp[:, 0], wp[:, 0] = T0, w0
    sopra = np.zeros(n, bool)
    T_prec, p_prec = T0, p0
    for k in range(1, nz):
        pk = p[:, k]
        secco = pk >= p_lcl
        T_secco = T0 * (pk / p0) ** KAPPA
        p_start = np.where(sopra, p_prec, p_lcl)
        T_start = np.where(sopra, T_prec, T_lcl)
        T_umido = salita_umida(T_start, p_start, np.minimum(pk, p_start))
        Tk = np.where(secco, T_secco, T_umido)
        Tp[:, k] = Tk
        wp[:, k] = np.where(secco, w0, r_sat(Tk, pk))
        sopra = ~secco
        T_prec, p_prec = Tk, pk

    tv_p = Tp * (1 + wp / EPS) / (1 + wp)
    tv_e = tk * (1 + w / EPS) / (1 + w)
    b = G0 * (tv_p - tv_e) / tv_e
    b_med = 0.5 * (b[:, :-1] + b[:, 1:])
    dz = np.diff(z, axis=1)
    p_med = 0.5 * (p[:, :-1] + p[:, 1:])
    valido = (p_med < p_lcl[:, None]) & (p_med > 10000.0) & (b_med > 0)
    return np.where(valido, b_med * dz, 0.0).sum(axis=1)


# ----------------------------------------------------------------------------
# Lettura di WRF
# ----------------------------------------------------------------------------
def tempi_file(ds):
    return [datetime.strptime(str(s).strip(), "%Y-%m-%d_%H:%M:%S") for s in chartostring(ds["Times"][:])]


def elabora_wrfout(percorso):
    """Una sola passata sul file: restituisce i tempi (UTC) e i campi derivati, forma (tempo, y, x)."""
    with Dataset(percorso) as ds:
        ds.set_auto_mask(False)
        v = lambda nome: np.asarray(ds[nome][:], dtype=np.float64)
        tempi = tempi_file(ds)
        nt = len(tempi)

        T2, Q2, PSFC = v("T2"), v("Q2"), v("PSFC")
        U10, V10 = v("U10"), v("V10")
        cosa, sina = v("COSALPHA"), v("SINALPHA")
        out = {
            "ue": U10 * cosa - V10 * sina,           # da vento "della griglia" a est/nord
            "ve": V10 * cosa + U10 * sina,
            "rain": v("RAINC") + v("RAINNC"),
        }
        hgt = v("HGT")

        # temperatura del punto di rugiada a 2 m
        e = Q2 * PSFC / (EPS + Q2)
        out["T2"] = T2
        out["Td2"] = np.minimum(td_da_e(e), T2)
        # pressione al livello del mare (riduzione barometrica con temperatura media dello strato)
        tv = T2 * (1 + 0.61 * Q2)
        out["slp"] = PSFC * np.exp(G0 * hgt / (RD * (tv + 0.0065 * hgt / 2))) / 100.0

        # grandezze 3D
        p = v("P") + v("PB")
        qv = v("QVAPOR")
        th = v("T") + 300.0
        if "USE_THETA_M" in ds.ncattrs() and int(ds.getncattr("USE_THETA_M")) == 1:
            th = th / (1 + 1.61 * qv)
        tk = th * (p / 1e5) ** KAPPA
        ph = (v("PH") + v("PHB")) / G0
        z = 0.5 * (ph[:, :-1] + ph[:, 1:])
        nz = p.shape[1]

        # temperatura a 850 hPa: interpolazione lineare in ln p tra i due livelli attorno a 850
        sotto = (p >= 85000.0).sum(axis=1)
        k1 = np.clip(sotto, 1, nz - 1)[:, None]
        k0 = k1 - 1
        p0, p1 = (np.take_along_axis(p, k, 1)[:, 0] for k in (k0, k1))
        t0, t1 = (np.take_along_axis(tk, k, 1)[:, 0] for k in (k0, k1))
        out["T850"] = t0 + (t1 - t0) * np.log(85000.0 / p0) / np.log(p1 / p0)

        # CAPE
        col = lambda a: np.moveaxis(a, 1, -1).reshape(-1, nz)
        out["cape"] = cape_superficie(col(p), col(tk), col(qv), col(z)).reshape(nt, *T2.shape[1:])

        statici = {"lat": v("XLAT")[0], "lon": v("XLONG")[0], "hgt": hgt[0]}
    return tempi, out, statici


def raffiche_da_xtrm(cartella):
    """Massimo orario del vento a 10 m dai file wrfxtrm_d03_* (dict istante -> campo), o {}."""
    res = {}
    for f in sorted(glob.glob(os.path.join(cartella, "**", "wrfxtrm_d03_*"), recursive=True)):
        with Dataset(f) as ds:
            ds.set_auto_mask(False)
            nome = next((n for n in ("SPDUV10MAX", "WSPD10MAX") if n in ds.variables), None)
            if nome is None:
                continue
            for t, campo in zip(tempi_file(ds), np.asarray(ds[nome][:], dtype=np.float64)):
                res[t] = campo
    return res


def carica(cartella):
    files = sorted(glob.glob(os.path.join(cartella, "**", "wrfout_d03_*"), recursive=True))
    if not files:
        sys.exit(f"Nessun file wrfout_d03_* in {cartella}")
    frames, statici = {}, None
    for f in files:
        print("leggo", Path(f).name, flush=True)
        tempi, campi, st = elabora_wrfout(f)
        statici = statici or st
        for i, t in enumerate(tempi):                  # al riavvio il primo istante è doppio: vale l'ultimo
            frames[t] = {k: a[i] for k, a in campi.items()}
    tempi = sorted(frames)
    dati = {k: np.stack([frames[t][k] for t in tempi]) for k in frames[tempi[0]]}
    return tempi, dati, statici, raffiche_da_xtrm(cartella)


# ----------------------------------------------------------------------------
# Dal reticolo di WRF alla griglia regolare delle mappe
# ----------------------------------------------------------------------------
def ricampiona(campi, statici, lat_f, lon_f):
    punti = np.column_stack([statici["lon"].ravel(), statici["lat"].ravel()])
    tri = Delaunay(punti)
    LON, LAT = np.meshgrid(lon_f, lat_f)
    out = {}
    for nome, a in campi.items():
        nt = a.shape[0]
        f = LinearNDInterpolator(tri, a.reshape(nt, -1).T)
        r = np.moveaxis(f(LON, LAT), -1, 0)
        if np.isnan(r).any():
            sys.exit(f"'{nome}': la griglia delle mappe esce dal dominio a 1 km di WRF")
        out[nome] = r
    z = LinearNDInterpolator(tri, statici["hgt"].ravel())(LON, LAT)
    return out, np.clip(z, 0, None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uscite", required=True, help="cartella con i wrfout_d03_* (anche in sottocartelle)")
    ap.add_argument("--out", default="mappe")
    ap.add_argument("--ciclo", default="", help="AAAAMMGGHH del ciclo usato, solo per il titolo")
    ap.add_argument("--pilota", default="ecmwf", choices=["ecmwf", "gfs"], help="modello globale usato, solo per il titolo")
    ap.add_argument("--n", type=int, default=80, help="punti per lato della griglia delle mappe")
    ap.add_argument("--senza-stazioni", action="store_true")
    ap.add_argument("--max-stazioni", type=int, default=60)
    ap.add_argument("--da-ora", default="", help="ora locale ISO da cui partire (default: l'ora attuale)")
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)

    tempi_utc, dati, statici, xtrm = carica(a.uscite)
    nt = len(tempi_utc)
    roma = ZoneInfo("Europe/Rome")
    tempi = [t.replace(tzinfo=timezone.utc).astimezone(roma).replace(tzinfo=None) for t in tempi_utc]

    # raffica stimata
    vento = np.hypot(dati["ue"], dati["ve"])
    G = None
    if xtrm:
        mx = np.stack([xtrm.get(t, np.zeros_like(vento[0])) for t in tempi_utc])
        G = np.maximum(FATTORE_RAFFICA * mx, vento)
    # pioggia oraria (dalle somme cumulate) e T in °C
    P = np.clip(np.diff(dati["rain"], axis=0, prepend=dati["rain"][:1]), 0, None)
    campi_nativi = {
        "T": dati["T2"] - 273.15, "Td": dati["Td2"] - 273.15, "T850": dati["T850"] - 273.15,
        "p": dati["slp"], "u": dati["ue"], "v": dati["ve"], "P": P, "cape": dati["cape"],
    }
    if G is not None:
        campi_nativi["G"] = G

    lat_f, lon_f = pc.griglia_fine(a.n)
    c, z_f = ricampiona(campi_nativi, statici, lat_f, lon_f)
    c["RH"] = pc.umidita_relativa(c["T"], c["Td"])
    c["G"] = c.get("G")
    c["P"] = np.clip(c["P"], 0, None)
    c["cape"] = np.clip(c["cape"], 0, None)
    c["P3"], c["P6"] = pc.somma_mobile(c["P"], 3), pc.somma_mobile(c["P"], 6)

    # si parte dall'ora attuale (il modello è partito qualche ora fa)
    ora = datetime.fromisoformat(a.da_ora) if a.da_ora else datetime.now().replace(minute=0, second=0, microsecond=0)
    i0 = next((i for i, t in enumerate(tempi) if t >= ora), 0)
    tempi = tempi[i0:]
    c = {k: (v[i0:] if isinstance(v, np.ndarray) else v) for k, v in c.items()}
    print(f"{len(tempi)} ore da {tempi[0]:%a %d %H:%M} a {tempi[-1]:%a %d %H:%M} (ora locale)")

    pil = a.pilota.upper()
    ciclo_txt = f"{pil} {a.ciclo[:8]} {a.ciclo[8:]}Z" if a.ciclo else pil
    banner = f"WRF 1 km ({ciclo_txt})"
    modello_txt = (f"WRF: modello fisico con tre domini annidati (9, 3 e 1 km) alimentato da {pil}; le mappe "
                   f"sono ricampionate a {2 * pc.MEZZO_LAT * 111.32 / (a.n - 1):.1f} km. "
                   "Raffiche: stima, massimo orario del vento a 10 m x 1,4. CAPE: stima da parcella di superficie.")

    if not a.senza_stazioni and os.environ.get("WU_API_KEY"):
        chiave = os.environ["WU_API_KEY"]
        pc.SEGRETI.append(chiave)
        try:
            scelte = pc.diradamento(pc.cerca_stazioni(chiave), a.max_stazioni)
            c, info = pc.correggi_con_stazioni(c, tempi, pc.leggi_stazioni(chiave, scelte), z_f, lat_f, lon_f)
            print(info["testo"])
            if info["n"] >= 3:
                banner += f" + {info['n']} stazioni WU"
                modello_txt += " " + info["nota"]
        except Exception as e:                            # la correzione è facoltativa
            print("Stazioni Wunderground non disponibili:", pc._pulisci(str(e)), file=sys.stderr)

    creati = pc.disegna_fogli(c, z_f, lat_f, lon_f, tempi, banner, modello_txt, a.out)
    for f in creati:
        print("Creato:", f)

    iy = int(np.abs(lat_f - pc.STAZIONE[1]).argmin())
    ix = int(np.abs(lon_f - pc.STAZIONE[2]).argmin())
    print(f"Velletri: T {c['T'][:, iy, ix].min():.0f}-{c['T'][:, iy, ix].max():.0f} °C, "
          f"vento max {np.hypot(c['u'], c['v'])[:, iy, ix].max() * 3.6:.0f} km/h, "
          f"pioggia 6 h max {c['P6'][:, iy, ix].max():.1f} mm, CAPE max {c['cape'][:, iy, ix].max():.0f} J/kg")


if __name__ == "__main__":
    main()
