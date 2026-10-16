#!/usr/bin/env python3
"""Confronta due cartelle con geo_em.d0N.nc (vecchi dati di serie e nuovi dati fini): statistiche e un'immagine."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from netCDF4 import Dataset

vecchi, nuovi, out = (Path(x) for x in sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
fig, ax = plt.subplots(2, 3, figsize=(15, 9))
for r, n in enumerate((3, 2)):
    with Dataset(vecchi / f"geo_em.d0{n}.nc") as a, Dataset(nuovi / f"geo_em.d0{n}.nc") as b:
        ha, hb = np.array(a["HGT_M"][0]), np.array(b["HGT_M"][0])
        la, lb = np.array(a["LU_INDEX"][0]), np.array(b["LU_INDEX"][0])
        ma, mb = np.array(a["LANDMASK"][0]), np.array(b["LANDMASK"][0])
        print(f"== dominio {n} ({ha.shape})")
        print(f"  quota   vecchia min/media/max {ha.min():.0f}/{ha.mean():.0f}/{ha.max():.0f}  nuova {hb.min():.0f}/{hb.mean():.0f}/{hb.max():.0f}")
        print(f"  differenza quota: media {np.mean(hb - ha):+.1f} m, assoluta media {np.mean(abs(hb - ha)):.1f} m, max {np.max(abs(hb - ha)):.0f} m")
        print(f"  deviazione standard della quota: vecchia {ha.std():.1f} nuova {hb.std():.1f}")
        print(f"  mare/terra (LANDMASK=0): vecchia {np.mean(ma == 0):.1%} nuova {np.mean(mb == 0):.1%}")
        for nome, m in (("vecchio", la), ("nuovo", lb)):
            c = dict(zip(*np.unique(m, return_counts=True)))
            print(f"  suolo {nome}: " + ", ".join(f"{int(k)}:{v / m.size:.1%}" for k, v in c.items()))
        vmax = max(ha.max(), hb.max())
        for j, (t, m, kw) in enumerate((("quota vecchia", ha, dict(vmin=0, vmax=vmax)), ("quota nuova", hb, dict(vmin=0, vmax=vmax)),
                                        ("uso del suolo nuovo", lb, dict(cmap="tab20", vmin=1, vmax=21)))):
            im = ax[r, j].imshow(m, origin="lower", **({"cmap": "terrain"} | kw))
            ax[r, j].set_title(f"d0{n} {t}")
            plt.colorbar(im, ax=ax[r, j], shrink=0.7)
fig.tight_layout()
fig.savefig(out / "confronto_geo.png", dpi=90)
