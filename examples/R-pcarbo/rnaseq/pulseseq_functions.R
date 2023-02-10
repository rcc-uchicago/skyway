# This function imports and prepares the "pulseseq" data from the
# Montoro et al (2018) paper for analysis in R. The return value is
# list with two list elements: (1) a data frame containing sample
# attributes (specifically, sample ids, barcodes, inferred tissue
# labels, mouse ids, lineage labels, and profiling time-point), and
# (2) an n x p matrix containing gene expression data (read counts),
# where n is the number of samples, and p is the number of genes.
#
# This function is known to work for file
# GSE103354_PulseSeq_UMI_counts.rds downloaded from the Gene
# Expression Omnibus (GEO) website, accession GSE103354.
read.montoro.pulseseq.data <- function (file) {
  counts <- t(readRDS(file))

  # Remove genes that are expressed in only a very small number of
  # samples.
  x      <- colSums(counts > 0)
  cols   <- which(x > 2)
  counts <- counts[,cols]

  # Extract some information from the sample ids: barcode, tissue,
  # mouse, lineage and time-point (tp).
  ids <- rownames(counts)
  ids <- strsplit(ids,"_")
  samples <-
    data.frame(id      = sapply(ids,function (x) paste(x[1:4],collapse = "-")),
               barcode = sapply(ids,function (x) x[1]),
               tissue  = factor(sapply(ids,function (x) tolower(x[5]))),
               mouse   = factor(sapply(ids,function (x) x[3])),
               lineage = factor(sapply(ids,function (x) x[4])),
               tp = factor(sapply(ids,function(x) substr(x[2],3,length(x)))),
               stringsAsFactors = FALSE)
  rownames(counts) <- samples$id

  # Return a data frame containing the sample attributes (samples),
  # and a matrix containing the gene expression data (counts).
  return(list(samples = samples,counts = counts))
}
