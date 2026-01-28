#!/usr/bin/env bash
set -euo pipefail

# Test Intel + OpenMPI stack and discover NetCDF-related variants.
if ! command -v module >/dev/null 2>&1; then
  if [ -f /etc/profile.d/modules.sh ]; then
    # shellcheck disable=SC1091
    source /etc/profile.d/modules.sh
  fi
fi

module --force purge

echo "==> Load Intel compiler"
module load intel/19.0.5.281
module list

echo "==> Available MPI stacks (post-Intel)"
module spider openmpi
module spider impi

echo "==> Load OpenMPI"
module load openmpi/4.1.6
module list

echo "==> NetCDF/HDF5/PNETCDF variants (post-Intel+OpenMPI)"
module spider hdf5
module spider netcdf-c
module spider netcdf-fortran
module spider parallel-netcdf

try_load() {
  local name="$1"
  shift
  local version
  for version in "$@"; do
    if module load "${name}/${version}" >/dev/null 2>&1; then
      echo "Loaded ${name}/${version}"
      return 0
    fi
  done
  echo "Failed to load ${name} with any candidate version" >&2
  return 1
}

echo "==> Attempt to load IO stack (preferred newest first)"
try_load hdf5 1.14.5 1.10.7
try_load netcdf-c 4.9.2 4.7.4
try_load netcdf-fortran 4.5.3
try_load parallel-netcdf 1.12.3 1.11.2
module load cmake

echo "==> Final module list"
module list
