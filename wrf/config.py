#!/usr/bin/env python3
"""Genera i namelist di WPS e WRF per i tre domini annidati (vedi dominio.py).

  config.py wps   --ciclo 2026101600 --ore 48 [--pilota ecmwf|gfs] [--geog PERCORSO]   > namelist.wps
  config.py input --ciclo 2026101600 --da 0 --a 16 [--nlev 34 --nsoil 4] > namelist.input
  config.py metgrid-info met_em.d01.*.nc          stampa "livelli_metgrid livelli_suolo"

`--da` e `--a` sono ore dall'inizio del ciclo; con --da > 0 il run riprende da un restart.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dominio as D  # noqa: E402

TIME_STEP = 54  # s sul dominio 1; 18 s e 6 s nei nidi (parent_time_step_ratio 1:3:3)


def _ciclo(testo):
    return datetime.strptime(testo, "%Y%m%d%H")


def _data(dt):
    return dt.strftime("%Y-%m-%d_%H:%M:%S")


def _tre(valore, fmt="{}"):
    return ", ".join(fmt.format(valore) for _ in range(3))


def namelist_wps(inizio, fine, geog, prefisso):
    starts = D.parent_starts()
    return f"""&share
 wrf_core = 'ARW',
 max_dom = 3,
 start_date = {_tre(_data(inizio), "'{}'")},
 end_date   = {_tre(_data(fine), "'{}'")},
 interval_seconds = 10800,
 io_form_geogrid = 2,
/

&geogrid
 parent_id         = 1, 1, 2,
 parent_grid_ratio = {", ".join(map(str, D.RATIO))},
 i_parent_start    = {", ".join(map(str, starts))},
 j_parent_start    = {", ".join(map(str, starts))},
 e_we              = {", ".join(map(str, D.E))},
 e_sn              = {", ".join(map(str, D.E))},
 geog_data_res     = 'default', 'default', 'default',
 dx = {D.DX[0]},
 dy = {D.DX[0]},
 map_proj  = 'lambert',
 ref_lat   = {D.LAT0},
 ref_lon   = {D.LON0},
 truelat1  = {D.TRUELAT1},
 truelat2  = {D.TRUELAT2},
 stand_lon = {D.LON0},
 geog_data_path = '{geog}',
/

&ungrib
 out_format = 'WPS',
 prefix = '{prefisso}',
/

&metgrid
 fg_name = '{prefisso}',
 io_form_metgrid = 2,
/
"""


def namelist_input(inizio, fine, riprendi, nlev, nsoil):
    ore = int(round((fine - inizio).total_seconds() / 3600))
    starts = D.parent_starts()

    def riga(nome, valori):
        return f" {nome:<26}= {', '.join(str(v) for v in valori)},\n"

    t = ""
    t += "&time_control\n"
    t += " run_days = 0,\n run_hours = %d,\n run_minutes = 0,\n run_seconds = 0,\n" % ore
    for nome, dt in (("start", inizio), ("end", fine)):
        for campo, fmt in (("year", "%Y"), ("month", "%m"), ("day", "%d"), ("hour", "%H")):
            t += riga(f"{nome}_{campo}", [int(dt.strftime(fmt))] * 3)
        t += riga(f"{nome}_minute", [0] * 3)
        t += riga(f"{nome}_second", [0] * 3)
    t += " interval_seconds = 10800,\n"
    t += riga("input_from_file", [".true."] * 3)
    t += riga("history_interval", [60] * 3)
    t += riga("frames_per_outfile", [1000] * 3)
    t += f" restart = {'.true.' if riprendi else '.false.'},\n"
    t += f" restart_interval = {ore * 60},\n"
    t += " io_form_history = 2,\n io_form_restart = 2,\n io_form_input = 2,\n io_form_boundary = 2,\n"
    t += " history_outname = 'wrfout_d<domain>_<date>',\n"
    # massimi orari (tra cui il vento a 10 m) per stimare le raffiche
    t += " output_diagnostics = 1,\n auxhist3_outname = 'wrfxtrm_d<domain>_<date>',\n"
    t += riga("auxhist3_interval", [60] * 3)
    t += riga("frames_per_auxhist3", [1000] * 3)
    t += " io_form_auxhist3 = 2,\n debug_level = 0,\n/\n\n"

    t += "&domains\n"
    t += f" time_step = {TIME_STEP},\n time_step_fract_num = 0,\n time_step_fract_den = 1,\n max_dom = 3,\n"
    t += riga("e_we", D.E) + riga("e_sn", D.E) + riga("e_vert", [D.E_VERT] * 3)
    t += riga("dx", D.DX) + riga("dy", D.DX)
    t += riga("grid_id", [1, 2, 3]) + riga("parent_id", [0, 1, 2])
    t += riga("i_parent_start", starts) + riga("j_parent_start", starts)
    t += riga("parent_grid_ratio", D.RATIO) + riga("parent_time_step_ratio", D.RATIO)
    t += " feedback = 0,\n smooth_option = 0,\n p_top_requested = 5000,\n"
    t += f" num_metgrid_levels = {nlev},\n num_metgrid_soil_levels = {nsoil},\n"
    t += " interp_type = 2,\n extrap_type = 2,\n t_extrap_type = 2,\n lowest_lev_from_sfc = .false.,\n"
    t += " use_levels_below_ground = .true.,\n use_surface = .true.,\n lagrange_order = 2,\n"
    t += " zap_close_levels = 500,\n force_sfc_in_vinterp = 1,\n"
    t += "/\n\n"

    t += "&physics\n"
    t += riga("mp_physics", [8] * 3)                       # Thompson
    t += riga("ra_lw_physics", [4] * 3) + riga("ra_sw_physics", [4] * 3)   # RRTMG
    t += riga("radt", [10, 6, 3])
    t += riga("sf_sfclay_physics", [1] * 3) + riga("sf_surface_physics", [2] * 3)  # Noah
    t += riga("bl_pbl_physics", [1] * 3) + riga("bldt", [0] * 3)           # YSU
    t += riga("cu_physics", [1, 0, 0]) + riga("cudt", [0] * 3)             # convezione esplicita da 3 km
    t += riga("topo_wind", [1] * 3)
    t += riga("slope_rad", [0, 0, 1]) + riga("topo_shading", [0, 0, 1])
    t += " isfflx = 1,\n ifsnow = 1,\n icloud = 1,\n surface_input_source = 1,\n"
    t += " num_soil_layers = 4,\n num_land_cat = 21,\n sst_update = 0,\n"
    t += riga("sf_urban_physics", [0] * 3)
    t += "/\n\n"

    t += "&dynamics\n"
    t += " hybrid_opt = 2,\n use_theta_m = 0,\n w_damping = 1,\n"
    t += riga("diff_opt", [1] * 3) + riga("km_opt", [4] * 3)
    t += riga("diff_6th_opt", [0] * 3) + riga("diff_6th_factor", [0.12] * 3)
    t += " base_temp = 290.,\n damp_opt = 3,\n zdamp = 5000., 5000., 5000.,\n dampcoef = 0.2, 0.2, 0.2,\n"
    t += riga("khdif", [0] * 3) + riga("kvdif", [0] * 3)
    t += riga("non_hydrostatic", [".true."] * 3)
    t += riga("moist_adv_opt", [1] * 3) + riga("scalar_adv_opt", [1] * 3)
    t += " gwd_opt = 0,\n/\n\n"

    t += "&bdy_control\n spec_bdy_width = 5,\n spec_zone = 1,\n relax_zone = 4,\n"
    t += riga("specified", [".true.", ".false.", ".false."]) + riga("nested", [".false.", ".true.", ".true."])
    t += "/\n\n&namelist_quilt\n nio_tasks_per_group = 0,\n nio_groups = 1,\n/\n"
    return t


def info_metgrid(percorso):
    from netCDF4 import Dataset

    with Dataset(percorso) as ds:
        return int(ds.getncattr("NUM_METGRID_LEVELS")), int(ds.getncattr("NUM_METGRID_SOIL_LEVELS"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wps")
    w.add_argument("--ciclo", default="2026010100")
    w.add_argument("--ore", type=int, default=24)
    w.add_argument("--geog", default="/percorso/WPS_GEOG")
    w.add_argument("--pilota", choices=["ecmwf", "gfs"], default="ecmwf",
                   help="modello globale da cui WRF prende condizioni iniziali e al contorno")
    i = sub.add_parser("input")
    i.add_argument("--ciclo", required=True)
    i.add_argument("--da", type=int, default=0)
    i.add_argument("--a", type=int, required=True)
    i.add_argument("--nlev", type=int, default=34)
    i.add_argument("--nsoil", type=int, default=4)
    m = sub.add_parser("metgrid-info")
    m.add_argument("file")
    a = ap.parse_args()

    D.verifica()
    if a.cmd == "wps":
        c = _ciclo(a.ciclo)
        sys.stdout.write(namelist_wps(c, c + timedelta(hours=a.ore), a.geog, a.pilota.upper()))
    elif a.cmd == "input":
        c = _ciclo(a.ciclo)
        if a.a <= a.da:
            sys.exit("--a deve essere maggiore di --da")
        sys.stdout.write(namelist_input(c + timedelta(hours=a.da), c + timedelta(hours=a.a), a.da > 0,
                                        a.nlev, a.nsoil))
    else:
        print(*info_metgrid(a.file))


if __name__ == "__main__":
    main()
