#!/bin/bash

#SBATCH --output=crossprod.out
#SBATCH --partition=rcc-aws
#SBATCH --account=rcc-aws
#SBATCH --constraint=c36

echo "Loading R."
module load openblas/0.3
module load r/3.5

echo "Running R computations."
cd /cloud/rcc-aws/pcarbo
Rscript crossprod.R
