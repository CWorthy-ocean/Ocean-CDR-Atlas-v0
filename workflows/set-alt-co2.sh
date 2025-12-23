#!/bin/bash

set -e 

# Set the main carbon system tracers (DIC, ALK) to the ALT_CO2 versions
# DIC = DIC_ALT_CO2
# ALK = ALK_ALT_CO2
# MARBL_PH_3D = MARBL_PH_3D_ALT_CO2
# MARBL_PH_SURF = MARBL_PH_SURF_ALT_CO2

# new way: Perlmutter
module load climate-utils

POP_R=${1}

extract_vars=ALK_CUR,ALK_OLD
extract_vars=${extract_vars},DIC_CUR,DIC_OLD
extract_vars=${extract_vars},MARBL_PH_3D,MARBL_PH_SURF

ncks -O -v ${extract_vars} ${POP_R} ${POP_R}.alt_co2
ncrename -O -v ALK_CUR,ALK_ALT_CO2_CUR ${POP_R}.alt_co2 ${POP_R}.alt_co2
ncrename -O -v ALK_OLD,ALK_ALT_CO2_OLD ${POP_R}.alt_co2 ${POP_R}.alt_co2
ncrename -O -v DIC_CUR,DIC_ALT_CO2_CUR ${POP_R}.alt_co2 ${POP_R}.alt_co2
ncrename -O -v DIC_OLD,DIC_ALT_CO2_OLD ${POP_R}.alt_co2 ${POP_R}.alt_co2
ncrename -O -v MARBL_PH_SURF,MARBL_PH_SURF_ALT_CO2 ${POP_R}.alt_co2 ${POP_R}.alt_co2
ncrename -O -v MARBL_PH_3D,MARBL_PH_3D_ALT_CO2 ${POP_R}.alt_co2 ${POP_R}.alt_co2

alt_co2_vars=ALK_ALT_CO2_CUR,ALK_ALT_CO2_OLD
alt_co2_vars=${alt_co2_vars},DIC_ALT_CO2_CUR,DIC_ALT_CO2_OLD
alt_co2_vars=${alt_co2_vars},MARBL_PH_3D_ALT_CO2,MARBL_PH_SURF_ALT_CO2

ncks -O -x -v ${alt_co2_vars} ${POP_R} ${POP_R}
ncks -A ${POP_R}.alt_co2 ${POP_R}
