Here are my instructions for running a small test of multithreaded
OpenBLAS matrix computations in R on an AWS node with 8 CPUs. In these
instructions, "cnetid" should be replaced by your actual CNET id.

1. Connect to `skyway.rcc.uchicago.edu`.

2. Copy files `crossprod.sbatch` and `crossprod.R` to
   `/cloud/rcc-aws/cnetid`.

3. Switch to that directory on skyway.

4. Run `sbatch crossprod.sbatch`.

5. After approximately a minute or less, you should see a new file
`crossprod.out`. The contents of this text file should look
something like this:

```
Loading R.
Running R computations.
   user  system elapsed
   91.858   2.588  13.329
```
