#!/usr/bin/env python3
"""
Quota 30 m e uso del suolo 10 m per geogrid.

Di serie WPS usa quota GMTED2010 a circa 900 m e uso del suolo MODIS a 500 m: troppo grossolani per un dominio a 1 km.
Questo script scarica solo la zona che serve e la scrive nel formato binario a tasselli che geogrid legge:

  quota        Copernicus DEM GLO-30 (AWS, 1 arcsec)        ->  <geog>/topo_cop30/
  uso suolo    ESA WorldCover 2021 (AWS, 10 m), tradotto nelle 21 classi MODIS di WRF  ->  <geog>/landuse_worldcover/

  dati_fini.py --out "$GEOG_PATH"          # scarica e scrive
  dati_fini.py --prova                     # collaudo senza rete (dati inventati)

Poi si usa geog_data_res = 'fine+default' (config.py wps --res fine+default) e una GEOGRID.TBL con le righe `fine:`
(`ritocca_tabella`): dove i dati fini non ci sono (fuori dal riquadro) geogrid usa quelli di serie.
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

# Quota: riquadro del dominio a 3 km (162 km) più circa 25 km di margine. Multipli esatti dei tasselli (0,2 gradi).
DEM_LAT0, DEM_LAT1 = 40.7, 42.7
DEM_LON0, DEM_LON1 = 11.4, 14.0
DEM_PIX = 3600                    # punti per grado (1 arcsec)
DEM_TASSELLO = 720                # punti per lato dei tasselli di geogrid (0,2 gradi)
DEM_SCALA = 0.1                   # i metri si salvano in decimi (interi a 16 bit)

# Suolo: dominio a 1 km (60 km) più margine. Tasselli di 0,1 gradi.
LU_LAT0, LU_LAT1 = 41.3, 42.1
LU_LON0, LU_LON1 = 12.2, 13.3
LU_PIX = 12000                    # punti per grado (10 m)
LU_TASSELLO = 1200

URL_DEM = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM.tif")
URL_WC = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_N{la:02d}E{lo:03d}_Map.tif")

# ESA WorldCover -> MODIS a 21 classi usate da WRF (17 = mare, 21 = lago)
WC_A_MODIS = {10: 5, 20: 6, 30: 10, 40: 12, 50: 13, 60: 16, 70: 15, 80: 17, 90: 11, 95: 2, 100: 20}


# ---------------------------------------------------------------------------------------------
# Scrittura nel formato di geogrid
# ---------------------------------------------------------------------------------------------
def scrivi_dataset(cartella, mat, lat0, lon0, pix, tassello, categorico, descrizione, unita, scala=None, mancante=None):
    """
    mat: matrice (righe dal SUD al NORD, colonne da OVEST a EST), già multipla del tassello.
    lat0, lon0: bordo sud-ovest. pix: punti per grado.
    """
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    ny, nx = mat.shape
    assert ny % tassello == 0 and nx % tassello == 0, "la matrice deve essere multipla del tassello"
    dx = 1.0 / pix
    if categorico:
        tipo, parola, firma = "<u1", 1, False
        mancante = 0 if mancante is None else mancante
    else:
        tipo, parola, firma = "<i2", 2, True
        mancante = -32768 if mancante is None else mancante
    righe = [
        f"type = {'categorical' if categorico else 'continuous'}",
        "projection = regular_ll",
        f"dx = {dx:.12f}",
        f"dy = {dx:.12f}",
        "known_x = 1.0",
        "known_y = 1.0",
        f"known_lat = {lat0 + dx / 2:.12f}",
        f"known_lon = {lon0 + dx / 2:.12f}",
        f"wordsize = {parola}",
        "endian = little",
        f"tile_x = {tassello}",
        f"tile_y = {tassello}",
        "tile_z = 1",
        "tile_bdr = 0",
        f"missing_value = {mancante}",
        f"units = \"{unita}\"",
        f"description = \"{descrizione}\"",
    ]
    if categorico:
        righe += ["category_min = 1", "category_max = 21"]
    else:
        righe += ["signed = yes"]
        if scala:
            righe += [f"scale_factor = {scala}"]
    (cartella / "index").write_text("\n".join(righe) + "\n")
    for ty in range(ny // tassello):
        for tx in range(nx // tassello):
            blocco = mat[ty * tassello:(ty + 1) * tassello, tx * tassello:(tx + 1) * tassello]
            nome = f"{tx * tassello + 1:05d}-{(tx + 1) * tassello:05d}.{ty * tassello + 1:05d}-{(ty + 1) * tassello:05d}"
            (cartella / nome).write_bytes(np.ascontiguousarray(blocco, dtype=tipo).tobytes())
    return ny // tassello * (nx // tassello)


def leggi_dataset(cartella):
    """Rilegge un dataset scritto sopra (per i collaudi). Ritorna (matrice dal sud, dizionario dell'indice)."""
    cartella = Path(cartella)
    ind = {}
    for riga in (cartella / "index").read_text().splitlines():
        if "=" in riga:
            k, v = riga.split("=", 1)
            ind[k.strip()] = v.strip().strip('"')
    t = int(ind["tile_x"])
    parola = int(ind["wordsize"])
    tipo = {1: "<u1", 2: "<i2"}[parola]
    nx = ny = 0
    pezzi = {}
    for f in cartella.iterdir():
        m = re.fullmatch(r"(\d{5})-(\d{5})\.(\d{5})-(\d{5})", f.name)
        if m:
            x0, x1, y0, y1 = map(int, m.groups())
            pezzi[(x0, y0)] = np.frombuffer(f.read_bytes(), dtype=tipo).reshape(y1 - y0 + 1, x1 - x0 + 1)
            nx, ny = max(nx, x1), max(ny, y1)
    mat = np.zeros((ny, nx), dtype=tipo)
    for (x0, y0), b in pezzi.items():
        mat[y0 - 1:y0 - 1 + b.shape[0], x0 - 1:x0 - 1 + b.shape[1]] = b
    return mat, ind


# ---------------------------------------------------------------------------------------------
# Conversioni
# ---------------------------------------------------------------------------------------------
def classi_modis(wc):
    """Matrice di classi WorldCover -> classi MODIS; l'acqua più grande è mare (17), il resto laghi (21)."""
    out = np.zeros(wc.shape, np.uint8)
    for k, v in WC_A_MODIS.items():
        out[wc == k] = v
    out[out == 0] = 17                                           # senza dato: acqua
    acqua = out == 17
    if acqua.any():
        from scipy import ndimage
        etichette, n = ndimage.label(acqua)
        if n > 1:
            aree = np.bincount(etichette.ravel())
            aree[0] = 0
            mare = int(aree.argmax())
            out[acqua & (etichette != mare)] = 21
        # una sola massa d'acqua: se è piccola (< 20 km2, cioè 200000 punti a 10 m) è un lago
        elif acqua.sum() < 200000:
            out[acqua] = 21
    return out


def scarica_dem():
    import rasterio
    ny = round((DEM_LAT1 - DEM_LAT0) * DEM_PIX)
    nx = round((DEM_LON1 - DEM_LON0) * DEM_PIX)
    mat = np.zeros((ny, nx), np.float32)
    mancanti = 0
    totali = 0
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for la in range(int(np.floor(DEM_LAT0)), int(np.ceil(DEM_LAT1))):
            for lo in range(int(np.floor(DEM_LON0)), int(np.ceil(DEM_LON1))):
                totali += 1
                url = "/vsicurl/" + URL_DEM.format(la=la, lo=lo)
                try:
                    with rasterio.open(url) as s:
                        assert s.width == DEM_PIX and s.height == DEM_PIX, (s.width, s.height)
                        # parte del grado dentro il riquadro
                        a0, a1 = max(la, DEM_LAT0), min(la + 1, DEM_LAT1)
                        o0, o1 = max(lo, DEM_LON0), min(lo + 1, DEM_LON1)
                        r0 = round((la + 1 - a1) * DEM_PIX)
                        r1 = round((la + 1 - a0) * DEM_PIX)
                        c0 = round((o0 - lo) * DEM_PIX)
                        c1 = round((o1 - lo) * DEM_PIX)
                        blocco = s.read(1, window=((r0, r1), (c0, c1))).astype(np.float32)
                        if s.nodata is not None:
                            blocco[blocco == s.nodata] = 0
                except Exception as e:                           # tessera di solo mare: non esiste
                    print(f"  quota N{la} E{lo}: assente ({str(e)[:70]}), uso 0 m", file=sys.stderr)
                    mancanti += 1
                    continue
                # in `mat` le righe vanno dal sud: la prima riga del blocco è la più a nord
                y_nord = round((a1 - DEM_LAT0) * DEM_PIX)
                x_ovest = round((o0 - DEM_LON0) * DEM_PIX)
                mat[y_nord - blocco.shape[0]:y_nord, x_ovest:x_ovest + blocco.shape[1]] = blocco[::-1]
                print(f"  quota N{la} E{lo}: ok {blocco.shape}", flush=True)
    if mancanti > totali // 2:
        sys.exit(f"!! Troppe tessere di quota assenti ({mancanti} su {totali})")
    return mat


def scarica_suolo():
    import rasterio
    ny = round((LU_LAT1 - LU_LAT0) * LU_PIX)
    nx = round((LU_LON1 - LU_LON0) * LU_PIX)
    mat = np.zeros((ny, nx), np.uint8)
    letti = 0
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for la in sorted({int(np.floor(x / 3)) * 3 for x in (LU_LAT0, LU_LAT1 - 1e-6)}):
            for lo in sorted({int(np.floor(x / 3)) * 3 for x in (LU_LON0, LU_LON1 - 1e-6)}):
                a0, a1 = max(la, LU_LAT0), min(la + 3, LU_LAT1)
                o0, o1 = max(lo, LU_LON0), min(lo + 3, LU_LON1)
                url = "/vsicurl/" + URL_WC.format(la=la, lo=lo)
                with rasterio.open(url) as s:
                    assert s.width == 36000 and s.height == 36000, (s.width, s.height)
                    r0 = round((la + 3 - a1) * LU_PIX)
                    r1 = round((la + 3 - a0) * LU_PIX)
                    c0 = round((o0 - lo) * LU_PIX)
                    c1 = round((o1 - lo) * LU_PIX)
                    blocco = s.read(1, window=((r0, r1), (c0, c1)))
                y_nord = round((a1 - LU_LAT0) * LU_PIX)
                x_ovest = round((o0 - LU_LON0) * LU_PIX)
                mat[y_nord - blocco.shape[0]:y_nord, x_ovest:x_ovest + blocco.shape[1]] = blocco[::-1]
                letti += 1
                print(f"  suolo N{la} E{lo}: ok {blocco.shape}", flush=True)
    if not letti:
        sys.exit("!! Nessuna tessera di uso del suolo")
    return mat


def scrivi_tutto(out, dem, wc):
    n1 = scrivi_dataset(Path(out) / "topo_cop30", np.clip(np.rint(np.maximum(dem, 0) / DEM_SCALA), 0, 32767),
                        DEM_LAT0, DEM_LON0, DEM_PIX, DEM_TASSELLO, False,
                        "Copernicus DEM GLO-30 (Castelli Romani)", "meters MSL", scala=DEM_SCALA)
    modis = classi_modis(wc)
    n2 = scrivi_dataset(Path(out) / "landuse_worldcover", modis, LU_LAT0, LU_LON0, LU_PIX, LU_TASSELLO, True,
                        "ESA WorldCover 2021 tradotto in classi MODIS (Castelli Romani)", "category")
    return n1, n2, modis


# ---------------------------------------------------------------------------------------------
# GEOGRID.TBL: aggiunge la risoluzione «fine» a quota e uso del suolo
# ---------------------------------------------------------------------------------------------
def ritocca_tabella(testo):
    """Aggiunge a HGT_M e LANDUSEF le righe `fine:` (rel_path, interp_option, landmask_water). Ritorna il testo nuovo."""
    blocchi = re.split(r"(?m)^(={5,}\s*)$", testo)
    out = []
    fatti = set()
    for b in blocchi:
        m = re.search(r"(?m)^\s*name\s*=\s*(\w+)", b)
        nome = m.group(1) if m else None
        if nome == "HGT_M":
            b = _inserisci(b, "interp_option", "        interp_option = fine:average_gcell(4.0)+four_pt+average_4pt")
            b = _inserisci(b, "rel_path", "        rel_path = fine:topo_cop30/")
            fatti.add(nome)
        elif nome == "LANDUSEF":
            b = _inserisci(b, "landmask_water", "        landmask_water = fine:17,21")
            b = _inserisci(b, "interp_option", "        interp_option = fine:average_gcell(0.0)")
            b = _inserisci(b, "rel_path", "        rel_path = fine:landuse_worldcover/")
            fatti.add(nome)
        out.append(b)
    if fatti != {"HGT_M", "LANDUSEF"}:
        sys.exit(f"!! GEOGRID.TBL: non trovo i blocchi HGT_M e LANDUSEF (trovati: {sorted(fatti)})")
    return "".join(out)


def _inserisci(blocco, chiave, riga):
    """Mette `riga` subito prima della prima riga che comincia con `chiave`."""
    righe = blocco.split("\n")
    for i, r in enumerate(righe):
        if re.match(rf"\s*{chiave}\s*=", r):
            righe.insert(i, riga)
            return "\n".join(righe)
    sys.exit(f"!! GEOGRID.TBL: manca `{chiave}` in un blocco")


# ---------------------------------------------------------------------------------------------
# Collaudo senza rete
# ---------------------------------------------------------------------------------------------
def prova():
    with tempfile.TemporaryDirectory() as tmp:
        rng = np.random.default_rng(3)
        ny, nx = 2 * DEM_TASSELLO, 3 * DEM_TASSELLO
        dem = rng.uniform(0, 900, (ny, nx)).astype(np.float32)
        wc = np.zeros((2 * LU_TASSELLO, 2 * LU_TASSELLO), np.uint8)
        wc[:] = 30
        wc[:400, :] = 80                                          # mare grande (tocca il bordo)
        wc[1500:1600, 1500:1560] = 80                             # lago piccolo
        wc[1000:1100, 100:300] = 50
        wc[2000:2100, 2000:2100] = 10
        wc[1200:1230, 600:640] = 40
        # le funzioni di scrittura lavorano con le dimensioni del riquadro vero: provo scrivi_dataset direttamente
        scrivi_dataset(Path(tmp) / "q", np.rint(dem / DEM_SCALA), DEM_LAT0, DEM_LON0, DEM_PIX, DEM_TASSELLO, False,
                       "prova", "meters MSL", scala=DEM_SCALA)
        letta, ind = leggi_dataset(Path(tmp) / "q")
        assert letta.shape == dem.shape and np.array_equal(letta, np.rint(dem / DEM_SCALA).astype("<i2")), "quota diversa"
        assert float(ind["scale_factor"]) == DEM_SCALA and ind["endian"] == "little" and ind["type"] == "continuous"
        assert abs(float(ind["known_lat"]) - (DEM_LAT0 + 0.5 / DEM_PIX)) < 1e-12
        modis = classi_modis(wc)
        assert set(np.unique(modis).tolist()) == {5, 10, 12, 13, 17, 21}, np.unique(modis)
        assert (modis[:400] == 17).all() and (modis[1500:1600, 1500:1560] == 21).all(), "mare/lago"
        scrivi_dataset(Path(tmp) / "s", modis, LU_LAT0, LU_LON0, LU_PIX, LU_TASSELLO, True, "prova", "category")
        letta, ind = leggi_dataset(Path(tmp) / "s")
        assert np.array_equal(letta, modis) and ind["type"] == "categorical" and ind["category_max"] == "21"
        nomi = sorted(p.name for p in (Path(tmp) / "s").iterdir())
        assert "00001-01200.00001-01200" in nomi and "index" in nomi and len(nomi) == 5, nomi
        # orientazione: la riga 0 della matrice è il bordo SUD
        piccola = np.zeros((LU_TASSELLO, LU_TASSELLO), np.uint8)
        piccola[0, 0] = 7
        scrivi_dataset(Path(tmp) / "o", piccola, 0, 0, LU_PIX, LU_TASSELLO, True, "x", "x")
        b = (Path(tmp) / "o" / "00001-01200.00001-01200").read_bytes()
        assert b[0] == 7 and len(b) == LU_TASSELLO ** 2

    tbl = """# commento
===============================
name = HGT_M
        priority = 1
        interp_option = default:average_gcell(4.0)+four_pt+average_4pt
        rel_path = default:topo_gmted2010_30s/
===============================
name=LANDUSEF
        priority=1
        landmask_water =        default:17,21      # x
        interp_option =        default:nearest_neighbor
        rel_path =        default:modis_landuse_20class_30s_with_lakes/
===============================
name = ALTRO
        rel_path = default:altro/
"""
    nuovo = ritocca_tabella(tbl)
    for riga in ("rel_path = fine:topo_cop30/", "rel_path = fine:landuse_worldcover/", "landmask_water = fine:17,21",
                 "interp_option = fine:average_gcell(0.0)", "interp_option = fine:average_gcell(4.0)+four_pt+average_4pt"):
        assert riga in nuovo, riga
    assert nuovo.count("fine:") == 5 and "altro/" in nuovo and "fine:altro" not in nuovo
    print("dati_fini: prova ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="cartella dei dati geografici (WPS_GEOG)")
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--tabella", help="GEOGRID.TBL da ritoccare (riscritta sul posto)")
    a = ap.parse_args()
    if a.prova:
        prova()
        return
    if a.tabella:
        p = Path(a.tabella)
        p.write_text(ritocca_tabella(p.read_text()))
        print(f"{p}: aggiunte le righe `fine:`")
        if not a.out:
            return
    if not a.out:
        ap.error("serve --out")
    print("Quota Copernicus 30 m...", flush=True)
    dem = scarica_dem()
    print(f"  quota: {dem.shape}, min {dem.min():.0f} max {dem.max():.0f} m", flush=True)
    print("Uso del suolo WorldCover 10 m...", flush=True)
    wc = scarica_suolo()
    n1, n2, modis = scrivi_tutto(a.out, dem, wc)
    classi = dict(zip(*np.unique(modis, return_counts=True)))
    tot = modis.size
    print(f"Scritti {n1} tasselli di quota e {n2} di suolo in {a.out}")
    print("  suolo (classi MODIS): " + ", ".join(f"{int(k)}:{v / tot:.1%}" for k, v in classi.items()))


if __name__ == "__main__":
    main()
