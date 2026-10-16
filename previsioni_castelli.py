#!/usr/bin/env python3
"""
previsioni_castelli.py - mappe meteo sui Castelli Romani per le prossime 48 ore.

Come funziona:
  1. scarica da Open-Meteo un modello meteo su una griglia grossolana 7x7 (~40x40 km)
  2. scarica le quote del terreno su una griglia fine (n x n, passo ~1 km)
  3. downscaling: interpola i campi sulla griglia fine e li corregge con la quota
       temperatura  -6.5 C/km
       punto di rugiada  -1.8 C/km
       vento 10 m   piu' forte in quota
  4. disegna 2 immagini verticali, pensate per essere lette da smartphone

Uso:
  python previsioni_castelli.py                  dati reali (serve internet)
  python previsioni_castelli.py --simula         dati INVENTATI, per provare codice e grafica
  python previsioni_castelli.py --ora 30         2 immagini di dettaglio (con i paesi) a +30 h da adesso
  python previsioni_castelli.py --modello icon_d2

Senza --ora crea un'immagine per variabile (temperatura a 2 m e a 850 hPa, vento medio, raffiche,
pioggia 1/3/6 ore, pressione, umidita', CAPE) con un riquadro ogni 6 ore sulle prossime 48 ore.

Dipendenze:  pip install numpy scipy matplotlib requests
"""
import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.patches import Ellipse
from matplotlib.ticker import MaxNLocator
from scipy.interpolate import RectBivariateSpline

# ----------------------------------------------------------------------------
# Dominio: ~40x40 km attorno ai Castelli Romani
# ----------------------------------------------------------------------------
LAT0, LON0 = 41.71, 12.73
MEZZO_LAT, MEZZO_LON = 0.18, 0.24
LAT_MIN, LAT_MAX = LAT0 - MEZZO_LAT, LAT0 + MEZZO_LAT
LON_MIN, LON_MAX = LON0 - MEZZO_LON, LON0 + MEZZO_LON
N_GROSSA = 7          # punti per lato della griglia del modello
ORE = 49              # ora 0 + 48 ore
PASSATO = 5           # ore passate scaricate solo per le somme della pioggia (3 e 6 ore)
GRAD_T = 0.0065       # C/m
GRAD_TD = 0.0018      # C/m

# Metti qui le coordinate esatte della tua stazione
STAZIONE = ("Velletri", 41.686, 12.778)
PAESI = [
    ("Frascati", 41.807, 12.681),
    ("Marino", 41.768, 12.664),
    ("Rocca di Papa", 41.763, 12.713),
    ("Nemi", 41.723, 12.712),
    ("Lanuvio", 41.677, 12.698),
]
LAGHI = [  # nome, lat, lon, raggio in gradi lat, raggio in gradi lon (schematici)
    ("Albano", 41.748, 12.667, 0.0126, 0.0169),
    ("Nemi", 41.7227, 12.7138, 0.0072, 0.0097),
]

# Palette di base (stessi colori in tutte le mappe, una tinta per variabile)
SFONDO, INK, SEC, TENUE, LINEA = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
ARANCIO, VIOLA, VERDE = "#eb6834", "#6250d6", "#008300"
BLU, AQUA, ROSSO = "#2a78d6", "#1baf7a", "#e34948"
MAGENTA = "#d55181"

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
PUNTI = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def griglia_grossa():
    return np.linspace(LAT_MIN, LAT_MAX, N_GROSSA), np.linspace(LON_MIN, LON_MAX, N_GROSSA)


def griglia_fine(n):
    return np.linspace(LAT_MIN, LAT_MAX, n), np.linspace(LON_MIN, LON_MAX, n)


# ----------------------------------------------------------------------------
# Dati reali: Open-Meteo (gratuito, nessuna chiave)
# ----------------------------------------------------------------------------
URL_PREVISIONI = "https://api.open-meteo.com/v1/forecast"
URL_QUOTE = "https://api.open-meteo.com/v1/elevation"
CACHE = Path(".cache_open_meteo")
URL_VICINE = "https://api.weather.com/v3/location/near"
URL_STAZIONE = "https://api.weather.com/v2/pws/observations/current"
SEGRETI = []          # chiavi API da nascondere nei messaggi d'errore
_sessione = None      # una connessione riusata è più stabile di tante nuove
VARIABILI = ("temperature_2m,dew_point_2m,pressure_msl,precipitation,wind_speed_10m,wind_direction_10m,cape,"
             "wind_gusts_10m,temperature_850hPa")


def _lista(valori):
    return ",".join(f"{v:.4f}" for v in valori)


def _pulisci(testo):
    """Toglie le chiavi API dai messaggi d'errore (le URL le contengono)."""
    for s in SEGRETI:
        testo = testo.replace(s, "***")
    return re.sub(r"apiKey=[^&\s'\"]+", "apiKey=***", testo)


def _get(url, params, tentativi=5):
    """GET con pazienza: se Open-Meteo risponde 429 (troppe richieste) o 5xx aspetta e riprova."""
    global _sessione
    import requests

    for i in range(tentativi):
        try:
            if _sessione is None:
                _sessione = requests.Session()
            r = _sessione.get(url, params=params, timeout=60)
        except requests.exceptions.ConnectionError:
            _sessione = None
            if i == tentativi - 1:
                raise
            attesa = 5 * (i + 1)
            print(f"Connessione fallita, riprovo tra {attesa} s...", file=sys.stderr)
            time.sleep(attesa)
            continue
        if "weather.com" in url:
            time.sleep(2.1)                      # Wunderground: massimo 30 richieste al minuto
        if r.status_code in (429, 500, 502, 503, 504) and i < tentativi - 1:
            attesa = int(r.headers.get("Retry-After", 0) or 0) or 15 * (i + 1)
            print(f"Il servizio risponde {r.status_code}, riprovo tra {attesa} s...", file=sys.stderr)
            time.sleep(attesa)
            continue
        r.raise_for_status()
        return r


def _get_json(url, params, validita):
    """Come _get ma salva la risposta in .cache_open_meteo/ per `validita` secondi."""
    firma = params if isinstance(params, str) else repr(sorted(params.items()))
    chiave = hashlib.md5((url + firma).encode()).hexdigest()
    f = CACHE / f"{chiave}.json"
    if f.exists() and time.time() - f.stat().st_mtime < validita:
        return json.loads(f.read_text())
    dati = _get(url, params).json()
    CACHE.mkdir(exist_ok=True)
    f.write_text(json.dumps(dati))
    return dati


def scarica_open_meteo(modello):
    import requests

    lat_c, lon_c = griglia_grossa()
    LA, LO = np.meshgrid(lat_c, lon_c, indexing="ij")
    la, lo = LA.ravel(), LO.ravel()
    risposta = []
    for i in range(0, la.size, 50):                    # a pacchetti: con centinaia di punti una sola richiesta è troppo pesante
        params = {
            "latitude": _lista(la[i:i + 50]),
            "longitude": _lista(lo[i:i + 50]),
            "hourly": VARIABILI,
            "wind_speed_unit": "ms",
            "timezone": "Europe/Rome",
            "forecast_hours": ORE,
            "past_hours": PASSATO,
            "models": modello,
        }
        r = _get_json(URL_PREVISIONI, params, validita=1800)
        risposta.extend([r] if isinstance(r, dict) else r)
        time.sleep(1.0)

    tempi = [datetime.fromisoformat(s) for s in risposta[0]["hourly"]["time"]]
    nt = len(tempi)

    def campo(nome):
        a = np.full((nt, N_GROSSA, N_GROSSA), np.nan)
        for i, loc in enumerate(risposta):
            a[:, i // N_GROSSA, i % N_GROSSA] = np.array(loc["hourly"][nome], dtype=float)
        return a

    z_c = np.array([loc["elevation"] for loc in risposta], dtype=float).reshape(N_GROSSA, N_GROSSA)
    vel, direz = campo("wind_speed_10m"), np.radians(campo("wind_direction_10m"))
    cape = campo("cape")
    if np.isnan(cape).all():
        print("Attenzione: questo modello non fornisce il CAPE, uso 0.", file=sys.stderr)
    d = {
        "tempi": tempi, "lat_c": lat_c, "lon_c": lon_c, "z_c": z_c,
        "T": campo("temperature_2m"), "Td": campo("dew_point_2m"),
        "p": campo("pressure_msl"), "P": np.nan_to_num(campo("precipitation")),
        "u": -vel * np.sin(direz), "v": -vel * np.cos(direz),
        "cape": np.nan_to_num(cape),
    }
    for k in ("T", "Td", "p", "u", "v"):
        if np.isnan(d[k]).any():
            raise ValueError(f"dati incompleti per '{k}' (prova un altro --modello)")
    for nome, chiave in (("wind_gusts_10m", "G"), ("temperature_850hPa", "T850")):
        a = campo(nome)
        d[chiave] = None if np.isnan(a).any() else a
        if d[chiave] is None:
            print(f"Attenzione: questo modello non fornisce '{nome}': quella mappa verrà saltata.", file=sys.stderr)
    d["P3"], d["P6"] = somma_mobile(d["P"], 3), somma_mobile(d["P"], 6)
    # si parte dall'ora corrente: le ore passate servivano solo per le somme della pioggia
    adesso = datetime.now().replace(minute=0, second=0, microsecond=0)
    i0 = next((i for i, t in enumerate(tempi) if t >= adesso), 0)
    fisse = ("lat_c", "lon_c", "z_c")
    return {k: (v[i0:] if k not in fisse and isinstance(v, (list, np.ndarray)) else v) for k, v in d.items()}


def quote_reali(lat_f, lon_f):
    import requests

    LA, LO = np.meshgrid(lat_f, lon_f, indexing="ij")
    la, lo = LA.ravel(), LO.ravel()
    out = []
    for i in range(0, la.size, 40):                    # richieste corte: quelle lunghe a volte vengono scartate
        params = ("latitude=" + ",".join(f"{v:.3f}" for v in la[i:i + 40])
                  + "&longitude=" + ",".join(f"{v:.3f}" for v in lo[i:i + 40]))
        out.extend(_get_json(URL_QUOTE, params, validita=30 * 86400)["elevation"])
        time.sleep(0.5)
    return np.array(out, dtype=float).reshape(LA.shape)


# ----------------------------------------------------------------------------
# Stazioni Weather Underground: la "situazione attuale" per correggere il modello
# La chiave si legge dalla variabile d'ambiente WU_API_KEY (mai scritta nei file)
# ----------------------------------------------------------------------------
def cerca_stazioni(chiave, per_lato=5):
    """Ogni ricerca restituisce al massimo 10 stazioni: si ripete da una griglia di punti."""
    trovate = {}
    for la in np.linspace(LAT_MIN + 0.04, LAT_MAX - 0.04, per_lato):
        for lo in np.linspace(LON_MIN + 0.05, LON_MAX - 0.05, per_lato):
            p = {"geocode": f"{la:.4f},{lo:.4f}", "product": "pws", "format": "json", "apiKey": chiave}
            try:
                loc = _get_json(URL_VICINE, p, validita=86400)["location"]       # elenco valido 1 giorno
            except (KeyError, ValueError):
                continue
            for sid, sla, slo in zip(loc["stationId"], loc["latitude"], loc["longitude"]):
                if sid and LAT_MIN <= sla <= LAT_MAX and LON_MIN <= slo <= LON_MAX:
                    trovate[sid] = (float(sla), float(slo))
    return trovate


def diradamento(stazioni, massimo):
    """Se sono troppe ne tiene `massimo`, il più possibile distanziate tra loro."""
    ids = list(stazioni)
    if len(ids) <= massimo:
        return ids
    k = 111.32
    xy = {i: ((stazioni[i][1] - LON0) * k * np.cos(np.radians(LAT0)), (stazioni[i][0] - LAT0) * k) for i in ids}
    scelte = [min(ids, key=lambda i: np.hypot(*xy[i]))]
    dmin = {i: np.hypot(xy[i][0] - xy[scelte[0]][0], xy[i][1] - xy[scelte[0]][1]) for i in ids}
    while len(scelte) < massimo:
        nuovo = max((i for i in ids if i not in scelte), key=lambda i: dmin[i])
        scelte.append(nuovo)
        for i in ids:
            dmin[i] = min(dmin[i], np.hypot(xy[i][0] - xy[nuovo][0], xy[i][1] - xy[nuovo][1]))
    return scelte


def leggi_stazioni(chiave, ids):
    """Ultima osservazione di ogni stazione (risposta tenuta in cache per 5 minuti)."""
    import requests

    oss = {}
    for sid in ids:
        p = {"stationId": sid, "format": "json", "units": "m", "numericPrecision": "decimal", "apiKey": chiave}
        try:
            o = _get_json(URL_STAZIONE, p, validita=300)["observations"][0]
            m = o["metric"]
            oss[sid] = {
                "lat": float(o["lat"]), "lon": float(o["lon"]), "quota": m.get("elev"),
                "ora": datetime.strptime(o["obsTimeLocal"], "%Y-%m-%d %H:%M:%S"),
                "T": m.get("temp"), "Td": m.get("dewpt"),
            }
        except (KeyError, IndexError, ValueError, TypeError, requests.RequestException):
            continue                                   # stazione senza dati o che non risponde
    return oss


def _filtra(valori):
    """Maschera dei valori non anomali: scarto dalla mediana entro max(3 MAD, 2.5)."""
    v = np.asarray(valori, float)
    if v.size >= 5:
        med = np.median(v)
        mad = 1.4826 * np.median(np.abs(v - med))
        return np.abs(v - med) <= max(3 * mad, 2.5)
    return np.abs(v) <= 6


def correggi_con_stazioni(c, tempi, oss, z_f, lat_f, lon_f, scala_km=5.0, lam=0.25, tau_h=6.0):
    """
    Confronta le stazioni con il modello già adattato al terreno e corregge temperatura e umidità.
    Controlli: dato recente (max 30 min), valori plausibili, posizione dentro il dominio,
    quota dichiarata coerente col terreno (max 200 m), scarto dal modello non anomalo rispetto alle altre.
    La correzione si spande attorno alle stazioni (scala 5 km) e si smorza in circa 6 ore.
    """
    nt = c["T"].shape[0]
    adesso = datetime.now()
    sp = lambda campo: RectBivariateSpline(lat_f, lon_f, campo, kx=1, ky=1)
    sp_z = sp(z_f)
    buone = {}
    for sid, o in oss.items():
        if o["T"] is None or o["Td"] is None:
            continue
        if not (timedelta(minutes=-10) <= adesso - o["ora"] <= timedelta(minutes=30)):
            continue
        if not (-30 < o["T"] < 50) or o["Td"] < -40:
            continue
        if not (LAT_MIN <= o["lat"] <= LAT_MAX and LON_MIN <= o["lon"] <= LON_MAX):
            continue
        if o["quota"] is not None and abs(float(o["quota"]) - float(sp_z.ev(o["lat"], o["lon"]))) > 200:
            continue                                   # posizione o quota incoerenti
        k = int(np.clip(round((o["ora"] - tempi[0]).total_seconds() / 3600), 0, nt - 1))
        o["rT"] = o["T"] - float(sp(c["T"][k]).ev(o["lat"], o["lon"]))
        o["rTd"] = min(o["Td"], o["T"]) - float(sp(c["Td"][k]).ev(o["lat"], o["lon"]))
        buone[sid] = o

    info = {"n": 0, "testo": "", "nota": ""}
    ids = list(buone)
    ids_T = [i for i, f in zip(ids, _filtra([buone[i]["rT"] for i in ids])) if f] if len(ids) >= 3 else []
    ids_Td = [i for i, f in zip(ids, _filtra([buone[i]["rTd"] for i in ids])) if f] if len(ids) >= 3 else []
    if len(ids_T) < 3:
        info["testo"] = (f"Stazioni: {len(oss)} lette, {len(ids)} recenti e coerenti, {len(ids_T)} attendibili: "
                         "troppo poche, nessuna correzione.")
        return c, info

    LON, LAT = np.meshgrid(lon_f, lat_f)
    km = 111.32
    X, Y = (LON - LON0) * km * np.cos(np.radians(LAT0)), (LAT - LAT0) * km

    def analisi(sel, chiave):
        num, den = np.zeros_like(X), np.zeros_like(X)
        for i in sel:
            xs = (buone[i]["lon"] - LON0) * km * np.cos(np.radians(LAT0))
            ys = (buone[i]["lat"] - LAT0) * km
            w = np.exp(-((X - xs) ** 2 + (Y - ys) ** 2) / (2 * scala_km ** 2))
            num += w * buone[i][chiave]
            den += w
        return num / (den + lam)

    corr_T = analisi(ids_T, "rT")
    corr_Td = analisi(ids_Td, "rTd") if len(ids_Td) >= 3 else np.zeros_like(X)
    t_rif = max(buone[i]["ora"] for i in ids_T)
    fatt = np.array([np.exp(-max(0.0, (t - t_rif).total_seconds() / 3600) / tau_h) for t in tempi])[:, None, None]

    out = dict(c)
    out["T"] = c["T"] + fatt * corr_T
    out["Td"] = np.minimum(c["Td"] + fatt * corr_Td, out["T"] - 0.1)
    out["RH"] = umidita_relativa(out["T"], out["Td"])
    bias = float(np.mean([buone[i]["rT"] for i in ids_T]))
    info["n"] = len(ids_T)
    info["testo"] = (f"Stazioni: {len(oss)} lette, {len(ids)} recenti e coerenti, {len(ids_T)} usate dopo il "
                     f"controllo qualità; scarto medio stazioni − modello {bias:+.1f} °C (ore {t_rif:%H:%M}).")
    info["nota"] = (f"Temperatura e umidità corrette con {len(ids_T)} stazioni Wunderground alle {t_rif:%H:%M} "
                    f"(scarto medio {bias:+.1f} °C), correzione smorzata in circa {tau_h:.0f} h; "
                    "vento e pioggia non corretti.")
    return out, info


# ----------------------------------------------------------------------------
# Dati INVENTATI (solo per --simula): terreno e "modello" finti ma plausibili
# ----------------------------------------------------------------------------
def dem_simulato(lat, lon):
    """Terreno inventato: vulcano laziale, laghi nei crateri, piana che sale verso est."""
    lat, lon = np.broadcast_arrays(np.asarray(lat, float), np.asarray(lon, float))

    def gauss(la, lo, h, sla, slo):
        return h * np.exp(-(((lat - la) / sla) ** 2 + ((lon - lo) / slo) ** 2) / 2)

    z = 40 + 220 * np.clip((lon - LON_MIN) / (LON_MAX - LON_MIN), 0, 1)
    z = z + gauss(41.755, 12.71, 760, 0.065, 0.085)
    z = z + gauss(41.86, 12.95, 480, 0.05, 0.06)
    z = z + gauss(41.64, 12.90, 250, 0.05, 0.06)
    z = z - gauss(41.748, 12.667, 380, 0.011, 0.015)
    z = z - gauss(41.7227, 12.7138, 330, 0.008, 0.011)
    z = z + 25 * np.sin(lat * 190) * np.cos(lon * 230) + 18 * np.sin(lat * 210 + 1) * np.sin(lon * 260)
    return np.clip(z, 0, None)


def dati_simulati(ora0):
    lat_c, lon_c = griglia_grossa()
    LA, LO = np.meshgrid(lat_c, lon_c, indexing="ij")
    z_c = dem_simulato(LA, LO)
    tempi = [ora0 + timedelta(hours=h) for h in range(ORE)]
    t = np.arange(ORE, dtype=float)[:, None, None]
    h = np.array([x.hour + x.minute / 60 for x in tempi])[:, None, None]
    LA3, LO3 = LA[None], LO[None]
    x = (LO3 - LON_MIN) / (LON_MAX - LON_MIN)

    # Temperatura e rugiada ridotte al livello del mare, poi portate alla quota del punto
    T_mare = 17.0 + 5.0 * (1 + 0.35 * x) * np.cos(2 * np.pi * (h - 15) / 24) - 0.06 * t
    Td_mare = np.minimum(10.5 + 0.045 * t + 0.8 * (1 - x), T_mare - 0.3)
    T = T_mare - GRAD_T * z_c[None]
    Td = Td_mare - GRAD_TD * z_c[None]

    # Pressione al livello del mare: scende per l'arrivo di una perturbazione
    p = 1016.8 - 0.14 * t + 1.2 * (x - 0.5)

    # Vento: brezza di mare da OSO di giorno, brezza di terra da NE di notte
    w = np.clip(0.5 + 0.6 * np.sin(2 * np.pi * (h - 10) / 24), 0, 1)
    pre = 1 + 0.7 * t / 48
    vs, vl = 4.0 * (1.25 - 0.5 * x) * pre, 1.6 * pre
    ds, dl = np.radians(240), np.radians(40)
    u = w * (-vs * np.sin(ds)) + (1 - w) * (-vl * np.sin(dl))
    v = w * (-vs * np.cos(ds)) + (1 - w) * (-vl * np.cos(dl))

    # Pioggia: celle temporalesche che attraversano il dominio verso ENE il secondo pomeriggio
    def cella(tc, intensita, dla=0.0, dlo=0.0):
        la_c = 41.65 + 0.010 * (t - 28) + dla
        lo_c = 12.49 + 0.045 * (t - 28) + dlo
        spazio = np.exp(-(((LA3 - la_c) / 0.07) ** 2 + ((LO3 - lo_c) / 0.09) ** 2) / 2)
        return intensita * np.exp(-(((t - tc) / 2.8) ** 2)) * spazio

    P = cella(33, 14) + cella(34, 7, 0.11, -0.10) + 0.25 * np.exp(-(((t - 27) / 4) ** 2)) * (1 + 0.3 * x)

    # CAPE: ciclo giornaliero, piu' alto il secondo giorno
    ampiezza = 250 + 900 / (1 + np.exp(-(t - 24) / 6))
    forma = np.maximum(0, np.cos(2 * np.pi * (h - 15) / 24)) ** 2
    zona_calda = np.exp(-(((LA3 - 41.66) / 0.09) ** 2 + ((LO3 - 12.62) / 0.12) ** 2) / 2)
    cape = np.clip(ampiezza * forma * (1.15 - 0.3 * x + 0.35 * zona_calda) + 20, 0, 1500)

    G = 1.0 + 1.7 * np.hypot(u, v)
    T850 = 11.0 - 0.07 * t + 0.4 * (x - 0.5) + 0.45 * np.cos(2 * np.pi * (h - 15) / 24)
    return {"tempi": tempi, "lat_c": lat_c, "lon_c": lon_c, "z_c": z_c,
            "T": T, "Td": Td, "p": p, "P": P, "u": u, "v": v, "cape": cape,
            "G": G, "T850": T850, "P3": somma_mobile(P, 3), "P6": somma_mobile(P, 6)}


# ----------------------------------------------------------------------------
# Downscaling: dalla griglia grossa a quella fine, con correzione di quota
# ----------------------------------------------------------------------------
def interpola(campo, lat_c, lon_c, lat_f, lon_f, ordine=3):
    out = np.empty((campo.shape[0], lat_f.size, lon_f.size))
    for i in range(campo.shape[0]):
        out[i] = RectBivariateSpline(lat_c, lon_c, campo[i], kx=ordine, ky=ordine)(lat_f, lon_f)
    return out


def umidita_relativa(T, Td):
    a, b = 17.625, 243.04
    return np.clip(100 * np.exp(a * Td / (b + Td) - a * T / (b + T)), 0, 100)


def downscaling(d, z_f, lat_f, lon_f):
    lc, oc, zc = d["lat_c"], d["lon_c"], d["z_c"][None]

    def it(campo, ordine=3):
        return interpola(campo, lc, oc, lat_f, lon_f, ordine)

    z_visto = it(zc)[0]                                   # quota "vista" dal modello sulla griglia fine
    T = it(d["T"] + GRAD_T * zc) - GRAD_T * z_f           # via dal mare e di nuovo alla quota vera
    Td = np.minimum(it(d["Td"] + GRAD_TD * zc) - GRAD_TD * z_f, T - 0.1)
    fattore = np.clip(1 + 0.0004 * (z_f - z_visto), 0.8, 1.7)
    u, v = it(d["u"]) * fattore, it(d["v"]) * fattore
    G = d.get("G")
    if G is not None:
        G = np.maximum(it(G) * fattore, np.hypot(u, v))      # la raffica non è mai sotto il vento medio
    T850 = d.get("T850")
    return {
        "T": T,
        "Td": Td,
        "RH": umidita_relativa(T, Td),
        "T850": None if T850 is None else it(T850),          # a 850 hPa (~1500 m) il terreno non conta
        "p": it(d["p"]),
        "u": u,
        "v": v,
        "G": G,
        "P": np.clip(it(d["P"], 1), 0, None),
        "P3": np.clip(it(d["P3"], 1), 0, None),
        "P6": np.clip(it(d["P6"], 1), 0, None),
        "cape": np.clip(it(d["cape"], 1), 0, None),
    }


# ----------------------------------------------------------------------------
# Grafica
# ----------------------------------------------------------------------------
def _mix(c1, c2, f):
    return tuple(np.array(to_rgb(c1)) * (1 - f) + np.array(to_rgb(c2)) * f)


def rampa(base):
    """Una sola tinta, dal chiaro (vicino allo sfondo) allo scuro."""
    return LinearSegmentedColormap.from_list("r", [_mix(base, "#ffffff", 0.78), base, _mix(base, "#000000", 0.55)])


def etichetta(dt):
    return f"{GIORNI[dt.weekday()]} {dt.day} {MESI[dt.month - 1]}, {dt:%H:%M}"


def nome_direzione(u, v):
    gradi = np.degrees(np.arctan2(-u, -v)) % 360     # direzione di provenienza
    return PUNTI[int((gradi + 22.5) // 45) % 8]


def livelli(campo, n=9, span_min=0.0, massimo=None):
    lo, hi = float(campo.min()), float(campo.max())
    if hi - lo < span_min:
        m = (hi + lo) / 2
        lo, hi = m - span_min / 2, m + span_min / 2
    lv = MaxNLocator(nbins=n).tick_values(lo, hi)
    if massimo is not None:
        lv = np.unique(np.clip(lv, None, massimo))
    return lv


def decora(ax, z_f, lat_f, lon_f):
    halo = [pe.withStroke(linewidth=3, foreground=SFONDO)]
    ax.contour(lon_f, lat_f, z_f, levels=np.arange(200, 1200, 200), colors=TENUE,
               linewidths=0.6, alpha=0.8, zorder=2)
    for _, la, lo, rla, rlo in LAGHI:
        ax.add_patch(Ellipse((lo, la), 2 * rlo, 2 * rla, fc="#cde2fb", ec=BLU, lw=0.8, zorder=5))
    for nome, la, lo in PAESI:
        ax.plot(lo, la, "o", ms=4, color=INK, mec=SFONDO, mew=0.8, zorder=7)
        ax.text(lo + 0.007, la, nome, fontsize=11, color=INK, va="center", zorder=7, path_effects=halo)
    nome, la, lo = STAZIONE
    ax.plot(lo, la, "*", ms=13, color=INK, mec=SFONDO, mew=0.8, zorder=8)
    ax.text(lo + 0.009, la - 0.008, nome, fontsize=10.5, weight="bold", color=INK, va="center",
            zorder=8, path_effects=halo)
    x0, y0 = LON_MIN + 0.02, LAT_MIN + 0.02
    lung = 10 / (111.32 * np.cos(np.radians(LAT0)))
    ax.plot([x0, x0 + lung], [y0, y0], color=INK, lw=2.5, zorder=8, solid_capstyle="butt")
    ax.text(x0 + lung / 2, y0 + 0.008, "10 km", fontsize=9.5, ha="center", color=INK, zorder=8, path_effects=halo)


def disegna_mappe(c, z_f, lat_f, lon_f, k, tempi, titolo_banner, modello_txt, out, sim):
    LON, LAT = np.meshgrid(lon_f, lat_f)
    iy = int(np.abs(lat_f - STAZIONE[1]).argmin())
    ix = int(np.abs(lon_f - STAZIONE[2]).argmin())

    u, v = c["u"] * 3.6, c["v"] * 3.6                        # km/h
    vel_tot = np.hypot(u, v)
    T, RH, p, P, C = c["T"][k], c["RH"][k], c["p"][k], c["P"][k], c["cape"][k]
    uk, vk, vel = u[k], v[k], vel_tot[k]
    st = lambda a: float(a[iy, ix])                          # valore alla stazione

    def p_temp(ax):
        cs = ax.contourf(LON, LAT, T, levels=livelli(T), cmap=rampa(ARANCIO), zorder=1)
        return cs, None

    def p_vento(ax):
        cs = ax.contourf(LON, LAT, vel, levels=livelli(vel, span_min=6), cmap=rampa(VIOLA), zorder=1)
        s = max(1, len(lon_f) // 10)
        rif = 10 if vel.max() < 20 else 20                 # lunghezza della freccia di riferimento
        q = ax.quiver(LON[::s, ::s], LAT[::s, ::s], uk[::s, ::s], vk[::s, ::s], color=INK, angles="uv",
                      scale=220 * rif / 20, scale_units="width", width=0.006, zorder=6)
        ax.quiverkey(q, 0.70, 0.07, rif, f"{rif} km/h", labelpos="E", coordinates="axes",
                     fontproperties={"size": 10}, labelcolor=INK)
        return cs, None

    def p_press(ax):
        lv = livelli(p, n=8, span_min=1.5)
        cs = ax.contourf(LON, LAT, p, levels=lv, cmap=rampa(VERDE), zorder=1)
        iso = ax.contour(LON, LAT, p, levels=lv, colors=INK, linewidths=0.7, zorder=3)
        try:
            ax.clabel(iso, fmt="%.1f", fontsize=9)
        except Exception:
            pass
        return cs, None

    def p_pioggia(ax):
        if P.max() < 0.1:
            ax.text(0.62, 0.12, "Nessuna pioggia\nprevista a quest'ora", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color=SEC)
            return None, None
        liv = [0.1, 0.5, 1, 2, 4, 8, 16, 32]
        cols = rampa(BLU)(np.linspace(0.18, 1, len(liv)))
        cs = ax.contourf(LON, LAT, P, levels=liv, colors=list(cols[:-1]), extend="max", zorder=1)
        cs.cmap.set_over(cols[-1])
        cs.changed()
        return cs, liv

    def p_umid(ax):
        cs = ax.contourf(LON, LAT, RH, levels=livelli(RH, n=8, massimo=100), cmap=rampa(AQUA), zorder=1)
        return cs, None

    def p_cape(ax):
        if C.max() < 50:
            ax.text(0.62, 0.12, "Instabilità trascurabile\n(CAPE sotto 50 J/kg)", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color=SEC)
            return None, None
        liv = [50] + list(range(100, 1600, 100))          # fasce da 100 J/kg: si vede il gradiente
        cols = rampa(ROSSO)(np.linspace(0.18, 1, len(liv)))
        cs = ax.contourf(LON, LAT, C, levels=liv, colors=list(cols[:-1]), extend="max", zorder=1)
        cs.cmap.set_over(cols[-1])
        cs.changed()
        return cs, [100, 300, 500, 700, 900, 1100, 1300, 1500]

    pannelli = {
        "temp": ("Temperatura a 2 m (°C)",
                 f"min {T.min():.1f} · max {T.max():.1f}   |   {STAZIONE[0]} {st(T):.1f} °C", p_temp),
        "vento": ("Vento a 10 m (km/h)",
                  f"max {vel.max():.0f}   |   {STAZIONE[0]} {st(vel):.0f} da {nome_direzione(st(uk), st(vk))}", p_vento),
        "press": ("Pressione al livello del mare (hPa)",
                  f"{p.min():.1f}–{p.max():.1f}   |   {STAZIONE[0]} {st(p):.1f}", p_press),
        "pioggia": ("Pioggia oraria (mm/h)",
                    f"max {P.max():.1f}   |   {STAZIONE[0]} {st(P):.1f} mm/h", p_pioggia),
        "umid": ("Umidità relativa (%)",
                 f"min {RH.min():.0f} · max {RH.max():.0f}   |   {STAZIONE[0]} {st(RH):.0f} %", p_umid),
        "cape": ("Instabilità, CAPE (J/kg)",
                 f"max {C.max():.0f}   |   {STAZIONE[0]} {st(C):.0f} J/kg", p_cape),
    }

    # Riepilogo 48 h alla stazione
    Ts, Ps = c["T"][:, iy, ix], c["P"][:, iy, ix]
    riep1 = (f"{STAZIONE[0]}, prossime {len(tempi) - 1} h:  T {Ts.min():.0f}–{Ts.max():.0f} °C"
             f" · pioggia {Ps.sum():.0f} mm · vento max {vel_tot[:, iy, ix].max():.0f} km/h")
    riep2 = (f"umidità min {c['RH'][:, iy, ix].min():.0f}% · CAPE max {c['cape'][:, iy, ix].max():.0f} J/kg"
             f" · pressione {c['p'][0, iy, ix]:.0f} → {c['p'][-1, iy, ix]:.0f} hPa")

    gruppi = [
        ("1/2", ["temp", "vento", "press"], "castelli_1_temp_vento_pressione.png"),
        ("2/2", ["pioggia", "umid", "cape"], "castelli_2_pioggia_umidita_cape.png"),
    ]
    def testo_note(sigla):
        note = ["Linee grigie: quota ogni 200 m. Laghi e posizioni dei paesi sono schematici.", modello_txt,
                "Non sostituisce le previsioni ufficiali."]
        if sigla == "2/2":
            note.insert(1, "CAPE alto = ambiente favorevole ai temporali, non una certezza.")
        return "\n".join(textwrap.fill(r, 74) for r in note)

    righe_note = max(testo_note(s).count("\n") + 1 for s in ("1/2", "2/2"))
    W, HEAD, MAPPA, BLOCCO = 6.4, 2.4, 5.4, 6.95
    FOOT = 0.35 + 0.19 * righe_note                      # il piede cresce con la lunghezza delle note
    H = HEAD + 3 * BLOCCO + FOOT
    fx, fy = (lambda xi: xi / W), (lambda yi: 1 - yi / H)
    file_out = []

    for sigla, chiavi, nome_file in gruppi:
        fig = plt.figure(figsize=(W, H), facecolor=SFONDO)
        fig.text(fx(0.5), fy(0.45), f"Castelli Romani · {sigla}", fontsize=20, weight="bold", color=INK, va="center")
        fig.text(fx(0.5), fy(0.88), f"+{k} h · {etichetta(tempi[k])}", fontsize=14, color=SEC, va="center")
        fig.text(fx(0.5), fy(1.35), titolo_banner, fontsize=12, weight="bold", color=INK, va="center",
                 bbox=dict(boxstyle="round,pad=0.45", fc="#ffffff", ec=INK, lw=1.2))
        fig.text(fx(0.5), fy(1.88), riep1, fontsize=11, color=SEC, va="center")
        fig.text(fx(0.5), fy(2.12), riep2, fontsize=11, color=SEC, va="center")

        for j, chiave in enumerate(chiavi):
            titolo, sotto, disegna = pannelli[chiave]
            top = HEAD + j * BLOCCO
            fig.text(fx(0.5), fy(top + 0.30), titolo, fontsize=15, weight="bold", color=INK, va="center")
            fig.text(fx(0.5), fy(top + 0.58), sotto, fontsize=12, color=SEC, va="center")
            ax = fig.add_axes([fx(0.5), fy(top + 0.75 + MAPPA), fx(MAPPA), MAPPA / H])
            ax.set_facecolor(SFONDO)
            ax.set_xlim(LON_MIN, LON_MAX)
            ax.set_ylim(LAT_MIN, LAT_MAX)
            ax.set_aspect(1 / np.cos(np.radians(LAT0)))
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color(LINEA)
            cs, ticks = disegna(ax)
            decora(ax, z_f, lat_f, lon_f)
            if cs is not None:
                cax = fig.add_axes([fx(0.5), fy(top + 0.75 + MAPPA + 0.38), fx(MAPPA), 0.16 / H])
                cb = fig.colorbar(cs, cax=cax, orientation="horizontal")
                if ticks is not None:
                    cb.set_ticks(ticks)
                cb.ax.tick_params(labelsize=12, colors=SEC, length=3)
                cb.outline.set_visible(False)

        testo = testo_note(sigla)
        fig.text(fx(0.5), fy(HEAD + 3 * BLOCCO + 0.05), testo, fontsize=9.5, color=SEC, va="top", linespacing=1.4)

        percorso = Path(out) / nome_file
        fig.savefig(percorso, dpi=140, facecolor=SFONDO)
        plt.close(fig)
        file_out.append(percorso)
    return file_out


def somma_mobile(P, n):
    """Somma delle n ore che finiscono a ogni istante (all'inizio, solo le ore disponibili)."""
    cum = np.cumsum(P, axis=0)
    out = cum.copy()
    out[n:] = cum[n:] - cum[:-n]
    return out


def definisci_fogli(c):
    kmh = 3.6
    G = c.get("G")
    return [
        dict(nome="temperatura_2m", titolo="Temperatura a 2 m", unita="°C", dati=c["T"], colore=ARANCIO,
             fmt="{:.0f}", span=4),
        dict(nome="temperatura_850", titolo="Temperatura a 850 hPa", unita="°C", dati=c.get("T850"),
             colore=MAGENTA, fmt="{:.0f}", span=4, nota="circa 1500 m di quota"),
        dict(nome="vento_medio", titolo="Vento medio a 10 m", unita="km/h", dati=np.hypot(c["u"], c["v"]) * kmh,
             colore=VIOLA, fmt="{:.0f}", span=10, frecce=(c["u"] * kmh, c["v"] * kmh),
             nota="frecce: verso dove soffia"),
        dict(nome="raffiche", titolo="Raffiche a 10 m", unita="km/h", dati=None if G is None else G * kmh,
             colore=VIOLA, fmt="{:.0f}", span=15),
        dict(nome="pioggia_1h", titolo="Pioggia nell'ultima ora", unita="mm", dati=c["P"], colore=BLU,
             fmt="{:.1f}", livelli=[0.1, 0.5, 1, 2, 4, 8, 16, 32]),
        dict(nome="pioggia_3h", titolo="Pioggia nelle ultime 3 ore", unita="mm", dati=c["P3"], colore=BLU,
             fmt="{:.1f}", livelli=[0.2, 1, 2, 5, 10, 20, 40, 80]),
        dict(nome="pioggia_6h", titolo="Pioggia nelle ultime 6 ore", unita="mm", dati=c["P6"], colore=BLU,
             fmt="{:.1f}", livelli=[0.5, 2, 5, 10, 20, 40, 80, 160]),
        dict(nome="pressione", titolo="Pressione al livello del mare", unita="hPa", dati=c["p"], colore=VERDE,
             fmt="{:.0f}", span=4),
        dict(nome="umidita", titolo="Umidità relativa", unita="%", dati=c["RH"], colore=AQUA, fmt="{:.0f}",
             span=15, massimo=100),
        dict(nome="cape", titolo="Instabilità (CAPE)", unita="J/kg", dati=c["cape"], colore=ROSSO, fmt="{:.0f}",
             livelli=[50, 100, 200, 300, 500, 750, 1000, 1500]),
    ]


def disegna_fogli(c, z_f, lat_f, lon_f, tempi, banner, modello_txt, out):
    """Un'immagine per variabile: 9 riquadri, uno ogni 6 ore, tutti con la stessa scala di colori."""
    idx = list(range(0, len(tempi), 6))[:9]
    LON, LAT = np.meshgrid(lon_f, lat_f)
    iy = int(np.abs(lat_f - STAZIONE[1]).argmin())
    ix = int(np.abs(lon_f - STAZIONE[2]).argmin())
    halo = [pe.withStroke(linewidth=2.5, foreground=SFONDO)]
    asciutto = float(c["P6"].max()) < 0.1

    fogli = []
    for f in definisci_fogli(c):
        if f["dati"] is None:
            print(f"Salto «{f['titolo']}»: questo modello non fornisce il dato.", file=sys.stderr)
        elif f["nome"].startswith("pioggia") and asciutto:
            if f["nome"] == "pioggia_1h":
                fogli.append(dict(nome="pioggia", vuoto=True))      # niente pioggia: un solo foglio, senza riquadri
        else:
            fogli.append(f)

    W, SIDE, GAP, MARG, ETICH, HEAD, CB = 6.4, 1.88, 0.08, 0.3, 0.34, 1.55, 0.95
    PASSO = SIDE + ETICH + 0.06
    righe_tile = -(-len(idx) // 3)
    wrap = lambda righe: "\n".join(textwrap.fill(r, 74) for r in righe)
    testo = wrap(["★ = Velletri: il suo valore è scritto in basso a destra di ogni riquadro.",
                  "Stessi colori in tutti i riquadri; linee grigie: quota ogni 200 m.", modello_txt,
                  "Non sostituisce le previsioni ufficiali."])
    testo_secco = wrap([modello_txt, "Non sostituisce le previsioni ufficiali."])
    foot = lambda t: 0.3 + 0.19 * (t.count("\n") + 1)
    simulato = "SIMULAZIONE" in banner

    def intestazione(fig, H, titolo, sotto):
        fig.text(MARG / W, 1 - 0.40 / H, titolo, fontsize=16, weight="bold", color=INK, va="center")
        fig.text(MARG / W, 1 - 0.80 / H, sotto, fontsize=11, color=SEC, va="center")
        if simulato:
            fig.text(MARG / W, 1 - 1.20 / H, banner, fontsize=11, weight="bold", color=INK, va="center",
                     bbox=dict(boxstyle="round,pad=0.4", fc="#ffffff", ec=INK, lw=1.2))
        else:
            fig.text(MARG / W, 1 - 1.20 / H, banner, fontsize=10.5, color=SEC, va="center")

    creati = []
    for n, f in enumerate(fogli, start=1):
        percorso = Path(out) / f"{n:02d}_{f['nome']}.png"

        if f.get("vuoto"):
            H = 2.9 + foot(testo_secco)
            fig = plt.figure(figsize=(W, H), facecolor=SFONDO)
            intestazione(fig, H, "Pioggia nelle prossime 48 ore", "ultima ora, 3 ore e 6 ore")
            fig.text(MARG / W, 1 - 1.85 / H, "Nessuna pioggia prevista", fontsize=15, weight="bold", color=INK, va="center")
            fig.text(MARG / W, 1 - 2.30 / H,
                     f"Massimo sul dominio: {c['P'].max():.1f} mm in 1 ora, {c['P6'].max():.1f} mm in 6 ore.",
                     fontsize=11, color=SEC, va="center")
            fig.text(MARG / W, 1 - 2.95 / H, testo_secco, fontsize=9.5, color=SEC, va="top", linespacing=1.4)
            fig.savefig(percorso, dpi=150, facecolor=SFONDO)
            plt.close(fig)
            creati.append(percorso)
            continue

        dati = np.asarray(f["dati"], float)
        sel = dati[idx]
        cmap = rampa(f["colore"])
        if "livelli" in f:
            liv = list(f["livelli"])
            cols = list(cmap(np.linspace(0.18, 1, len(liv))))
        else:
            liv = livelli(sel, n=8, span_min=f.get("span", 3.0), massimo=f.get("massimo"))
            cols = None

        def riempi(ax, campo):
            if cols is None:
                return ax.contourf(LON, LAT, campo, levels=liv, cmap=cmap, zorder=1)
            if campo.max() < liv[0]:
                return None
            cs = ax.contourf(LON, LAT, campo, levels=liv, colors=cols[:-1], extend="max", zorder=1)
            cs.cmap.set_over(cols[-1])
            cs.changed()
            return cs

        H = HEAD + righe_tile * PASSO + CB + foot(testo)
        fig = plt.figure(figsize=(W, H), facecolor=SFONDO)
        sotto = f"ogni 6 ore da {GIORNI[tempi[0].weekday()]} {tempi[0]:%H:%M}"
        if f.get("nota"):
            sotto += " · " + f["nota"]
        intestazione(fig, H, f"{f['titolo']} ({f['unita']})", sotto)

        frecce = f.get("frecce")
        if frecce is not None:
            scala = max(float(sel.max()), 10.0) / 0.18          # la freccia più lunga misura 0.18 della larghezza
            s = max(1, len(lon_f) // 5)
            o = s // 2

        for i, k in enumerate(idx):
            r, col = divmod(i, 3)
            x0 = MARG + col * (SIDE + GAP)
            alto = HEAD + r * PASSO + ETICH
            ax = fig.add_axes([x0 / W, 1 - (alto + SIDE) / H, SIDE / W, SIDE / H])
            ax.set_facecolor(SFONDO)
            ax.set_xlim(LON_MIN, LON_MAX)
            ax.set_ylim(LAT_MIN, LAT_MAX)
            ax.set_aspect(1 / np.cos(np.radians(LAT0)))
            ax.set_xticks([])
            ax.set_yticks([])
            for sp_ in ax.spines.values():
                sp_.set_color(LINEA)
            riempi(ax, dati[k])
            ax.contour(lon_f, lat_f, z_f, levels=np.arange(200, 1200, 200), colors=TENUE,
                       linewidths=0.4, alpha=0.8, zorder=2)
            if frecce is not None:
                ax.quiver(LON[o::s, o::s], LAT[o::s, o::s], frecce[0][k][o::s, o::s], frecce[1][k][o::s, o::s],
                          color=INK, angles="uv", scale=scala, scale_units="width", width=0.012, zorder=6)
            ax.plot(STAZIONE[2], STAZIONE[1], "*", ms=8, color=INK, mec=SFONDO, mew=0.6, zorder=8)
            ax.text(0.96, 0.04, f["fmt"].format(dati[k][iy, ix]), transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=11, weight="bold", color=INK, zorder=9, path_effects=halo)
            fig.text(x0 / W, 1 - (alto - 0.05) / H, f"{GIORNI[tempi[k].weekday()]} {tempi[k]:%H:%M} · +{k} h",
                     fontsize=10.5, weight="bold", color=INK, va="bottom")

        # barra dei colori: stessi livelli dei riquadri, disegnata su un asse nascosto
        asse = fig.add_axes([0, 0, 0.01, 0.01])
        asse.set_visible(False)
        ref = np.linspace(liv[0], liv[-1] * (1.5 if cols is not None else 1.0), LON.size).reshape(LON.shape)
        cs = riempi(asse, ref)
        y_cb = HEAD + righe_tile * PASSO + 0.35
        cax = fig.add_axes([(W - 5.0) / 2 / W, 1 - (y_cb + 0.17) / H, 5.0 / W, 0.17 / H])
        cb = fig.colorbar(cs, cax=cax, orientation="horizontal")
        if cols is not None:
            cb.set_ticks(liv)
        cb.ax.tick_params(labelsize=11, colors=SEC, length=3)
        cb.outline.set_visible(False)

        fig.text(MARG / W, 1 - (HEAD + righe_tile * PASSO + CB + 0.05) / H, testo, fontsize=9.5, color=SEC,
                 va="top", linespacing=1.4)
        fig.savefig(percorso, dpi=150, facecolor=SFONDO)
        plt.close(fig)
        creati.append(percorso)
    return creati


def main():
    ap = argparse.ArgumentParser(description="Mappe meteo 48 h sui Castelli Romani")
    ap.add_argument("--simula", action="store_true", help="usa dati inventati invece di Open-Meteo")
    ap.add_argument("--modello", default="best_match",
                    help="modello Open-Meteo (es. italia_meteo_arpae_icon_2i = ICON-2I a ~2 km, icon_eu, ecmwf_ifs025)")
    ap.add_argument("--grossa", type=int, default=0,
                    help="punti per lato con cui si legge il modello (0 = automatico: 19, uno ogni ~2 km, "
                         "per i modelli a 2 km; 7 per gli altri)")
    ap.add_argument("--ora", type=int, default=None, help="se indicato, 2 immagini di dettaglio (con i paesi) a quell'ora (0-48)")
    ap.add_argument("--n", type=int, default=40, help="punti per lato della griglia fine (default 40, ~1 km)")
    ap.add_argument("--inizio", default=None, help="solo con --simula: ora di partenza ISO, es. 2026-10-16T08:00")
    ap.add_argument("--out", default="output", help="cartella di destinazione delle immagini")
    ap.add_argument("--senza-stazioni", action="store_true", help="non usare le stazioni Wunderground")
    ap.add_argument("--max-stazioni", type=int, default=60, help="massimo di stazioni Wunderground da leggere")
    a = ap.parse_args()

    global N_GROSSA
    if a.grossa:
        N_GROSSA = a.grossa
    elif not a.simula and any(s in a.modello for s in ("icon_2i", "icon_d2", "arome")):
        N_GROSSA = 19                      # un punto ogni ~2,2 km su 40 km: tutto il dettaglio del modello

    Path(a.out).mkdir(parents=True, exist_ok=True)
    lat_f, lon_f = griglia_fine(a.n)
    passo_km = 2 * MEZZO_LAT * 111.32 / (a.n - 1)
    passo_modello_km = 2 * MEZZO_LAT * 111.32 / (N_GROSSA - 1)

    if a.simula:
        ora0 = datetime.fromisoformat(a.inizio) if a.inizio else datetime.now().replace(minute=0, second=0, microsecond=0)
        d = dati_simulati(ora0)
        z_f = dem_simulato(*np.meshgrid(lat_f, lon_f, indexing="ij"))
        banner = "SIMULAZIONE: DATI INVENTATI, NON È UNA PREVISIONE"
        modello_txt = "Campi e terreno generati al computer per provare codice e grafica."
    else:
        try:
            import requests
        except ImportError:
            sys.exit("Manca il modulo requests:  pip install requests")
        try:
            d = scarica_open_meteo(a.modello)
        except (requests.RequestException, KeyError, ValueError) as e:
            sys.exit("Impossibile scaricare i dati: " + _pulisci(str(e)))
        try:
            z_f = quote_reali(lat_f, lon_f)
            quote_ok = True
        except (requests.RequestException, KeyError, ValueError) as e:
            print("Quote del terreno non scaricabili, uso quelle interpolate dal modello:",
                  _pulisci(str(e))[:120], file=sys.stderr)
            z_f = np.clip(interpola(d["z_c"][None], d["lat_c"], d["lon_c"], lat_f, lon_f)[0], 0, None)
            quote_ok = False
        banner = f"Dati reali Open-Meteo · modello {a.modello}"
        modello_txt = (f"Griglia a {passo_km:.1f} km; il modello è letto ogni {passo_modello_km:.1f} km, "
                       "i dettagli più fini vengono dalla correzione di quota "
                       "(T −6,5 °C/km, rugiada −1,8 °C/km, vento più forte in quota).")
        if not quote_ok:
            modello_txt += " Quote del terreno approssimate: i dettagli del rilievo sono meno fedeli."

    tempi = d["tempi"]
    campi = downscaling(d, z_f, lat_f, lon_f)

    if not a.simula and not a.senza_stazioni:
        chiave = os.environ.get("WU_API_KEY")
        if chiave:
            SEGRETI.append(chiave)
            try:
                scelte = diradamento(cerca_stazioni(chiave), a.max_stazioni)
                campi, info = correggi_con_stazioni(campi, tempi, leggi_stazioni(chiave, scelte), z_f, lat_f, lon_f)
                print(info["testo"])
                if info["n"] >= 3:
                    banner = f"Open-Meteo ({a.modello}) + {info['n']} stazioni WU"
                    modello_txt += " " + info["nota"]
            except Exception as e:                     # la correzione è facoltativa
                print("Stazioni Wunderground non disponibili:", _pulisci(str(e)), file=sys.stderr)
        else:
            print("Nessuna WU_API_KEY impostata: salto la correzione con le stazioni.", file=sys.stderr)
    if a.ora is None:
        creati = disegna_fogli(campi, z_f, lat_f, lon_f, tempi, banner, modello_txt, a.out)
    else:
        k = max(0, min(a.ora, len(tempi) - 1))
        creati = disegna_mappe(campi, z_f, lat_f, lon_f, k, tempi, banner, modello_txt, a.out, a.simula)
    for f in creati:
        print("Creato:", f)


if __name__ == "__main__":
    main()
