#!/bin/bash

#SBATCH --job-name=peter
#SBATCH --output=crossprod.out
#SBATCH --partition=rcc-aws
#SBATCH --account=rcc-aws
#SBATCH --exclusive
#SBATCH --ntasks=1
#SBATCH --constraint=c5.4xlarge

echo "Loading R."
module load openblas/0.3
module load r/3.5

echo "Running R computations."
cd /cloud/rcc-aws/pcarbo
Rscript crossprod.R
