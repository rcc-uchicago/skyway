Here are my instructions for running principal components analysis
(PCA) on a large (single-cell RNA-seq) gene expression data set. In
these instructions, "cnetid" should be replaced by your actual CNET
id.

1. Connect to `skyway.rcc.uchicago.edu`.

2. Copy files `pulseseq_pca.sbatch`, `pulseseq_pca.R` and
   `pulseseq_functions.R` to `/cloud/rcc-aws/cnetid`.

3. Switch to that same directory on skyway.

4. Download the "pulse-seq" data, `GSE103354_PulseSeq_UMI_counts.rds`,
   from the Gene Expression Omnibus (GEO) website, accession
   GSE103354.

5. Run `sbatch pulseseq_pca.sbatch`.

6. After about ten minutes or less, you should see a new file
`pulseseq_pca.out`. The contents of this text file should look
something like this:

```
Loading R.
Running R computations.
Reading read count data.
Number of genes: 19853
Number of samples: 66265
Proportion of counts that are non-zero: 10.1%.
Computing top 4 PCs from count data.
Computation took 79.36 seconds.
Summarizing PCA results.
                          PC1    PC2    PC3    PC4
Explained variance     50.240 33.660 15.904 10.727
Standard deviations     7.088  5.802  3.988  3.275
Proportion of variance  0.046  0.031  0.014  0.010
Cumulative proportion   0.046  0.076  0.091  0.100
```
