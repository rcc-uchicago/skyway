I attempted two small tests:

1) Connect to Skyway and find pi using a simple C algorithm.
2) Connect to Skyway, start R and run a simple MPI R script.

I found Yuxing's instructions fine for connecting to Skyway.

1. Move the scripts (.sbatch, .R and .c) into my home directory on Midway.

1. Ssh to `skyway.rcc.uchicago.edu`.

2. Copy all files from my home directory to `/cloud/rcc-aws/jcarlsen`.

3. Switch to that directory on skyway.

4. Run `pi_reduce.sbatch`.

This failed because the modules intelmpi and mkl have not yet been built on Skyway.

5. Start R with `module load R` and `R` -- loads fine (R version 3.5.1).

6. Run `rmpi_test.R`.

This failed as I could not load the "Rmpi" library -- and it cannot be installed from within R because the default directory for R libraries does not allow write access.

Peter noted that if you specify a directory where you do have write access, you can force R to install the library in that directory, and then it should work.


