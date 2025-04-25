#!/bin/bash

echo "Starting scheduler..."

scheduler_file=$SCRATCH/scheduler_file.json
rm -f $scheduler_file

module load python
conda activate dor

#start scheduler
DASK_DISTRIBUTED__COMM__TIMEOUTS__CONNECT=3600s \
DASK_DISTRIBUTED__COMM__TIMEOUTS__TCP=3600s \
dask scheduler \
    --interface hsn0 \
    --scheduler-file $scheduler_file &

dask_pid=$!

# Wait for the scheduler to start
sleep 5
until [ -f $scheduler_file ]
do
     sleep 5
done

echo "Starting workers"

#start scheduler
DASK_DISTRIBUTED__COMM__TIMEOUTS__CONNECT=3600s \
DASK_DISTRIBUTED__COMM__TIMEOUTS__TCP=3600s \
srun dask worker \
--scheduler-file $scheduler_file \
    --interface hsn0 \
    --nworkers 1 \
    --nthreads 1

echo "Killing scheduler"
kill -9 $dask_pid

