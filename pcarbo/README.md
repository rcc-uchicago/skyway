Here are my instructions for running a small test of multithreaded
OpenBLAS matrix computations in R on an AWS node with 8 CPUs
("c5.4xlarge"). In these instructions, "cnetid" should be replaced by
your actual CNET id.

1. ssh to skyway.rcc.uchicago.edu

2. Copy `crossprod.sbatch` and `crossprod.R` to `/cloud/rcc-aws/cnetid`.

3. Run `sbatch crossprod.sbatch`

4. After less than a minute, you should see a new file
`crossprod.out`. The contents of this text file should look
something like this:

```
Loading R.
Running R computations.
   user  system elapsed
   91.858   2.588  13.329
```
