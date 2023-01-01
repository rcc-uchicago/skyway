#!/bin/sh

#SBATCH --job-name=SA_TEST
#SBATCH --partition=rcc-aws
#SBATCH --account=rcc-aws
#SBATCH --exclusive
#SBATCH --nodes=1
#SBATCH --cpus-per-task=36
#SBATCH --time=00:58:00
#SBATCH --constraint=c5.18xlarge

cd $SLURM_SUBMIT_DIR
module load parallelstudio/2018.up2

./simann_earnings
