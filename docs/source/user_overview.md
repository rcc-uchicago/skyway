# User Guide
<!-- From these links:
https://cloud-skyway.rcc.uchicago.edu/ -->

This documentation briefly explains how regular users access to Skyway and submit jobs to use cloud services. Please refer to the [Skyway](https://cloud-skyway.rcc.uchicago.edu/) home page for more information and news.


## Gaining Access

You first need an active RCC User account (see [accounts and allocations page](https://rcc.uchicago.edu/accounts-allocations)). Next, you should contact your PI or class instructors for access to Skyway. Alternatively, you can reach out to our Help Desk at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu) for assistance.

## Connecting

Once your RCC User account is active, you log in to the Midway cluster with your `CNetID`
```
  ssh [CNetID]@midway2.rcc.uchicago.edu
```
then log in to Skyway from Midway2:
```
  ssh [CNetID]@skyway.rcc.uchicago.edu
```
If successful, you will get access to the Skyway login node, where you can access to the following locations:

1. `/home/[CNetID]`
This is the temporary home directory (no backup) for users on Skyway. Note, this is NOT the home file system on Midway, so you won’t see any contents from your home directory on midway. Please do NOT store any sizable or important data here. (`TODO`: Add note here about changing $HOME environment variable to `/cloud/aws/[CNetID]`.)
2. `/project` and `/project2`
This is the RCC high-performance capacity storage file systems from Midway, mounted on Skyway, with the same quotas and usages as on Midway. Just as with running jobs on Midway, /project and /project2 should be treated as the location for users to store the data they intend to keep. This also acts as a way to make data accessible between Skyway and midway as the /project and /project2 filesystems are mounted on both systems.
Run `cd /project/<labshare>` or `/project2/<labshare>`, where `<labshare>` is the name of the lab account, to access the files by your lab or group. This will work even if the lab share directory does not appear in a file listing, e.g., `ls /project`.
3. `/cloud/[cloud]/[CNetID]`
Options of [cloud]: aws or gcp
This is the cloud scratch folder (no backup), which is intended for read/write of cloud compute jobs. For example, with Amazon cloud resources (AWS) The remote cloud S3 AWS bucket storage is mounted to Skyway at this path. Before submitting jobs to the cloud compute resources, users must first stage the data, scripts and executables their cloud job will use to the /cloud/aws/[CNetID] folder. After running their cloud compute job, users should then copy the data they wish to keep from the /cloud/aws/[CNetID] folder back to their project folder. Similarly, if users are using Google Cloud Platform (GCP), the scratch folder /cloud/gcp/[CNetID] should be used.

You can create your own folders, upload data, write and compile codes, prepare job scripts and submit jobs in a similar manner to what you do on [Midway](https://rcc.uchicago.edu/docs/using-midway/index.html).

Skyway provides compiled software packages (i.e. `modules`) that you can load to build your codes or run your jobs. The list of the modules is given in the [Skyway](https://cloud-skyway.rcc.uchicago.edu/) home page.

## Running Jobs

You submit jobs to SLURM in a similar manner to what do on [Midway](../midway23/midway_getting_started.md). The difference is that you should specify different partitions and accounts corresponding to the cloud services you have access to (e.g. AWS or GCP). Additionally, the instance configuration should be specified via `--constraint`.

To submit jobs to cloud, you must specify a type of virtual machine (VM) by the option `--constraint=[VM Type]`. The VM types currently supported through Skyway can be found in the table below. You can also get an up-to-date listing of the machine types by running command sinfo-node-types on a skyway login node.

|  <div style="width:100px">VM Type</div> | Description |  AWS EC2 Instance |
| ----------- | ----------- | ----------- |
| t1  | 1 core, 1G Mem (for testing and building software) | t2.micro    |
| c1  | 1 core, 4G Mem (for serial jobs)                   | c5.large    |
| c8  | 8 cores, 32G Mem (for medium sized multicore jobs) | c5.4xlarge  |
| c36 | 36 cores, 144G Mem (for large memory jobs)         | c5.18xlarge |
| m24 | 24 cores, 384G Mem (for large memory jobs)         | c5.12xlarge |
| g1  | 1x V100 GPU (for GPU jobs)                         | p3.2xlarge  |
| g4  | 4x V100 GPU (for heavy GPU jobs)                   | p3.8xlarge  |
| g8  | 8x V100 GPU (for heavy GPU jobs)                   | p3.16xlarge |

When submitting jobs, include following two options in the job script:

* `--partition=rcc-aws`
* `--account=rcc-aws`

Some commonly used SLURM commands are:

* __sinfo__ – Show compute nodes status
* __sbatch__ – Submit computing jobs
* __scancel__ – Cancel submitted jobs
* __sacct__ – Check logs of recent jobs

A sample job script `sample.sbatch` would look like this

```
#!/bin/sh

#SBATCH --job-name=TEST
#SBATCH --partition=rcc-aws
#SBATCH --account=rcc-aws
#SBATCH --exclusive
#SBATCH --ntasks=1
#SBATCH --constraint=t2 # Specifies you would like to use a t2 instance

cd $SLURM_SUBMIT_DIR

hostname
lscpu
lscpu --extended
free -h
```

You can also request interactive jobs for testing and debugging purpuses:
```
   sinteractive --partition=rcc-aws --constraint=t2 --ntasks=1
```
and with GPUs
```
   sinteractive --partition=rcc-aws --constraint=g1 --ntasks=1 --gres=gpu:1
```


## Troubleshooting

For further assistance, please contact our Help Desk at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu).
