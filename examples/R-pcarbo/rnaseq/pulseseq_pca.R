counts.file <- "GSE103354_PulseSeq_UMI_counts.rds"

# LOAD PACKAGES & FUNCTIONS
# -------------------------
library(Matrix)
library(readr)
library(rsvd)
source("pulseseq_functions.R")

# READ DATA
# ---------
cat("Reading read count data.\n")
out     <- read.montoro.pulseseq.data(counts.file)
samples <- out$samples
counts  <- out$counts
rm(out)

# SUMMARIZE DATA
# --------------
cat(sprintf("Number of genes: %d\n",ncol(counts)))
cat(sprintf("Number of samples: %d\n",nrow(counts)))
cat(sprintf("Proportion of counts that are non-zero: %0.1f%%.\n",
            100*mean(counts > 0)))

# RUN PCA
# -------
cat("Computing top 4 PCs from count data.\n")
counts <- as.matrix(counts)
counts <- log(counts + 1)
timing <- system.time(
  out <- rpca(counts,k = 4,center = TRUE,scale = FALSE,retx = TRUE))
cat(sprintf("Computation took %0.2f seconds.\n",timing["elapsed"]))

# SUMMARIZE RESULTS
# -----------------
cat("Summarizing PCA results.\n")
print(summary(out))
