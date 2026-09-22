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
module load skyway
```

## Using cloud resources

You submit jobs to cloud in a similar manner to what do on your HPC cluster. The difference is that you should specify different cloud accounts corresponding to the cloud services you have access to. The cloud account is different from the PI account on the RCC machines. Additionally, the instance configuration should be specified via `--constraint`.

### List all the node types available to an account
```
skyway_nodetypes --account=your-cloud-account
skyway_nodetypes --account=your-gcp-account
```

For instance, the AWS VM types currently available through Skyway can be found in the table below. Other VM types will be included per requests.

|  <div style="width:100px">VM Type</div> | AWS EC2 Instance | Configuration | Description |  
| ----------- | ----------- | ----------- | ----------- |  
| t1  | t2.micro    | 1 core, 1GB RAM | for testing and building software |
| c1  | c5.large    | 1 core, 4B RAM | for serial jobs                   |
| c8  | c5.4xlarge  | 8 cores, 32GB RAM | for medium sized multicore jobs | 
| c36 | c5.18xlarge | 36 cores, 144GB RAM | for large memory jobs         |
| g1  | p3.2xlarge  | 4 cores, 61 GB RAM, 1x V100 GPU | for GPU jobs                         |
| g4  | p3.8xlarge  | 16 cores, 244 GB RAM, 4x V100 GPU | for heavy GPU jobs                   |
| g5  | p5.2xlarge  | 8 cores, 32 GB RAM, 1x A10G GPU | for heavy GPU jobs                   |
| m24 | c5.12xlarge | 24 cores, 384GB RAM | for large memory jobs         |

The following steps show a representative workflow with Skyway on the Midway3 login node.

### Allocate/provision an instance

To submit jobs to cloud, you must specify a type of virtual machine (VM) by the option `--constraint=[VM Type]`.
  ```
  skyway_alloc --account=your-cloud-account --constraint=t1 --time=01:00:00
  ```
  For a GPU instance, use
  ```
  skyway_alloc -A your-cloud-account --constraint=g5 --time=00:30:00
  ```

Expected behavior: If a VM is successfully provisioned, Skyway will show its public IP and a port number to which a SSH tunnel is set up on the login node.

### List the running and stopped VMs
  ```
  skyway_list --account=your-cloud-account
  ```

Expected behavior: The output shows all the running and stopped VMs under the cloud account.

### Transfer data

To copy a file from the login node to the instance named `your-run`
  ```
  skyway_transfer -A your-cloud-account -J your-run /path/to/my/code/training.py
  ```

Transfer a file from an instance to the login node
  ```
  skyway_transfer -A your-cloud-account -J your-run --from-cloud --cloud-path=~/output.txt $HOME/output.txt
  ```

You can also use scp or rsync to transfer data from and to the VM
  ```
  scp -i ~/.my_aws_ssh_key.pem -rC [user-name]@[vm-public-ip]:/path/to/data $HOME/path/to/dest/
  ```
Expected behavior: The data is present at the destination.

### Connect to the VM

To connect to the VM or cloud job with named `your-run`, use the `skyway_connect` command
  ```
  skyway_connect --account=your-cloud-account your-run
  ```

Expected behavior: The prompt shows the current working directory is on the VM.

You can use the VS Code Remote SSH Extension to connect to the VM using the private key above.

Alternatively, you can install Jupyter in a persistent storage accessible from the VM, and
launch a Jupyter session with the port number returned by `skyway_alloc` or `skyway_interactive` earlier
  ```
  # Go to the persistent storage folder on the VM (arranged previously by Skyway admins)
  cd /tmp/gcs
  python -m venv my-env
  source my-env/bin/activate
  python -m pip install --upgrade pip
  pip install notebook
  jupyter notebook --no-browser --ip=127.0.0.1 --port 21471
  ```
If the server is up and running, you will see a URL:
```
http://127.0.0.1:28875/tree?token=b1ee21e419bd59dede01ab4bda37499597ea7e0b99a968f
```

At this point, if you are in a ThinLinc session to the login node you can run the web browser (Firefox) and open this URL.

If you are using a SSH connection to the login node from your Linux/MacOS/Windows machine, 
then you will need to set up a port forwarding from the login node to the VM using the private key:
  ```
  ssh -i ~/.my_gcp_ssh_key.pem –L 21471:localhost:21471 [your-user-name]@[vm_public_ip]
  ```
and another port forward to your machine using 2FA:
  ```
  ssh -N -f -L 21471:localhost:21471 [your-CNetID]@midway3.rcc.uchicago.edu
  ```
Now you can can run the web browser on your machine to open the URL with the token above.

Expected behavior: You can see the Jupyter Notebook session with the folder and files on the VM .

### Stop/restart a job

To stop an instance, you use the `skyway_stop` command with your account and the instance ID:
  ```
  skyway_stop -A=your-cloud-account -i [instanceID]
  ```
The stopped instance does not get charged and the data on the VM is preserved. The data on the persistent storage remains, but not on the home folder.

Expected behavior: The command returns without any error message. `skyway_list` shows the VM in the `stopped` status.

To restart a stopped instance, you use the `skyway_restart` command with your account and the instance ID:
  ```
  skyway_restart -A=your-cloud-account -i [instanceID] -t 02:00:00
  ```
The instance ID is reported by the `skyway_list` command. You will be asked to confirm the allocation for the VM with the same VM type.

Expected behavior: The command returns without any error message. `skyway_list` shows the VM in the `running` status.

### Cancel/terminate/cancel a job
  ```
  skyway_cancel --account=your-cloud-account [job_name]
  ```

Expected behavior: The jobs (VMs) got terminated. When run `skyway_list` (step 3 above) the VM will not be present.

Note that when a VM is terminated, all the data on the VM is erased. The user should transfer the intermediate output to a cloud storage space or to local storage.

## Interactive and batch jobs

Skyway support interactive and batch jobs submitted from the Midway3 login nodes in a similar fashion to Slurm jobs.
The following steps are for launching interactive and batch jobs.

### Submit an interactive job

  ```
  skyway_interative --account=your-cloud-account --constraint=t1 --time=01:00:00
  ```
  For a GPU instance, use
  ```
  skyway_interative --account=your-cloud-account --constraint=g5 -t 00:30:00
  ```

Expected behavior: the user lands on a compute node or a VM on a separate terminal.

### Submit a batch job

A sample job script `job_script.sh` is given as bellow

  ```
  #!/bin/sh

  #SBATCH --job-name=your-run
  #SBATCH --account=your-cloud-account
  #SBATCH --constraint=g1
  #SBATCH --time=06:00:00

  skyway_transfer training.py
  
  source activate pytorch
  wget [url-of-the-dataset]
  python training.py
  ```


To submit the job, use the `skyway_batch` command
  ```
  skyway_batch job_script.sh
  ```

When the job script finishes, the instance is stopped right away, so the unused part of the walltime is not charged. Likewise, if the job is terminated due to the time limit, the instance is stopped. In both cases the data on the instance is preserved: you can find the instance ID with the `skyway_list` command and restart it to back up the data.

To keep the instance running after the job script finishes (until the walltime is reached, and charged until then), submit with
  ```
  skyway_batch --no-auto-stop job_script.sh
  ```

Transfer output data from cloud
  ```
  skyway_transfer -A your-cloud-account -J your-run --from-cloud --cloud-path=~/model*.pkl .
  ```

You can cancel the job using the `skyway_cancel` command.

## Troubleshooting

For further assistance, please contact our Help Desk at [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu).
