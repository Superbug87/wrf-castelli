# WRF sui Castelli Romani

Previsione a 48 ore con **WRF** (modello fisico vero) su tre domini annidati centrati sui Castelli Romani
(41,71 N, 12,73 E): **9 km → 3 km → 1 km**. Parte dai dati aperti di **ECMWF** (IFS 0,25°; GFS è l'alternativa) e gira da sola ogni giorno sui
server gratuiti di GitHub. Alla fine disegna le stesse mappe di `previsioni_castelli.py`
(30 tipi: temperatura a 2 m, 925 e 850 hPa, zero termico, umidità, vento medio, raffiche, pioggia 1/3/6/12/24 h,
neve 6/24 h, pressione, nuvolosità totale/bassa/media/alta, CAPE (parcella più instabile e strato mescolato), CIN, shear 0-1/0-3/0-6 km,
elicità 0-1/0-3 km, rischio fulmini, rischio supercelle, rischio tornado), una ogni 6 ore, e le pubblica nel ramo `risultati`.

## Avvertenze
- **Progetto personale e sperimentale, non un servizio ufficiale.** Le previsioni sono prodotte in automatico da un modello
  numerico, senza il controllo di un meteorologo, e possono essere sbagliate, anche di molto. Per pioggia e temporali
  posizione e orario possono sbagliare di chilometri e di ore.
- **Non sostituiscono i bollettini e le allerte ufficiali** (Protezione Civile, Aeronautica Militare, centri funzionali
  regionali). Non usarle per decisioni che riguardano la sicurezza di persone o cose: protezione civile, volo,
  navigazione, lavori o eventi a rischio.
- **Nessuna garanzia.** Sono fornite «così come sono», senza garanzie di esattezza, continuità o disponibilità: il servizio
  può ritardare, fermarsi o dare errori. L'autore non risponde di danni derivanti dall'uso.
- **Nessun legame con i fornitori dei dati.** Il progetto non è collegato a ECMWF, NOAA, NCAR/UCAR, Weather Underground né
  agli altri fornitori elencati sotto e non è da loro approvato o rivisto.

## Prima di cominciare
- Il repository deve essere **pubblico** (lo è): i server sono da 4 processori e i minuti sono illimitati.
  In un repository privato i server hanno 2 processori e 2000 minuti al mese: non bastano.
- Facoltativo ma consigliato: la chiave Wunderground, per far entrare le stazioni dentro WRF (vedi sotto).
  Su GitHub: *Settings → Secrets and variables → Actions → New repository secret*, nome `WU_API_KEY`.

## Come si avvia (anche da telefono)
1. App GitHub (o sito) → il repository → **Actions** → **Previsione WRF Castelli Romani** → **Run workflow**.
2. Campi: `pilota` (`ecmwf` di default, oppure `gfs`), `ciclo` (vuoto = l'ultimo completo; per ECMWF solo le 00 e le 12 UTC),
   `ore` (default 48), `ore_segmento` (default 16), `stazioni` (nudging, sì di default), `mare` (temperatura del mare
   MUR a 1 km, sì di default), `radar` (confronto con il radar e pioggia delle prossime 3 ore, sì di default).
3. L'avvio automatico (riga `schedule` nel workflow) è attivo dopo la prima esecuzione completa riuscita (16 ottobre 2026): con ECMWF
   alle 08:40 UTC (ciclo delle 00 UTC, pubblicato verso le 07:35) e alle 20:10 UTC (ciclo delle 12 UTC, verso le 19:35).
   GitHub può ritardare di ore, o saltare, i lanci programmati (visto il 16 ottobre: lancio delle 19:50 partito alle 22:14), quindi ci sono
   anche due lanci di riserva (11:20 e 22:30 UTC) che non rifanno il ciclo se è già nel ramo `risultati`. I lanci a mano rifanno sempre.

Tempi **stimati** (non ancora misurati):

| fase | quando | durata |
|---|---|---|
| compilazione di WRF e WPS | solo la prima volta | 40-90 min |
| dati statici (terreno, uso del suolo) | solo la prima volta | 30-60 min |
| scarico ECMWF, ungrib, metgrid, real | ogni giorno | 10-20 min |
| WRF, 3 segmenti da 16 h in fila | ogni giorno | 2-2,5 h ciascuno |
| mappe e pubblicazione | ogni giorno | 5 min |

GitHub ferma ogni job dopo 6 ore, per questo la previsione è divisa in segmenti che ripartono dal *restart*
del precedente. Se i segmenti vanno stretti, abbassa `ore_segmento` (massimo 4 segmenti) o `ore`.

**La compilazione è a tappe** (`wrf/costruisci.sh prepara|wrf|wps|installa`, quattro passi del job `costruzione`):
- mentre WRF compila, il log scrive ogni 5 minuti a che punto è (oggetti compilati, ultimo file, carico, memoria);
- se in 30 minuti non cambia nulla (né file compilati né righe di log) un guardiano stampa quali processi sono rimasti
  appesi, salva la diagnosi (`diagnosi.txt`, tra gli allegati `log-compilazione`) e ferma il job invece di lasciarlo girare
  fino al limite;
- c'è un tempo massimo di 290 minuti per WRF: se scade, il sorgente parziale (con gli oggetti già compilati) va in cache
  e **rilanciando il flusso la compilazione riprende da lì**, senza ricominciare;
- la cache finale (`wrf-install`) si salva solo se tutte e quattro le tappe finiscono; quella parziale (`wrf-src`) si salva
  anche se si interrompe.

## Dove trovo i risultati
- Ramo **`risultati`** del repository: la cartella `ultimo/` e il suo `README.md` con tutte le immagini
  (si legge bene dall'app GitHub). In `archivio/` ci sono gli ultimi 14 cicli (una settimana).
- Stesso ramo, cartella **`orarie/`**: una immagine per ogni ora e per ogni tipo di mappa (solo tipo, ora del run e ora
  della mappa, senza descrizioni), degli ultimi 14 cicli (una settimana: 30 variabili x 49 ore a 64 colori, circa 60-100 KB l'una, circa 1 GB per i 14 cicli);
  `orarie/cicli.json` elenca i cicli presenti, `orarie/<ciclo>/indice.json` variabili e ore di ciascuno. Il ramo viene
  riscritto con un solo commit a ogni pubblicazione, così la storia non cresce.
- **Sul sito Meteo Velletri**: la pagina `sito/previsioni-wrf.html` (un solo file, senza dipendenze) sfoglia le immagini
  orarie: scelta del run (una settimana di previsioni), del tipo di mappa, cursore delle ore, scarico dell'immagine
  mostrata e della GIF dell'intero run (2 secondi a immagine, creata nel browser), tasto play, frecce, scorrimento col dito, salto al giorno.
  Va caricata sul sito (FTP) e legge le immagini direttamente da GitHub (`raw.githubusercontent.com`), che le tiene in
  cache circa 5 minuti: si aggiorna da sola quando esce un nuovo ciclo. Si può anche incorporare con un `<iframe>`.
  `sito/meteovelletri.html` è la pagina di Meteo Velletri con la sezione «Previsioni WRF» (iframe sulla pagina sopra).
  **Caricamento automatico (FTP)**: `.github/workflows/sito.yml` + `wrf/carica_sito.sh` caricano `previsioni-wrf.html`
  a ogni modifica; `meteovelletri.html` solo avviando il flusso a mano con la casella «anche_meteovelletri». Servono
  quattro segreti del repository (Settings → Secrets and variables → Actions): `FTP_HOST`, `FTP_USER`,
  `FTP_PASSWORD`, `FTP_CARTELLA` (es. `5archi`). Senza segreti il flusso non fa nulla.
- In *Actions → l'esecuzione → Artifacts*: `mappe` (le immagini) e, se qualcosa va storto, i log.

## Cosa fa e cosa non fa
- WRF è alimentato da un solo modello globale per volta (ECMWF o GFS).
- **Stazioni Wunderground dentro WRF (nudging).** Con la chiave `WU_API_KEY`, prima del calcolo si cercano le
  stazioni nei tre domini (fitte nel dominio a 1 km, fino a 40; 30 nel dominio a 3 km; 20 nel dominio a 9 km),
  se ne scarica lo storico delle ultime 24 ore, si controllano (valori plausibili, quota dichiarata coerente con il
  terreno del modello, scarto dalle stazioni vicine riportate alla stessa quota) e si mediano ogni 15 minuti.
  WRF, dall'inizio del ciclo fino all'ultima osservazione, spinge temperatura e umidità verso quei valori
  (raggio di influenza 100/50/25 km nei tre domini, tempo di rilassamento circa mezz'ora); poi prosegue libero
  dallo stato raggiunto. Il **vento delle stazioni non viene usato**: gli anemometri amatoriali sono quasi sempre
  riparati. Senza chiave o senza dati utili WRF gira senza nudging. In questo caso le mappe applicano come prima
  la correzione dopo il calcolo; con il nudging non si corregge una seconda volta.
  Limiti: i sensori amatoriali sono di qualità diversa (quelli al sole di giorno scaldano) e l'effetto sulle ore
  lontane dall'ultima osservazione è piccolo: il nudging migliora lo stato di partenza, non cancella gli errori del
  modello globale. Assimilare le stazioni con un'analisi vera (WRFDA) sarebbe un lavoro a parte.
- **Temperatura del mare.** ECMWF dà la temperatura del mare a 25 km. Per il mare si scarica l'analisi MUR SST di NASA JPL
  (circa 1 km, con 1-2 giorni di ritardo, tenuta costante per le 48 ore) e WRF la usa sui punti d'acqua al posto di quella del
  modello globale. I Castelli sono a circa 30 km dalla costa: il guadagno riguarda soprattutto la fascia costiera e le brezze.
  Se il servizio non risponde, WRF gira lo stesso con la temperatura del mare del modello globale.
- **Radar (Protezione Civile).** Due immagini in più, `radar_1_verifica` e `radar_2_prossime_3_ore`, e un CSV nell'archivio.
  *Verifica*: per le ultime ore (fino a 6) la pioggia oraria misurata dal radar nazionale (prodotto SRI, mosaico a 1 km
  ogni 5 minuti) accanto a quella di WRF, con la media sull'area, la quota di area bagnata e un indice di accordo di
  posizione (FSS, soglia 0,5 mm in un'ora, controllato su 10 km). *Prossime 3 ore*: il radar spostato lungo il movimento che
  ha adesso, WRF per le stesse ore, e un mix dei due in cui il peso del radar scende da 83% (prima ora) a 17% (terza).
  I pesi sono una scelta di buon senso, **non tarati**. Se il radar non risponde lo script esce e le mappe di WRF non cambiano.
  Cosa dicono i collaudi (radar vero, ultimi 4 giorni, 76 casi su riquadri di 300 km in tutta Italia, confronto con
  «la pioggia resta dov'è»): spostare la pioggia **non migliora in media** l'accordo di posizione (differenza tra
  −0,02 e +0,02, indistinguibile da zero). Se però il movimento stimato è rapido (oltre circa 24 km/h) si guadagna
  poco (circa +0,04 su una base di circa 0,25), mentre con movimenti lenti spostare peggiora (circa −0,03). Per questo sotto quella
  velocità la pioggia è lasciata ferma. Un singolo episodio di pioggia organizzata (12 ottobre sul Lazio) andava molto
  meglio (accordo a un'ora 0,68 contro 0,43), ma è un caso favorevole, non la regola. Il radar non prevede la nascita dei
  temporali: dopo 1-2 ore conta soprattutto WRF. Il radar stesso può sbagliare (echi dei monti, schermature, calibrazione).
  Nella zona dei Castelli negli ultimi 4 giorni non è piovuto, quindi la verifica contro WRF vero non è ancora stata vista.
  Il CSV (`archivio/<ciclo>/radar_verifica.csv`) serve a vedere nel tempo se WRF migliora e a tarare i pesi.
- **Raffiche = stima**: massimo orario del vento a 10 m di WRF (`nwp_diagnostics`) e raffica «turbolenta» (vento medio + 7,71 u\* f,
  con f che cresce con l'instabilità, metodo del modello ECMWF, Bechtold e Bidlot 2009); la mappa mostra il più alto dei due.
  Non ancora tarata sulle raffiche misurate dalle stazioni: si regola con la variabile d'ambiente `WRF_FATTORE_TURBOLENZA` (1 = metodo originale).
- **CAPE e CIN = stima** calcolate colonna per colonna su tutti i livelli di WRF: parcella più instabile (MU, nei primi 300 hPa) e strato mescolato
  (ML, 100 hPa), con temperatura virtuale e livello di libera convezione. Controllate contro MetPy su profili simili a quelli di WRF
  (scarti attorno al 10% per ML, molto meno per MU): è un controllo del calcolo, non della previsione.
- **Zero termico, T a 925 e 850 hPa**: interpolati in ln p; sotto il suolo si estrapola con 6,5 K/km. **Nuvolosità**: da CLDFRA con
  sovrapposizione massima-casuale (bassa sigma > 0,8, media 0,45-0,8, alta < 0,45). **Neve fresca**: precipitazione solida di WRF con densità di
  Hedstrom e Pomeroy (1998), non accumulata sul suolo. **Shear e SRH**: vento a quote fisse sopra il suolo, moto della tempesta di Bunkers.
- **Rischio fulmini, supercelle e tornado sono INDICI, non probabilità.** Fulmini: LPI di WRF (`lightning_option = 3` nel dominio a 1 km) e corrente
  ascendente × graupel; supercelle: tipo SCP (CAPE, CIN, SRH 0-3 km, shear 0-6 km); tornado: tipo STP (CAPE e CIN del livello mescolato, base delle nubi,
  SRH 0-1 km, shear 0-6 km). Nascono su dati degli Stati Uniti e **non sono tarati sull'Italia**: dicono dove le condizioni sono favorevoli,
  non quanto è probabile l'evento. Un tornado è un fenomeno più piccolo della cella di calcolo: l'indice segnala un ambiente, non prevede un tornado.
  Ogni mappa lo dichiara in basso.
- ECMWF (come GFS) ha punti ogni 25 km: l'1 km viene da WRF e dall'orografia, non dal dato di partenza.
- I dati ECMWF sono quelli *open data* (licenza CC-BY 4.0): per ogni ora si scaricano solo i campi che servono
  (circa 40 MB invece di 140), si ritagliano sull'Italia e si riscrivono con compressione semplice perché
  `ungrib` non legge la compressione CCSDS di ECMWF. Gli strati di suolo, numerati da 1 a 4, diventano
  profondità in cm (0-7, 7-28, 28-100, 100-289) e l'orografia dell'ora 0 è copiata in tutte le ore.
- Non sostituisce le previsioni ufficiali.

## Fonti dei dati e licenze
| cosa | fonte | condizioni |
|---|---|---|
| Dati di partenza e al contorno (default) | [ECMWF IFS open data](https://www.ecmwf.int/en/forecasts/datasets/open-data), 0,25°, [doi:10.21957/open-data](https://doi.org/10.21957/open-data) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) e condizioni d'uso ECMWF. **Dati modificati**: ritagliati sull'Italia, ricodificati e usati come condizioni iniziali e al contorno di WRF. ECMWF non garantisce i dati e non risponde di errori o omissioni |
| Dati di partenza alternativi | [GFS di NOAA/NCEP](https://www.nco.ncep.noaa.gov/pmb/products/gfs/) | dati pubblici del governo statunitense; NOAA non approva questo lavoro |
| Temperatura del mare (facoltativa) | [MUR SST](https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1) di NASA JPL (0,01°, circa 1 km), via [NOAA CoastWatch ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/), citazione: JPL MUR MEaSUREs Project, 2015, [doi:10.5067/GHGMR-4FJ04](https://doi.org/10.5067/GHGMR-4FJ04) | dati NASA ad accesso libero, si chiede di citare la fonte |
| Radar (facoltativo) | [Radar-DPC](https://radar.protezionecivile.it), Dipartimento della Protezione Civile, mosaico nazionale SRI (intensità di pioggia) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): va citata la fonte e le immagini ricavate (`radar_*`) hanno la stessa licenza. Dati usati solo per le due immagini radar, non ripubblicati in forma grezza; il CSV contiene solo medie sull'area |
| Modello | [WRF e WPS](https://www2.mmm.ucar.edu/wrf/users/public.html) di NCAR/UCAR | software pubblico, non incluso qui: lo compila il flusso di lavoro dai sorgenti ufficiali |
| Terreno e uso del suolo | dati geografici [WPS_GEOG](https://www2.mmm.ucar.edu/wrf/users/download/get_sources_wps_geog.html) di NCAR/UCAR (tra cui GMTED2010 di USGS/NGA e MODIS) | scaricati durante il calcolo, non inclusi qui; vale la licenza di ciascun dato |
| Confini provinciali e comunali | confini amministrativi ISTAT, elaborati da [Openpolis](https://github.com/openpolis/geojson-italy) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)) | semplificati (25 m) e ritagliati sull'area delle mappe in `dati/confini.json`; la fonte va citata (Confini: ISTAT, elaborati da Openpolis, CC BY 4.0) |
| Contorno dei laghi | [ESA WorldCover 2021](https://esa-worldcover.org) v200 (acqua a 10 m) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium; contorni semplificati in `dati/laghi.json` |
| Stazioni meteo | rete di stazioni amatoriali di [Weather Underground](https://www.wunderground.com/) (The Weather Company), tramite la chiave personale del proprietario | restano soggette ai termini d'uso di Weather Underground, da rispettare (la chiave è personale). I dati **non vengono ripubblicati**: si scaricano durante il calcolo, entrano in WRF e non finiscono nei risultati; i file temporanei che passano da un segmento all'altro sono cifrati; i log non riportano codici o posizioni delle stazioni; le mappe mostrano solo l'uscita del modello |
| Solo per `previsioni_castelli.py` usato da solo | [Open-Meteo](https://open-meteo.com/) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); l'API gratuita è per uso non commerciale) e quote dal modello digitale del terreno Copernicus DEM («contiene dati Copernicus modificati») | non usati dalla catena WRF |

Librerie principali: ecCodes (Apache 2.0), JasPer, NumPy, SciPy, Matplotlib, netCDF4, requests, pyproj, OpenCV, tifffile: ciascuna con la sua licenza.
I nomi dei paesi e le posizioni sulle mappe sono scritti a mano nello script, non vengono da OpenStreetMap o altri archivi.
Le condizioni dei fornitori possono cambiare: prima di usare il progetto in modo diverso da quello personale
(per esempio per un servizio pubblico o commerciale) vanno ricontrollate.

## Stato del collaudo
Provato davvero (in un ambiente senza compilatore Fortran):
namelist (letti da f90nml, domini annidati verificati), scelta del ciclo e scarico dei dati ECMWF veri,
`ungrib` compilato e fatto girare su file ECMWF veri con la tabella `Vtable.ECMWF_OD` (88 campi per ora, suolo
e neve compresi),
file delle stazioni (inventate) riletto con le stesse istruzioni di lettura di WRF,
file `SST` riletto con `rd_intermediate` di WPS,
radar vero (scarico, posizione sulla mappa, movimento su casi inventati e su pioggia vera) e le due immagini a partire da
`wrfout` inventati; il confronto con WRF vero non è stato visto,
grandezze derivate (`wrf/diagnostiche.py`) su casi con risposta nota, CAPE contro MetPy, mappe a partire da file `wrfout` inventati con la stessa struttura di WRF, pubblicazione
nel ramo `risultati`, sintassi del workflow (actionlint) e degli script (shellcheck).

Queste prove (tranne la compilazione del ramo ECMWF vero) girano da sole a ogni modifica del codice:
`wrf/prove.sh`, lanciato dal flusso **Prova automatica** (`.github/workflows/prova.yml`, pochi minuti, non tocca le
cache di WRF). Si può lanciare anche a mano: `bash wrf/prove.sh` (con `PROVA_RADAR=1` prova anche il radar vero).

**Non provato:** compilazione di WRF e WPS sul server di GitHub, download dei dati geografici NCAR, geogrid, metgrid,
real.exe, wrf.exe, accettazione da parte di WRF di `nwp_diagnostics` e `lightning_option = 3`.
Il primo avvio potrebbe richiedere qualche correzione: i log escono come artifact.
Cronaca della prima compilazione su GitHub (16 ottobre 2026):
1. *Primo run:* fermo per oltre 4 ore, annullato. Causa **quasi certa**: il rilevamento dell'opzione lanciava `./configure < /dev/null | … | head -n1`;
   senza risposte il configure di WRF riscrive il menu all'infinito (verificato in locale). In locale il SIGPIPE lo ferma, su GitHub no:
   il log mostrava i `Broken pipe` della catena e, all'annullamento, i processi `configure` e `perl` ancora vivi (che il SIGPIPE sia
   ignorato dal server è dedotto, non misurato). Ora quella chiamata ha un limite di 60 secondi e il run successivo ha superato il punto.
2. *Secondo run:* tutti gli oggetti compilati in circa 30 minuti, nessun errore di compilazione, ma il collegamento di `wrf.exe` e `real.exe`
   è fallito con `undefined reference` (a `module_optional_input`, `solve_interface`, …), pur con quei moduli compilati e archiviati. Ogni
   collegamento durava 18 minuti con 7 GB di memoria. Il `mpif90` di Ubuntu aggiunge da solo `-flto=auto`. Correzione: `-fno-lto` su `DM_FC` e `DM_CC`
   (`disattiva_lto`); gli oggetti già compilati si riusano dalla cache parziale. È una **ipotesi forte, non ancora provata**: in un caso piccolo
   il problema non si riproduce. Se il collegamento fallisce ancora, `diagnosi.txt` contiene il contenuto dell'archivio.

Le funzioni di avanzamento, tempo massimo, guardiano e `-fno-lto` sono provate con comandi e file inventati (`wrf/prova_costruzione.sh`).
La chiave della cache parziale (`wrf-src-v1-…`) non dipende dagli script: una correzione a `costruisci.sh` non butta via gli oggetti compilati
(per ripartire da zero basta cambiare `v1` nel flusso di lavoro). La cache finale (`wrf-build-…`) invece dipende dagli script.

## File
- `.github/workflows/wrf.yml` — il flusso automatico
- `wrf/dominio.py` — geometria dei tre domini · `wrf/config.py` — namelist di WPS e WRF
- `wrf/dipendenze.sh`, `costruisci.sh` (a tappe, con avanzamento e guardiano), `statico.sh`, `esegui.sh`, `pubblica.sh`
- `wrf/scarica_ecmwf.py` + `wrf/Vtable.ECMWF_OD` — dati ECMWF · `wrf/scarica_gfs.py` — alternativa GFS
- `wrf/diagnostiche.py` — CAPE/CIN, shear, SRH, nuvole, zero termico, indici di rischio, raffica e neve, colonna per colonna · `wrf/postprocess.py` — da `wrfout` alle mappe · `wrf/orarie.py` — una immagine per ora e variabile + `indice.json`
- `sito/previsioni-wrf.html` — pagina per sfogliare le immagini orarie (da caricare sul sito)
- `wrf/stazioni_wrf.py` — stazioni Wunderground nel formato di WRF per il nudging
- `wrf/scarica_sst.py` — temperatura del mare MUR nel formato intermedio di WPS (campo `SST`)
- `wrf/radar.py` — scarico del radar Radar-DPC, posizione sulla mappa, movimento · `wrf/pioggia_radar.py` — verifica e
  pioggia delle prossime 3 ore
- `wrf/prova_sintetica.py` — file `wrfout` (e `geo_em`) inventati per collaudare senza WRF · `wrf/prove.sh` — tutte le prove
  · `wrf/leggi_obs.f90` — rilegge i file delle stazioni con i formati di WRF · `wrf/prova_costruzione.sh` — prova
  avanzamento, tempo massimo e guardiano della compilazione con comandi inventati
- `.github/workflows/prova.yml` — prova automatica a ogni modifica
- `previsioni_castelli.py` — mappe e correzione con le stazioni (usato da `postprocess.py`)
- Il vento è disegnato come **linee di flusso** (come le carte di Meteociel): linee continue sottili con freccette piene lungo la linea che danno il verso; il colore sotto è la velocità. Si regola con `densita` e `scala` in `disegna_flusso()` (`previsioni_castelli.py`).
- `dati/confini.json` — confini comunali (linea molto fine) e provinciali (fine) disegnati su tutte le mappe · `wrf/prepara_confini.py` — lo rifà dai confini ISTAT di Openpolis (serve solo se cambiano)
- `dati/laghi.json` — contorni reali dei laghi (Albano, Nemi e stagni) · `wrf/prepara_laghi.py` — lo rifà da ESA WorldCover
