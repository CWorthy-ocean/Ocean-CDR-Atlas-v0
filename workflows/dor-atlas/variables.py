### Choice of variables

# Matt's breakdown of which variables are most important to keep
# Except I've separated out all counterfactual vars ("*_ALT" variables)
PRIORITY_0_VARS = [  # do not include (except from control run)
    "ECOSYS_ATM_PRESS",
    "ECOSYS_IFRAC",
    "ECOSYS_XKW",
    "IAGE",
    "Jint_100m_DIC",
    "SCHMIDT_CO2",
]
PRIORITY_1_VARS = [  # highest priority to include
    "ALK",
    "ALK_FLUX",
    "ALK_zint_100m",
    "ANGLE",
    "ANGLET",
    "ATM_CO2",
    "DCO2STAR",
    "DIC",
    "DIC_zint_100m",
    "DXT",
    "DXU",
    "DYT",
    "DYU",
    "DpCO2",
    "FG_CO2",
    "HT",
    "HTE",
    "HTN",
    "HU",
    "HUS",
    "HUW",
    "KMT",
    "KMU",
    "PH",
    "REGION_MASK",
    "STF_ALK",
    "T0_Kelvin",
    "TAREA",
    "TLAT",
    "TLONG",
    "UAREA",
    "ULAT",
    "ULONG",
    "cp_air",
    "cp_sw",
    "days_in_norm_year",
    "dz",
    "dzw",
    "fwflux_factor",
    "grav",
    "heat_to_PW",
    "hflux_factor",
    "latent_heat_fusion",
    "latent_heat_fusion_mks",
    "latent_heat_vapor",
    "mass_to_Sv",
    "momentum_factor",
    "nsurface_t",
    "nsurface_u",
    "ocn_ref_salinity",
    "omega",
    "pCO2SURF",
    "ppt_to_salt",
    "radius",
    "rho_air",
    "rho_fw",
    "rho_sw",
    "salinity_factor",
    "salt_to_Svppt",
    "salt_to_mmday",
    "salt_to_ppt",
    "sea_ice_salinity",
    "sflux_factor",
    "sound",
    "stefan_boltzmann",
    "time",
    "time_bound",
    "vonkar",
    "z_t",
    "z_t_150m",
    "z_w",
    "z_w_bot",
    "z_w_top",
]
PRIORITY_2_VARS = [
    "CO2STAR",
    "CO3",
    "H2CO3",
    "HCO3",
    "co3_sat_arag",
    "co3_sat_calc",
    "pH_3D",
    "tend_zint_100m_ALK",
    "tend_zint_100m_DIC",
]
PRIORITY_3_VARS = [  # lowest priority to include
    "ALK_RESTORE_TEND",
]

# variables which don't actually vary with polygon_id
# i.e. anything with `_ALT` in it
# (though they arguably do vary with injection_date)
COUNTERFACTUAL_PRIORITY_0_VARS = [
    "ATM_ALT_CO2",
]
COUNTERFACTUAL_PRIORITY_1_VARS = [
    "ALK_ALT_CO2",
    "ALK_ALT_CO2_zint_100m",
    "DCO2STAR_ALT_CO2",
    "DIC_ALT_CO2",
    "DIC_ALT_CO2_zint_100m",
    "DpCO2_ALT_CO2",
    "FG_ALT_CO2",
    "PH_ALT_CO2",
    "STF_ALK_ALT_CO2",
    "pCO2SURF_ALT_CO2",
]
COUNTERFACTUAL_PRIORITY_2_VARS = [
    "CO2STAR_ALT_CO2",
    "CO3_ALT_CO2",
    # "H2CO3",
    # "HCO3",
    "co3_sat_arag",
    "co3_sat_calc",
    "pH_3D_ALT_CO2",
    "tend_zint_100m_ALK_ALT_CO2",
    "tend_zint_100m_DIC_ALT_CO2",
]
COUNTERFACTUAL_PRIORITY_3_VARS = [
    "ALK_ALT_CO2_RESTORE_TEND",
]
COUNTERFACTUAL_VARS = (
    COUNTERFACTUAL_PRIORITY_0_VARS
    + COUNTERFACTUAL_PRIORITY_1_VARS
    + COUNTERFACTUAL_PRIORITY_2_VARS
    + COUNTERFACTUAL_PRIORITY_3_VARS
)

# But loads of these data variables aren't really dependent data variables at all...
COORDS = [
    "dz",
    "dzw",
    "KMT",
    "KMU",
    "REGION_MASK",
    "UAREA",
    "TAREA",
    "HU",
    "HT",
    "DXU",
    "DYU",
    "DXT",
    "DYT",
    "HTN",
    "HTE",
    "HUS",
    "HUW",
    "time_bound",
    # everything beyond here are just like fundamental constants or conversion factors, do we actually need these?
    "ANGLE",
    "ANGLET",
    "days_in_norm_year",
    "grav",
    "omega",
    "cp_sw",
    "vonkar",
    "rho_air",
    "rho_sw",
    "rho_fw",
    "stefan_boltzmann",
    "latent_heat_vapor",
    "latent_heat_fusion",
    "latent_heat_fusion_mks",
    "ocn_ref_salinity",
    "sea_ice_salinity",
    "T0_Kelvin",
    "salt_to_ppt",
    "ppt_to_salt",
    "mass_to_Sv",
    "heat_to_PW",
    "salt_to_Svppt",
    "salt_to_mmday",
    "momentum_factor",
    "hflux_factor",
    "fwflux_factor",
    "salinity_factor",
    "sflux_factor",
    "nsurface_t",
    "nsurface_u",
    "radius",
    "sound",
    "cp_air",
]

VARS_TO_DROP = (
    COUNTERFACTUAL_PRIORITY_0_VARS
    + COUNTERFACTUAL_PRIORITY_3_VARS
    + PRIORITY_0_VARS
    + PRIORITY_3_VARS
)
