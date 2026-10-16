#!/usr/bin/env bash
# Pacchetti di sistema per compilare e far girare WRF/WPS su Ubuntu 22.04 (runner di GitHub).
set -euo pipefail
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  gfortran gcc g++ make m4 csh perl file \
  mpich libmpich-dev \
  libnetcdf-dev libnetcdff-dev netcdf-bin \
  libpng-dev libjasper-dev zlib1g-dev
