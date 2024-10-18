# User Guide

This documentation explains how regular users access to Skyway and submit jobs to use cloud services. Please refer to the [Skyway](https://cloud-skyway.rcc.uchicago.edu/) home page for more information and news.

## Gaining Access

You first need an active RCC User account (see [accounts and allocations page](https://rcc.uchicago.edu/accounts-allocations)). Next, you should contact your PI or class instructors for access to Skyway. Alternatively, you can reach out to our Help Desk at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu) for assistance.

## Connecting

You need to log in to the HPC cluster.

```
ssh -Y [cnetid]@midway3.rcc.uchicago.edu
```

For Midway3 users, 

```
  module use /project/rcc/shared/modulefiles
  module load skyway
```

## Running Jobs

You submit jobs to cloud in a similar manner to what do on your HPC cluster. The difference is that you should specify different partitions and accounts corresponding to the cloud services you have access to. Additionally, the instance configuration should be specified via `--constraint`.

1) List all the node types available to an account
```
skyway_nodetypes --account=your-aws-account
skyway_nodetypes --account=your-gcp-account
```

To submit jobs to cloud, you must specify a type of virtual machine (VM) by the option `--constraint=[VM Type]`. The VM types currently supported through Skyway can be found in the table below. You can also get an up-to-date listing of the machine types by running command sinfo-node-types on a skyway login node.

|  <div style="width:100px">VM Type</div> | Configuration | Description |  AWS EC2 Instance |
| ----------- | ----------- | ----------- |  ----------- |
| t1  | 1 core, 1GB RAM | for testing and building software | t2.micro    |
| c1  | 1 core, 4B RAM | for serial jobs                   | c5.large    |
| c8  | 8 cores, 32GB RAM | for medium sized multicore jobs | c5.4xlarge  |
| c36 | 36 cores, 144GB RAM | for large memory jobs         | c5.18xlarge |
| g1  | 4 cores, 61 GB RAM, 1x V100 GPU | for GPU jobs                         | p3.2xlarge  |
| g4  | 16 cores, 244 GB RAM, 4x V100 GPU | for heavy GPU jobs                   | p3.8xlarge  |
| g5  | 8 cores, 32 GB RAM, 1x A10G GPU | for heavy GPU jobs                   | p5.2xlarge  |
| m24 | 24 cores, 384GB RAM | for large memory jobs         | c5.12xlarge |

2) Allocate/provision an instance
  ```
  skyway_alloc --account=rcc-aws --constraint=t1 --time=01:00:00
  ```
  For a GPU instance, use
  ```
  skyway_alloc -A rcc-aws --constraint=g5 --time=00:30:00
  ```

3) List all the running VMs with an account
  ```
  skyway_list --account=rcc-aws
  ```

4) Transfer data to the instance named your-run
  ```
  skyway_transfer --account=rcc-aws -J your-run training.py
  ```

5) Connect to the VM named your-run
  ```
  skyway_connect --account=rcc-aws your-run
  ```

Once on the VM, do
  ```
  nvidia-smi
  source activate pytorch
  python training.py > ~/output.txt
  scp output.txt [yourcnetid]@midway3.rcc.uchicago.edu:~/
  exit
  ```
At this point, there would be a file named output.txt in your Midway3 home folder.

6) Cancel/terminate/cancel a job
  ```
  skyway_cancel --account=rcc-aws [job_name]
  ```

Expected behavior: The jobs (VMs) got terminated. When run `skyway_list` (step 3 above) the VM will not be present.

The following steps are for launching interactive and batch jobs.

7) Submit an interactive job (combinig steps 4, 6 and 7)

  7a) to AWS
  ```
  skyway_interative --account=rcc-aws --constraint=t1 --time=01:00:00
  ```
  For a GPU instance, use
  ```
  skyway_interative --account=rcc-aws --constraint=g5 -t 00:30:00
  ```

  7b) to midway3
  ```
  skyway_interactive --account=rcc-midway3 --constraint=t1 --time=01:00:00
  ```
Expected behavior: the user lands on a compute node or a VM on a separate terminal.

8) Submit a batch job

A sample job script `job_script.sh` would look like this

  ```
  #!/bin/sh

  #SBATCH --job-name=your-run
  #SBATCH --account=rcc-aws
  #SBATCH --constraint=g1

  source activate pytorch
  python training.py
  ```


  8a) Submit the job
  ```
  skyway_batch job_script.sh
  ```
  8b) Connect to the VM to check the current progress of the run (like step 7)
  ```
  skyway_connect -A rcc-aws -J your-run
  ```
  
  Once on the VM:
  ```
  ls -lrt
  cat output.txt
  exit
  ``` 
  
  8c) Transfer output data from cloud
  ```
  skyway_transfer --account=rcc-aws -J your-run --from-cloud --cloud-path=~/model*.pkl .
  ```

  8d) Cancel the job (like step 6)



## Troubleshooting

For further assistance, please contact our Help Desk at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu).
