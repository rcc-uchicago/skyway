Here are my instructions for principal components analysis (PCA) on a
large (single-cell RNA-seq) gene expression data set. In these
instructions, "cnetid" should be replaced by your actual CNET id.

1. Connect to `skyway.rcc.uchicago.edu`.

2. Copy files `pulseseq_pca.sbatch`, `pulseseq_pca.R` and
   `pulseseq_functions.R` to `/cloud/rcc-aws/cnetid`.

3. Switch to that directory on skyway.

4. Download the "pulse-seq" data, `GSE103354_PulseSeq_UMI_counts.rds`,
   from the Gene Expression Omnibus (GEO) website, accession
   GSE103354.

5. Run `sbatch crossprod.sbatch`

6. After approximately a minute or less, you should see a new file
`crossprod.out`. The contents of this text file should look
something like this:

```
Loading R.
Running R computations.
   user  system elapsed
   91.858   2.588  13.329
```
