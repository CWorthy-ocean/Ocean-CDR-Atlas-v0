import os
import subprocess


# config.yml
project_name = "Ocean-CDR-Atlas-v0"
project_sname = "cdr-atlas-v0"
branch = project_sname
codename = "cesm2.2.0"
remote = "git@github.com:CWorthy-ocean/cesm2.2.0.git"
kernel_name = "python3"

machine_name = "anvil"

if machine_name == "perlmutter":
    account = "m4632"
    dir_project_root = f"/global/cfs/projectdirs/m4746/Projects/{project_name}"
    cesm_inputdata = f"/global/cfs/projectdirs/m4746/Datasets/cesm-inputdata"
    cesm_inputdata_ro = f"/dvs_ro/cfs/projectdirs/m4746/Datasets/cesm-inputdata" # TODO: read-only give better performance, but requires staging data
elif machine_name == "anvil":
    account = "ees250129"
    dir_project_root = f"/anvil/projects/x-ees250129/{project_name}"
    cesm_inputdata = f"/anvil/projects/x-ees250129/Datasets/cesm-inputdata"
    cesm_inputdata_ro = cesm_inputdata
else:
    raise ValueError(f"unknown machine: {machine_name}")


# house keeping
USER = os.environ["USER"]
assert machine_name in ["perlmutter", "anvil"]

# directories that might not exist
paths = dict()
paths["cesm_inputdata"] = cesm_inputdata
paths["cesm_inputdata_ro"] = cesm_inputdata_ro
paths["scratch"] = f"{os.environ['SCRATCH']}/{project_name}"
paths["data"] = f"{dir_project_root}/data"
paths["codes"] = (
    f"{dir_project_root}/codes"  # does this need to be known outside config.py?
)
paths["cases"] = f"{dir_project_root}/cases"

for path in paths.values():
    os.makedirs(path, exist_ok=True)

# directories that exist
paths["workflow"] = os.path.dirname(os.path.realpath(__file__))
paths["src"] = os.path.join(paths["codes"], codename)

# check out the code
if not os.path.exists(paths["src"]):
    # clone the repo
    p = subprocess.Popen(
        f"git clone {remote}",
        shell=True,
        cwd=paths["codes"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = p.communicate()

    # crude error handling
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    if p.returncode != 0:
        raise Exception("git error")

    if branch:
        # checkout branch
        p = subprocess.Popen(
            f"git checkout {branch}",
            shell=True,
            cwd=paths["codes"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = p.communicate()

        # crude error handling
        if stdout:
            print(stdout)
        if stderr:
            print(stderr)
        if p.returncode != 0:
            raise Exception("git error")
