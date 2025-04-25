#!/bin/bash


#SBATCH --job-name=cdr-atlas-proc       # Job name
#SBATCH --output=cdr-atlas-proc-%j.log  # Standard output and error log
#SBATCH --nodes=1                       # Request 1 node
#SBATCH --ntasks-per-node=256
##SBATCH --exclusive
#SBATCH --time=00:30:00                 # Request 24 hours runtime
#SBATCH --qos=debug                   # Use regular QoS as requested
#SBATCH --constraint=cpu                # Use CPU nodes as you've been doing


set -e

# Print job details for logging
echo "Job ID: $SLURM_JOB_ID"
echo "Running on: $SLURM_JOB_NODELIST"
echo "Start time: $(date)"

# Load necessary modules
module load conda 

# Activate conda environment
conda activate dor

# Navigate to the project directory
cd $HOME/Ocean-CDR-Atlas-v0/workflows/dor-atlas

# # Set the number of worker processes to match allocated CPUs
# export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# Run the Python script with appropriate parameters
echo "Starting data processing at $(date)"
# time python research_grade_data.py process-all --polygon 1
time python dor_cli.py vis build-pyramid -p 1 --output-store s3://carbonplan-dor-efficiency/v2/store2.zarr/

# Print completion information
echo "Processing completed at $(date)"


