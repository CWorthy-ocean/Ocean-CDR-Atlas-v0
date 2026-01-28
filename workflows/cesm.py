import os
import shutil
from glob import glob
from subprocess import check_call

from datetime import datetime

import textwrap

import numpy as np
import pandas as pd

import machine
from config import project_sname, paths, account, machine_name

scriptroot = paths["workflow"]
os.makedirs(f"{scriptroot}/output/build-in", exist_ok=True)
os.makedirs(f"{scriptroot}/output/build-out", exist_ok=True)


cesm_inputdata = paths["cesm_inputdata_ro"]


def create_smyle_clone(
    case,
    refdate="0347-01-01",
    queue="regular",
    cdr_forcing=None,
    cdr_forcing_file=None,
    clobber=False,
    curtail_output=True,
    stop_n=15,
    stop_option="nyear",
    wallclock="10:00:00",
    resubmit=0,
):

    caseroot = f"{paths['cases']}/{case}"
    assert (
        not os.path.exists(caseroot) or clobber
    ), f"Case {case} exists; caseroot:\n{caseroot}\n"

    if cdr_forcing is not None:
        assert cdr_forcing in ["OAE", "DOR", "ERW"], f"Unknown CDR forcing: {cdr_forcing}"

    rundir = f"{paths['scratch']}/{case}/run"
    blddir = f"{paths['scratch']}/{case}/bld"
    archive_root = f"{paths['data']}/archive/{case}"

    check_call(["rm", "-fr", caseroot])
    check_call(["rm", "-fr", archive_root])
    check_call(["rm", "-fr", f"{paths['scratch']}/{case}"])

    refcase = "g.e22.GOMIPECOIAF_JRA-1p4-2018.TL319_g17.SMYLE.005"
    refcaserest_root = "/global/cfs/projectdirs/m4746/Datasets/SMYLE-FOSI/rest"
    compset = (
        "OMIP_DATM%JRA-1p4-2018_SLND_CICE_POP2%ECO_DROF%JRA-1p4-2018_SGLC_WW3_SIAC_SESP"
    )
    res = "TL319_g17"

    check_call(
        " ".join(
            [
                "module load python",
                "&&",
                "./create_newcase",
                "--compset",
                compset,
                "--case",
                caseroot,
                "--res",
                res,
                "--machine",
                machine_name,
                "--compiler",
                "intel",
                "--project",
                account,
                "--queue",
                queue,
                "--walltime",
                wallclock,
                "--handle-preexisting-dirs",
                "r",
                "--run-unsupported",
            ]
        ),
        shell=True,
        cwd=f"{paths['src']}/cime/scripts",
    )

    def xmlchange(arg, force=False):
        """call xmlchange"""
        check_call(f"module load python && ./xmlchange {arg}", cwd=caseroot, shell=True)

    xmlchange("MAX_TASKS_PER_NODE=128")
    xmlchange("MAX_MPITASKS_PER_NODE=128")

    xmlchange("NTASKS_ATM=72")
    xmlchange("NTASKS_CPL=72")
    xmlchange("NTASKS_WAV=72")
    xmlchange("NTASKS_GLC=72")
    xmlchange("NTASKS_ICE=72")
    xmlchange("NTASKS_ROF=72")
    xmlchange("NTASKS_LND=72")
    xmlchange("NTASKS_ESP=72")
    xmlchange("NTASKS_IAC=72")

    xmlchange("NTASKS_OCN=751")
    xmlchange("ROOTPE_OCN=72")

    xmlchange("CICE_BLCKX=16")
    xmlchange("CICE_BLCKY=16")
    xmlchange("CICE_MXBLCKS=7")
    xmlchange("CICE_DECOMPTYPE='sectrobin'")
    xmlchange("CICE_DECOMPSETTING='square-ice'")

    xmlchange("OCN_TRACER_MODULES='iage ecosys'")
    xmlchange("DATM_PRESAERO='clim_1850'")

    xmlchange("POP_AUTO_DECOMP=FALSE")
    xmlchange("POP_BLCKX=9")
    xmlchange("POP_BLCKY=16")
    xmlchange("POP_NX_BLOCKS=36")
    xmlchange("POP_NY_BLOCKS=24")
    xmlchange("POP_MXBLCKS=1")
    xmlchange("POP_DECOMPTYPE='spacecurve'")

    # refcase SourceMods
    check_call(
        f"cp -vr {scriptroot}/input/cesm2.2.0/cases/{refcase}/SourceMods/* {caseroot}/SourceMods",
        shell=True,
    )

    # list SourceMod files
    src_pop_files = []
    if curtail_output:
        src_pop_files.extend(
            glob(
                f"{scriptroot}/input/cesm2.2.0/SourceMods/curtail-output-gx1v7/src.pop/*"
            )
        )

    # copy SourceMod files
    for src in src_pop_files:
        src_basename = os.path.basename(src)
        if src_basename == "diagnostics_latest.yaml":
            check_call(
                " ".join(
                    [
                        "module load python",
                        "&&",
                        f"{paths['src']}/components/pop/externals/MARBL/MARBL_tools/./yaml_to_json.py",
                        "-y",
                        f"{src}",
                        "-o",
                        f"{caseroot}/SourceMods/src.pop",
                    ]
                ),
                shell=True,
            )
        else:
            dst = f"{caseroot}/SourceMods/src.pop/{src_basename}"
            shutil.copyfile(src, dst)
            if ".csh" in src_basename:
                check_call(["chmod", "+x", dst])

    xmlchange(f"RUNDIR={rundir}")
    xmlchange(f"CIME_OUTPUT_ROOT={paths['scratch']}")

    xmlchange(f"DIN_LOC_ROOT={cesm_inputdata}")
    xmlchange(f"DOUT_S_ROOT='{paths['data']}/archive/$CASE'")

    xmlchange(f"RUN_TYPE=branch")
    xmlchange(f"RUN_STARTDATE={refdate}")
    xmlchange(f"RUN_REFCASE={refcase}")
    xmlchange(f"RUN_REFDATE={refdate}")

    xmlchange(f"STOP_N={stop_n}")
    xmlchange(f"STOP_OPTION={stop_option}")
    xmlchange(f"REST_N={stop_n}")
    xmlchange(f"REST_OPTION={stop_option}")
    xmlchange(f"RESUBMIT={resubmit}")
    xmlchange(f"JOB_WALLCLOCK_TIME={wallclock}")

    xmlchange(f"CHARGE_ACCOUNT={account}")
    xmlchange(f"PROJECT={account}")
    xmlchange(f"JOB_QUEUE={queue}")

    # copy restarts
    os.makedirs(rundir, exist_ok=True)
    check_call(
        f"cp {refcaserest_root}/{refdate}-00000/* {rundir}/.",
        shell=True,
    )

    check_call(
        "module load python && ./case.setup",
        cwd=caseroot,
        shell=True,
    )

    # copy RefCase user_nl files
    user_nl_files = glob(f"{scriptroot}/input/cesm2.2.0/cases/{refcase}/user_nl*")
    for file in user_nl_files:
        file_out = os.path.join(caseroot, os.path.basename(file))
        print(f"{file} -> {file_out}")
        with open(file, "r") as fid:
            file_str = fid.read().replace(
                "/glade/p/cesmdata/cseg/inputdata", cesm_inputdata
            )
        with open(file_out, "w") as fid:
            fid.write(file_str)

    # user_datm files
    user_datm_files = glob(f"{scriptroot}/input/cesm2.2.0/cases/{refcase}/user_datm.*")
    for file in user_datm_files:
        file_out = os.path.join(caseroot, os.path.basename(file))
        print(f"{file} -> {file_out}")
        with open(file, "r") as fid:
            file_str = fid.read().replace(
                "/glade/p/cesmdata/cseg/inputdata", cesm_inputdata
            )
        with open(file_out, "w") as fid:
            fid.write(file_str)

    # namelist
    user_nl = dict()

    print(cdr_forcing)

    alk_forcing_scale_factor = 1.0
    dic_forcing_scale_factor = -1.0
    if cdr_forcing is None:
        lalk_forcing_apply_file_flux = ".false."
        ldic_forcing_apply_file_flux = ".false."
        cdr_forcing_file = "dummy-file-path"
        atm_alt_co2_opt = "const"
        alk_forcing_scale_factor = 1.0
        dic_forcing_scale_factor = -1.0        

    elif cdr_forcing == "OAE":
        lalk_forcing_apply_file_flux = ".true."
        ldic_forcing_apply_file_flux = ".false."
        atm_alt_co2_opt = "drv_diag"
        alk_forcing_scale_factor = 1.0
        dic_forcing_scale_factor = -1.0
        
    elif cdr_forcing == "DOR":
        lalk_forcing_apply_file_flux = ".false."
        ldic_forcing_apply_file_flux = ".true."
        atm_alt_co2_opt = "drv_diag"
        alk_forcing_scale_factor = 1.0
        dic_forcing_scale_factor = -1.0
    
    elif cdr_forcing == "ERW":
        lalk_forcing_apply_file_flux = ".true."
        ldic_forcing_apply_file_flux = ".true."
        atm_alt_co2_opt = "drv_diag"
        alk_forcing_scale_factor = 1.0
        dic_forcing_scale_factor = 1.0
        
    user_nl["marbl"] = textwrap.dedent(
        f"""\
        lalk_forcing_apply_flux = {lalk_forcing_apply_file_flux}
        ldic_forcing_apply_flux = {ldic_forcing_apply_file_flux}
        alk_forcing_scale_factor = {alk_forcing_scale_factor}
        dic_forcing_scale_factor = {dic_forcing_scale_factor}
        """
    )

    user_nl["pop"] = textwrap.dedent(
        f"""\
        atm_alt_co2_opt = '{atm_alt_co2_opt}'
        lecosys_tavg_alt_co2 = .true.
        alk_forcing_shr_stream_year_first = 1999
        alk_forcing_shr_stream_year_last = 2019
        alk_forcing_shr_stream_year_align = 347
        alk_forcing_shr_stream_file = '{cdr_forcing_file}'
        alk_forcing_shr_stream_scale_factor = 1.0e5 ! convert from mol/m^2/s to nmol/cm^2/s
        """
    )

    if curtail_output:
        user_nl["pop"] += textwrap.dedent(
            f"""\
        ! curtail output
        ldiag_bsf = .false.    
        diag_gm_bolus = .false.
        moc_requested = .false.
        n_heat_trans_requested = .false.
        n_salt_trans_requested = .false.
        ldiag_global_tracer_budgets = .false.
        """
        )

    for key, nl in user_nl.items():
        user_nl_file = f"{caseroot}/user_nl_{key}"
        with open(user_nl_file, "a") as fid:
            fid.write(user_nl[key])

    # set ALT_CO2 tracers to CO2 tracers
    if cdr_forcing is not None:
        check_call(
            ["./set-alt-co2.sh", f"{rundir}/{refcase}.pop.r.{refdate}-00000.nc"],
            cwd=scriptroot,
        )

    check_call(
        "module load python && ./case.build --skip-provenance-check",
        cwd=caseroot,
        shell=True,
    )

    return


def create_hr_4p2z_clone(
    case,
    refdate="1999-01-01",
    queue="regular",
    cdr_forcing=None,
    cdr_forcing_file=None,
    clobber=False,
    curtail_output=True,
    stop_n=1,
    stop_option="nyear",
    wallclock="48:00:00",
    resubmit=0,
):
    caseroot = f"{paths['cases']}/{case}"
    assert (
        not os.path.exists(caseroot) or clobber
    ), f"Case {case} exists; caseroot:\n{caseroot}\n"

    if cdr_forcing is not None:
        assert cdr_forcing in ["OAE", "DOR"], f"Unknown CDR forcing: {cdr_forcing}"

    rundir = f"{paths['scratch']}/{case}/run"
    blddir = f"{paths['scratch']}/{case}/bld"
    archive_root = f"{paths['data']}/archive/{case}"

    check_call(["rm", "-fr", caseroot])
    check_call(["rm", "-fr", archive_root])
    check_call(["rm", "-fr", f"{paths['scratch']}/{case}"])

    refcase = "g.e22.TL319_t13.G1850ECOIAF_JRA_HR.4p2z.001"

    if machine_name == "perlmutter":
        refcaserest_root = "/global/cfs/projectdirs/m4746/Datasets/HR_4p2z/rest"
    
    elif machine_name == "anvil":
        refcaserest_root = "/anvil/projects/x-ees250129/Datasets/HR_4p2z/rest"
    
    else:
        raise ValueError("unknown machine")
        
    compset = "G1850ECOIAF_JRA_HR"
    res = "TL319_t13"

    check_call(
        " ".join(
            [
                "module load python",
                "&&",
                "./create_newcase",
                "--compset",
                compset,
                "--case",
                caseroot,
                "--res",
                res,
                "--machine",
                machine_name,
                "--compiler",
                "intel",
                "--project",
                account,
                "--queue",
                queue,
                "--walltime",
                wallclock,
                "--handle-preexisting-dirs",
                "r",
                "--run-unsupported",
            ]
        ),
        shell=True,
        cwd=f"{paths['src']}/cime/scripts",
    )

    def xmlchange(arg, opt="", force=False):
        """call xmlchange"""
        check_call(
            f"module load python && ./xmlchange {opt} {arg}", cwd=caseroot, shell=True
        )

    xmlchange(f"RUNDIR={rundir}")
    xmlchange(f"CIME_OUTPUT_ROOT={paths['scratch']}")

    xmlchange(f"DIN_LOC_ROOT={cesm_inputdata}")
    xmlchange(f"DOUT_S_ROOT='{paths['data']}/archive/$CASE'")

    xmlchange(f"OCN_CHL_TYPE=prognostic")
    xmlchange(f"OCN_CO2_TYPE=diagnostic")
    xmlchange(f"CCSM_BGC=CO2A")

    xmlchange(f"RUN_TYPE=hybrid")
    xmlchange(f"RUN_REFCASE={refcase}")
    xmlchange(f"RUN_REFDATE={refdate}")
    xmlchange(f"RUN_STARTDATE={refdate}")

    xmlchange(f"OCN_TRACER_MODULES=ecosys")

    xmlchange(f"CICE_CONFIG_OPTS='-trage 0'", opt="-a")

    xmlchange(f"DATM_MODE=CORE_IAF_JRA")
    xmlchange(f"DROF_MODE=IAF_JRA")
    xmlchange(f"DATM_CO2_TSERIES=omip")
    xmlchange(f"CPL_SEQ_OPTION=RASM_OPTION1")

    xmlchange(f"NTASKS_OCN=25654")

    xmlchange(f"STOP_N={stop_n}")
    xmlchange(f"STOP_OPTION={stop_option}")
    xmlchange(f"REST_N={stop_n}")
    xmlchange(f"REST_OPTION={stop_option}")
    xmlchange(f"RESUBMIT={resubmit}")
    xmlchange(f"JOB_WALLCLOCK_TIME={wallclock}", opt="--subgroup case.run")

    xmlchange(f"CHARGE_ACCOUNT={account}")
    xmlchange(f"PROJECT={account}")
    xmlchange(f"JOB_QUEUE={queue}")

    check_call(
        "module load python && ./case.setup",
        cwd=caseroot,
        shell=True,
    )

    # refcase SourceMods
    # check_call(
    #    f"cp -vr {scriptroot}/input/cesm2.2.0/cases/{refcase}/SourceMods/* {caseroot}/SourceMods",
    #    shell=True,
    # )

    ## TODO: add CDR source mods

    # list user_nl files
    user_nl_files = glob(f"{scriptroot}/input/cesm2.2.0/cases/{refcase}/user_nl*")
    for file in user_nl_files:
        file_out = os.path.join(caseroot, os.path.basename(file))
        print(f"{file} -> {file_out}")
        with open(file, "r") as fid:
            file_str = fid.read().replace(
                "/glade/p/cesmdata/cseg/inputdata", cesm_inputdata
            )
        with open(file_out, "w") as fid:
            fid.write(file_str)

    # user_datm files
    user_datm_files = glob(f"{scriptroot}/input/cesm2.2.0/cases/{refcase}/user_datm.*")
    for file in user_datm_files:
        file_out = os.path.join(caseroot, os.path.basename(file))
        print(f"{file} -> {file_out}")
        with open(file, "r") as fid:
            file_str = fid.read().replace(
                "/work/02503/edwardsj/CESM/inputdata", cesm_inputdata
            )
        with open(file_out, "w") as fid:
            fid.write(file_str)

    # namelist
    user_nl = dict()

    tavg_contents_override_file = f"{scriptroot}/input/cesm2.2.0/cases/{refcase}/tavg_contents/tx0.1v3_tavg_contents_no5day_4p2z"
    n_tavg_streams = 3

    user_nl["pop"] = textwrap.dedent(
        f"""\
        ! tavg contents
        tavg_contents_override_file = '{tavg_contents_override_file}'
        n_tavg_streams = {n_tavg_streams}
        
        ! ndep from shr_stream
        ndep_data_type = 'shr_stream'
        ndep_shr_stream_file = '{cesm_inputdata}/ocn/pop/tx0.1v3/forcing/ocn_Ndep_transient_forcing_x0.1_241004.nc'
        ndep_shr_stream_scale_factor = 7.1429e+06
        ndep_shr_stream_year_align = 1958
        ndep_shr_stream_year_first = 1958
        ndep_shr_stream_year_last = 2021
        """
    )

    for key, nl in user_nl.items():
        user_nl_file = f"{caseroot}/user_nl_{key}"
        with open(user_nl_file, "a") as fid:
            fid.write(user_nl[key])

    # copy restarts
    check_call(
        f"cp -v {refcaserest_root}/{refdate}-00000/* {rundir}/.",
        shell=True,
    )

    check_call(
        "module load python && ./case.build --skip-provenance-check",
        cwd=caseroot,
        shell=True,
    )


def case_status(vintage=None, caselist=None, path_cases=None):
    """look at all CaseStatus files and extract information"""

    if path_cases is None:
        path_cases = paths["cases"]

    caseroots = sorted(glob(f"{path_cases}/*"))

    if vintage is not None:
        n = len(vintage) + 1
        caseroots = [c for c in caseroots if c[-n:] == f".{vintage}"]

    if caselist is not None:
        caseroots = [c for c in caseroots if os.path.basename(c) in caselist]

    rows = []
    df_caseinfo = None

    # get the queue status
    job_info = machine.queue_info()

    for caseroot in caseroots:
        case = os.path.basename(caseroot)
        CaseStatus = f"{caseroot}/CaseStatus"
        timing_files = sorted(glob(f"{caseroot}/timing/cesm_timing.{case}.*"))

        lines = []
        if os.path.exists(CaseStatus):
            with open(CaseStatus, "r") as fid:
                lines = fid.readlines()

        timestamp_run = None
        for l in lines:
            if "case.run success" in l:
                datetime_str = l[:19]
                timestamp_run = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")

        row_data = dict(
            case=case,
            build=any("case.build success" in line for line in lines),
            submitted=any("case.submit success" in line for line in lines),
            run_completed=any("case.run success" in line for line in lines),
            archive=any("st_archive success" in line for line in lines),
            error=any("ERROR" in line for line in lines),
            error_count=sum(["ERROR" in line for line in lines]),
            timestamp_run=timestamp_run,
            JobId=None,
            JobState=None,
            Queued=False,
        )

        if case in job_info:
            row_data["Queued"] = True
            row_data["JobId"] = job_info[case]["JobId"]
            row_data["JobState"] = job_info[case]["JobState"]

        yrs_per_day = np.nan
        cost = np.nan
        if timing_files:
            for f in timing_files:
                with open(f, "r") as fid:
                    lines = fid.readlines()

            yrs_per_day = np.array(
                [np.float64(l.split()[2]) for l in lines if "Model Throughput:" in l]
            )
            yrs_per_day = yrs_per_day.mean()

            cost = np.array(
                [np.float64(l.split()[2]) for l in lines if "Model Cost:" in l]
            )
            cost = cost.mean()

        row_data["yr_per_day"] = yrs_per_day
        row_data["pe-hr_per_yr"] = cost
        rows.append(row_data)

    if rows:
        df_caseinfo = pd.DataFrame(rows).set_index("case")

    return df_caseinfo
