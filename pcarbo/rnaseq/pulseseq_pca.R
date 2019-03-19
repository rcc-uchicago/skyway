# Instructions for running these computations on skyway:
#
# 1. Download GSE103354_PulseSeq_UMI_counts.rdsfrom the Gene
# Expression Omnibus (GEO) website accession GSE103354.
#
# 2. Copy these files to 
#

# SCRIPT PARAMETERS
# -----------------
data.dir    <- file.path("..","data")
counts.file <- "GSE103354_PulseSeq_UMI_counts.rds"
K           <- 13

# LOAD PACKAGES
# -------------
library(Matrix)
library(readr)
library(rsvd)
source("montoro_functions.R")

# READ DATA
# ---------
counts.file <- file.path(data.dir,counts.file)
out         <- read.montoro.pulseseq.data(counts.file)
samples     <- out$samples
counts      <- out$counts
rm(out)

# SUMMARIZE DATA
# --------------
cat(sprintf("Number of genes: %d\n",ncol(counts)))
cat(sprintf("Number of samples: %d\n",nrow(counts)))
cat(sprintf("Proportion of counts that are non-zero: %0.1f%%.\n",
            100*mean(counts > 0)))

# RUN PCA
# -------
counts <- as.matrix(counts)
counts <- log(counts + 1)
timing <- system.time(
  out <- rpca(counts,k = 20,center = TRUE,scale = FALSE,retx = TRUE))
cat(sprintf("Computation took %0.2f seconds.\n",timing["elapsed"]))
print(summary(out))
