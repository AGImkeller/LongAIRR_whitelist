# LongAIRR-Whitelist <img src="./docs/images_design/images/longairr_logo_small.png" align="right" height="150" alt="logo" />

[![bioRxiv](https://img.shields.io/badge/bioRxiv-10.64898%2F2026.06.22.733709-B31B1B.svg)](https://doi.org/10.64898/2026.06.22.733709)
[![LongAIRR GitHub](https://img.shields.io/badge/LongAIRR-GitHub-2ea44f.svg)](https://github.com/AGImkeller/LongAIRR)
[![Documentation Status](https://app.readthedocs.org/projects/longairr/badge/?version=latest)](https://longairr.readthedocs.io/en/latest/)

**LongAIRR-Whitelist** is a companion package to create sample-specific Visium HD 3′ spatial barcode (SPBC) indices.
These observed-spbc whitelists are used during the annotation of UMI and SPBC barcodes within the [LongAIRR framework](https://github.com/AGImkeller/LongAIRR).

---

> [!NOTE]
> **LongAIRR Documentation** about creating Spatial Barcode Whitelist 
> for Visium HD 3' datasets using LongAIRR_Whitelist: [LongAIRR ReadTheDocs](https://longairr.readthedocs.io/en/latest/in_depth/inputs_outputs/spbc_hd3/).
> **Installation instructions and exemplary Snakemake/LongAIRR_Whitelist workflows are provided below.**

---
---

### Overview

**This package currently provides:**

* Preprocessing helpers for Visium HD 3′ **long-read** AIRR input [ONT datasets]

* Documentation for the usage of 10x Genomics SpaceRanger using the preprocessed long-read AIRR Visium HD 3' dataset.

* A `build-index` module that creates a LongAIRR-facing SPBC-whitelist index from SpaceRanger's `possorted_genome_bam.bam`

The generated SQLite index maps observed raw Space Ranger barcode sequences (`CR`) to corrected Visium HD barcode identifiers (`CB` / `sb`) and is intended for downstream use in [LongAIRR](https://github.com/AGImkeller/LongAIRR).

> [!IMPORTANT]
>    LongAIRR_whitelist currently only supports **ONT-datasets**.
>    Since the SpaceRanger-preprocessing for long-reads is platform-dependent,
>    PacBio datasets would have to be prepared externally following this github repository: [10XGenomics/visium-hd-long-reads](https://github.com/10XGenomics/visium-hd-long-reads/).
>    The output from this would be ready to process with SpaceRanger and then passed to longairrwhitelist build-index for index generation.

___

### Installation

10x Genomics SpaceRanger is not installed by **LongAIRR_whitelist**. Install SpaceRanger manually from [10x Genomics](https://www.10xgenomics.com/support/software/space-ranger/downloads) and make sure `spaceranger` is available on `PATH`.

#### Clone repository

```bash
git clone https://github.com/AGImkeller/LongAIRR_whitelist.git
cd LongAIRR_whitelist
```
___

#### Example installation for ONT

```bash
bash install.sh
source ~/.bashrc
conda activate longairr_whitelist
longairrwhitelist check
```

This installs the ONT environment with Percula, fastcat, samtools, pysam, and Snakemake.

___
[**BACK TO TOP**](#Table-of-Content)
___

### Example Snakemake workflow

> [!IMPORTANT]
> Refer to the [LongAIRR documentation](https://longairr.readthedocs.io/en/latest/ in_depth/inputs_outputs/spbc_hd3/)
> to get information about manually using **LongAIRR-Whitelist**.

An example Snakemake workflow is provided for the ONT path:

```text
longairr_whitelist_example_workflow/snakemake/
├── Snakefile
├── config.yaml
└── README.md
```

The example workflow streamlines the following steps:

```text
longairrwhitelist preprocess
spaceranger count --create-bam=true
longairrwhitelist build-index
```

All necessary runtime-parameters can be configured in the **config.yaml**.
Run the workflow with:

```
conda activate longairr_whitelist
```

```
snakemake --cores 8 -s /path/to/longairr_whitelist_example_workflow/snakemake/snakefile_whitelist --configfile /path/to/longairr_whitelist_example_workflow/snakemake/config.yaml
```

> [!IMPORTANT]
> Use paths on **local storage** for the configured output folders.
> Especially for SpaceRanger output directories, SQLite index creation,
> and Snakemake working/output directories.
> Avoid CIFS/SMB/network-mounted paths for active SpaceRanger or SQLite output, 
> because SpaceRanger/Martian can fail when creating symlinks and SQLite can fail with  database locking issues on some mounted filesystems.

___
[**BACK TO TOP**](#Table-of-Content)
___

# Citation

If you use LongAIRR in your work, please cite:

> Schuck J, Ortega Iannazzo S, Mahmoud Z, Gwellem Anchang C, Hasse LM,
> Weber K, and Imkeller K. Consistent consensus-based annotation of spatial
> adaptive immune receptor repertoires from long-read sequencing using
> LongAIRR. Preprint at
> [bioRxiv](https://www.biorxiv.org/content/10.64898/2026.06.22.733709v1)
> (2026). DOI:
> [10.64898/2026.06.22.733709](https://doi.org/10.64898/2026.06.22.733709).

---

# Authors

[Jonas Schuck](https://github.com/Jonas-Schuck), [Katharina Imkeller](https://github.com/imkeller)

**Contact**: Schuck@med.uni-frankfurt.de

**Issues/Bug-report**: [LongAIRR-Issues](https://github.com/AGImkeller/LongAIRR/issues)

___
[**BACK TO TOP**](#Table-of-Content)
___