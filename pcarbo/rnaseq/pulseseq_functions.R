# This file implements functions to import, prepare and analyze data
# accompanying the Montoro et al (2018) paper, "A revised airway
# epithelial hierarchy includes CFTR-expressing ionocytes."

# This function imports and prepares the "droplet" data from the
# Montoro et al (2018) paper for analysis in R. The return value is
# list with two list elements: (1) a data frame containing sample
# attributes (specifically, mouse ids, barcodes and tissue labels),
# and (2) an n x p matrix containing gene expression data (read
# counts), where n is the number of samples, and p is the number of
# genes.
#
# This function is known to work for file
# GSE103354_Trachea_droplet_UMIcounts.txt.gz downloaded from the Gene
# Expression Omnibus (GEO) website, accession GSE103354, but only
# after editing the first line so that the column names are "gene",
# "M1_GCTTGAGAAGTCGT_Club", "M1_GGAACACTTTCGTT_Club", etc., to align
# with the columns provided.
#
# Note that all genes (columns) vary in the sample, so there is no
# preprocessing step to remove genes that do not vary in the sample.
read.montoro.droplet.data <- function (file) {
    
  # Load the gene expression data (i.e., the read counts) as an n x p
  # double-precision matrix, where n is the number of samples, and p
  # is the number of genes for which we have expression data (read
  # counts).
  suppressMessages(
    counts <- read_delim(file,delim = "\t",progress = FALSE,
                         col_types = cols(.default = col_double(),
                                          gene     = col_character())))
  class(counts)    <- "data.frame"
  genes            <- counts$gene
  rownames(counts) <- genes
  counts           <- counts[-1]
  counts           <- as.matrix(counts)
  counts           <- t(counts)

  # Extract the barcodes, mouse ids and tissue labels, and create a
  # new data frame containing this info.
  ids       <- rownames(counts)
  ids       <- strsplit(ids,"_")
  mouse.ids <- factor(sapply(ids,function (x) x[1]))
  barcodes  <- sapply(ids,function (x) x[2])
  tissues   <- factor(sapply(ids,function (x) x[3]))
  samples   <- data.frame(mouse.id = mouse.ids,
                          barcode  = barcodes,
                          tissue   = tissues,
                          stringsAsFactors = FALSE)

  # Set the row labels to be the combination of the mouse ids and
  # barcodes.
  rownames(counts) <- paste(mouse.ids,barcodes,sep = "_")
  
  # Return a data frame containing the sample attributes (samples),
  # and a matrix containing the gene expression data (counts).
  return(list(samples = samples,counts = counts))
}

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

# Create a scatterplot showing Montoro et al "droplet" gene expression
# samples projected onto two principal components (PCs), with color
# and shape varying according to the tissue label of the samples.
plot.droplet.pcs <- function (tissues, pcs, x = "PC1", y = "PC2",
                              guide = "legend") {

  # Specify the colours and shapes used in the scatterplot.
  colors <- c("#E69F00","#56B4E9","#009E73","#F0E442","#0072B2",
              "#D55E00","#CC79A7")
  shapes <- c(19,17,8,1)
  shapes <- rep(shapes,2)

  # Collect all the data used for the plot into a single data frame.
  pdat <- cbind(data.frame(tissue = tissues),pcs)

  # Create the scatterplot.
  return(ggplot(pdat,aes_string(x = x,y = y,color = "tissue",
                                shape = "tissue")) +
         geom_point() +
         scale_x_continuous(breaks = NULL) +
         scale_y_continuous(breaks = NULL) +
         scale_color_manual(values = colors,guide = guide) +
         scale_shape_manual(values = shapes,guide = guide) +
         theme_cowplot(font_size = 12) +
         theme(legend.title = element_blank()))
}

# Create a scaterrplot showing Montoro et al "pulseseq" gene
# expression samples projected onto principal components (PCs), with
# color and shape varying according to the specified factor ("labels").
plot.pulseseq.pcs <-
  function (labels, pcs, x = "PC1", y = "PC2", guide = "legend",
            colors = rep(c("#E69F00","#56B4E9","#009E73","#F0E442",
                            "#0072B2","#D55E00","#CC79A7"),2),
            shapes = rep(c(1,2,4),5)) {

  # Collect all the data used for the plot into a single data frame.
  pdat <- cbind(data.frame(label = labels),pcs)

  # Create the scatterplot.
  return(ggplot(pdat,aes_string(x = x,y = y,color = "label",
                                shape = "label")) +
         geom_point() +
         scale_x_continuous(breaks = NULL) +
         scale_y_continuous(breaks = NULL) +
         scale_color_manual(values = colors,guide = guide) +
         scale_shape_manual(values = shapes,guide = guide) +
         theme_cowplot(font_size = 12) +
         theme(legend.title = element_blank()))
}
