# Process raw DOR data into compressed research-grade dataset and create visualization stores 


## Environment Setup

To set up the environment for the Ocean CDR Atlas, follow these steps:

1. **Clone the Repository**: 
   ```bash
   git clone https://github.com/CWorthy-ocean/Ocean-CDR-Atlas-v0
   ```
2. **Set Up the Environment**: 
   ```bash
    cd Ocean-CDR-Atlas-v0/workflows/dor-atlas
    conda env create -f environment.yml
    conda activate dor
    ```

## Command-Line Interface (CLI) Tool

The `dor_cli.py` command-line interface (CLI) tool is used to manage the data processing workflow. It provides several commands to process raw DOR data into research-grade datasets and create visualization stores. The main commands are

```bash
(dor) abanihi@login31:~/Ocean-CDR-Atlas-v0/workflows/dor-atlas> python dor_cli.py --help
                                                                                                                                                                                                                                                    
 Usage: dor_cli.py [OPTIONS] COMMAND [ARGS]...                                                                                                                                                                                                      
                                                                                                                                                                                                                                                    
 CDR Atlas Data Processing Tool: Process and build visualization data                                                                                                                                                                               
                                                                                                                                                                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.                                                                                                                                                                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the installation.                                                                                                                                   │
│ --help                        Show this message and exit.                                                                                                                                                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ setup-environment   Setup and validate the processing environment.                                                                                                                                                                               │
│ research-data       Process research-grade data                                                                                                                                                                                                  │
│ vis                 Generate visualization pyramids                                                                                                                                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### Verify Your Setup
To verify your setup, you can run the following command:

```bash
python dor_cli.py setup-environment
```

This command checks the environment and ensures that all necessary dependencies are installed. It will also create a temporary directory for processing data. You should see output similar to the following:

```bash
                                                                            Environment Setup                                                                            
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Directory                            ┃ Path                                                                                                               ┃ Status    ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ scratch                              │ /pscratch/sd/a/abanihi/dor                                                                                         │ ✓ Exists  │
│ joblib_cache_dir                     │ /pscratch/sd/a/abanihi/dor/joblib                                                                                  │ ✓ Exists  │
│ dask_log_dir                         │ /pscratch/sd/a/abanihi/dask/logs                                                                                   │ ✓ Exists  │
│ dask_local_dir                       │ /pscratch/sd/a/abanihi/dask/local-dir                                                                              │ ✓ Exists  │
│ compressed_data_dir                  │ /global/cfs/projectdirs/m4746/Datasets/Ocean-CDR-Atlas-v0/DOR-Efficiency-Map/research-grade-compressed/experiments │ ✓ Exists  │
│ data_archive_dir                     │ /global/cfs/projectdirs/m4746/Projects/Ocean-CDR-Atlas-v0/data/archive                                             │ ✓ Exists  │
│ store_1_path                         │ /pscratch/sd/a/abanihi/dor/store1b.zarr                                                                            │ ✗ Missing │
│ store_2_path                         │ /pscratch/sd/a/abanihi/dor/store2.zarr                                                                             │ ✗ Missing │
│ cumulative_fg_co2_percent_store_path │ /pscratch/sd/a/abanihi/dor/cumulative_FG_CO2_percent.zarr                                                          │ ✗ Missing │
└──────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────┘
All required modules available
Environment setup is complete and valid!
```

### Process raw DOR data into compressed research-grade dataset

To process raw DOR data into a compressed research-grade dataset, you can use the same `dor_cli.py` command-line interface (CLI) tool. The CLI provides several commands to manage the data processing workflow. The main commands are:

```bash
(dor) abanihi@login31:~/Ocean-CDR-Atlas-v0/workflows/dor-atlas> python dor_cli.py research-data --help
                                                                                                                                                                                                                                                    
 Usage: dor_cli.py research-data [OPTIONS] COMMAND [ARGS]...                                                                                                                                                                                        
                                                                                                                                                                                                                                                    
 Process research-grade data                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                                                                                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ list-cases          List all available cases with their metadata.                                                                                                                                                                                │
│ process-case        Process a single case, compressing and saving all associated files.                                                                                                                                                          │
│ process-all-cases   Process all available cases or a filtered subset.                                                                                                                                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

There are 690 polygons with four intervention dates (01, 04, 07, 10) in the dataset. Each case corresponds to a specific polygon and intervention date. This means there are 2760 cases in total. The CLI tool allows you to process all cases or filter by specific polygons or dates. To process a specific polygon, you can use the `process-all-cases` command with the `--polygon` option. For example, to process all cases for polygon 100, you would run:

```bash
python dor_cli.py research-data process-all-cases --polygon 123
```


To process all cases, you can simply run:

```bash
python dor_cli.py research-data process-all-cases
```


#### Running the processing command via batch job

To run the processing command via batch job, you can use the `single-case-batch-job.sh` script. This script is designed to submit batch jobs for processing individual cases. You can specify the polygon ID and the number of cases to process. For example, to process cases for polygon 123, you would update the `single-case-batch-job.sh` script with the desired polygon ID and then submit the job using the `sbatch` command:

```bash
sbatch single-case-batch-job.sh
```

To facilitate the processing of multiple cases, you can also use the `submit-polygon-jobs.sh` script. 

```bash
(dor) abanihi@login34:~/Ocean-CDR-Atlas-v0/workflows/dor-atlas> bash submit-polygon-jobs.sh --help
Usage: submit-polygon-jobs.sh [options]
Submits jobs for processing polygons within QoS limits

Options:
  -s, --start NUM      Start polygon ID (default: 0)
  -e, --end NUM        End polygon ID (default: 689)
  -w, --wait NUM       Seconds to wait between checks (default: 60)
  -h, --help           Show this help message

Press Ctrl+C at any time to stop the script.
```

This script will submit jobs for processing polygons within the specified range. You can adjust the `--start` and `--end` options to specify the range of polygons you want to process. For example, to process polygons from 0 to 689, you would run:

```bash
bash submit-polygon-jobs.sh --start 0 --end 689
```
This will submit jobs for all polygons in the dataset. The script will wait for a specified number of seconds between checks to avoid overwhelming the system.

### Generate visualization pyramids

To generate visualization pyramids, you can use the `vis` command in the CLI tool. The `vis` command provides several options for generating and managing different types of visualization stores. The main commands are:

```bash
(dor) abanihi@login34:~/Ocean-CDR-Atlas-v0/workflows/dor-atlas> python dor_cli.py vis --help
 Usage: dor_cli.py vis [OPTIONS] COMMAND [ARGS]...                                                                                                                                                                                                  
                                                                                                                                                                                                                                                    
 Generate visualization pyramids                                                                                                                                                                                                                    
                                                                                                                                                                                                                                                    
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                                                                                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ create-template-store1   Create a template for the DOR efficiency visualization store.                                                                                                                                                           │
│ create-template-store2   Create a template for the pyramid visualization store.                                                                                                                                                                  │
│ create-template-store3   Create a template for the cumulative FG CO2 percent store.                                                                                                                                                              │
│ populate-store1          Populate the DOR efficiency visualization store.                                                                                                                                                                        │
│ populate-store2          Populate the visualization pyramid store                                                                                                                                                                                │
│ populate-store3          Populate the cumulative FG CO2 percent store.                                                                                                                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```


## Joblib Caching 


The code base includes an implementation for a caching mechanism using [`joblib.Memory`](https://joblib.readthedocs.io/en/stable/generated/joblib.Memory.html) that can significantly improve performance by avoiding redundant computations. Here's how to leverage this feature effectively:

The caching system works by:

- Storing the inputs and outputs of expensive function calls
- Returning cached results when the same function is called with identical inputs
- Persisting cache across sessions in the joblib_cache_dir


### How Caching Works

No special syntax is needed to use cached functions - the system automatically retrieves cached results when available:
The `setup_memory` function initializes a persistent cache in the specified directory:

When a function is wrapped with `memory.cache()`, joblib:

- Computes a hash of the function and its arguments
- Checks if results for this hash exist in the cache
- Returns cached results if available
- Otherwise, executes the function and stores results for future use


## zarr v2 vs v3 

- store 2b requires using zarr v2 because of the string encoding discrepancy introduced by zarr v3


## Transfering data from Perlmutter's filesytem to Source Coop Bucket in AWS

To transfer data from Perlmutter's filesystem to a Source Coop bucket in AWS, you can use the `s5cmd sync` command. This command allows you to synchronize files between your local filesystem and the S3 bucket. The `s5cmd` tool will be installed in the `dor` conda environment.

To transfer files, you can use the following command:

```bash
s5cmd --endpoint-url https://data.source.coopsync /path/to/local/directory s3://your-bucket-name/path/to/destination
```
Replace `/path/to/local/directory` with the path to the local directory you want to transfer, and `s3://your-bucket-name/path/to/destination` with the S3 bucket and destination path.

Note that you will need to configure your AWS credentials to allow access to the S3 bucket. You can do this by generating API keys from `https://source.coop/YOUR_USERNAME/manage` and running the following command:

```bash
aws configure
```

This command will prompt you for your AWS Access Key ID, Secret Access Key, and default region. Make sure to enter the correct values for your Source Coop account. Once you have configured your AWS credentials, you can use the `s5cmd` command to transfer files to the S3 bucket.


