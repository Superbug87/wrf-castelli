# WRF sui Castelli Romani

Previsione a 48 ore con **WRF** (modello fisico vero) su tre domini annidati centrati sui Castelli Romani
(41,71 N, 12,73 E): **9 km → 3 km → 1 km**. Parte dai dati globali GFS 0,25° e gira da sola ogni giorno sui
server gratuiti di GitHub. Alla fine disegna le stesse mappe di `previsioni_castelli.py`
(temperatura a 2 m e 850 hPa, vento medio, raffiche, pioggia 1/3/6 h, pressione, umidità, CAPE),
una ogni 6 ore, e le pubblica nel ramo `risultati`.

## Prima di cominciare
- Il repository deve essere **pubblico**: i server sono da 4 processori e i minuti sono illimitati.
  In un repository privato i server hanno 2 processori e 2000 minuti al mese: non bastano.
- Facoltativo: la chiave Wunderground per correggere temperatura e umidità con le stazioni.
  Su GitHub: *Settings → Secrets and variables → Actions → New repository secret*, nome `WU_API_KEY`.

## Come si avvia (anche da telefono)
1. App GitHub (o sito) → il repository → **Actions** → **Previsione WRF Castelli Romani** → **Run workflow**.
2. Campi: `ciclo` (vuoto = l'ultimo GFS completo), `ore` (default 48), `ore_segmento` (default 16).
3. Poi parte da sola ogni giorno alle 05:10 UTC (con il ciclo GFS delle 00 UTC).

Tempi **stimati** (non ancora misurati):

| fase | quando | durata |
|---|---|---|
| compilazione di WRF e WPS | solo la prima volta | 40-90 min |
| dati statici (terreno, uso del suolo) | solo la prima volta | 30-60 min |
| scarico GFS, ungrib, metgrid, real | ogni giorno | 15-25 min |
| WRF, 3 segmenti da 16 h in fila | ogni giorno | 2-2,5 h ciascuno |
| mappe e pubblicazione | ogni giorno | 5 min |

GitHub ferma ogni job dopo 6 ore, per questo la previsione è divisa in segmenti che ripartono dal *restart*
del precedente. Se i segmenti vanno stretti, abbassa `ore_segmento` (massimo 4 segmenti) o `ore`.

## Dove trovo i risultati
- Ramo **`risultati`** del repository: la cartella `ultimo/` e il suo `README.md` con tutte le immagini
  (si legge bene dall'app GitHub). In `archivio/` ci sono gli ultimi 14 giorni.
- In *Actions → l'esecuzione → Artifacts*: `mappe` (le immagini) e, se qualcosa va storto, i log.

## Cosa fa e cosa non fa
- WRF è alimentato solo dal GFS. Le **stazioni Wunderground non entrano dentro WRF**: dopo il calcolo
  correggono temperatura e umidità (scarto medio delle stazioni sensate, che si smorza in circa 6 ore).
  Assimilarle nel modello (WRFDA) è un lavoro a parte.
- **Raffiche = stima**: massimo orario del vento a 10 m (diagnostica di WRF) × 1,4.
- **CAPE = stima** da parcella di superficie. Controllata contro MetPy su 5 profili: scarti sotto l'1%.
- Il GFS ha punti ogni 25 km: l'1 km viene da WRF e dall'orografia, non dal dato di partenza.
- Non sostituisce le previsioni ufficiali.

## Stato del collaudo
Provato davvero (in un ambiente senza compilatore Fortran):
namelist (letti da f90nml, domini annidati verificati), scelta del ciclo GFS e percorsi/dimensioni dei file su AWS,
CAPE contro MetPy, mappe a partire da file `wrfout` inventati con la stessa struttura di WRF, pubblicazione
nel ramo `risultati`, sintassi del workflow (actionlint) e degli script (shellcheck).

**Non provato:** compilazione di WRF e WPS, download dei dati geografici NCAR, geogrid, real.exe, wrf.exe.
Il primo avvio potrebbe richiedere qualche correzione: i log escono come artifact.

## File
- `.github/workflows/wrf.yml` — il flusso automatico
- `wrf/dominio.py` — geometria dei tre domini · `wrf/config.py` — namelist di WPS e WRF
- `wrf/dipendenze.sh`, `costruisci.sh`, `statico.sh`, `esegui.sh`, `pubblica.sh`
- `wrf/scarica_gfs.py` — scarico dei file GFS · `wrf/postprocess.py` — da `wrfout` alle mappe
- `wrf/prova_sintetica.py` — file `wrfout` inventati per collaudare le mappe senza WRF
- `previsioni_castelli.py` — mappe e correzione con le stazioni (usato da `postprocess.py`)
