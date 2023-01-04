# Developer Guide
<!-- From these links:
https://cloud-skyway.rcc.uchicago.edu/ -->

This documentation provides information for admins and developers to install and deploy Skyway on a management node and login node. 

## Pre-requisites

The login node and service (management) node should be installed the following software:

* SLURM
* NFS

The following `python` packages are also needed to be ready to use

* miniconda
* boto3
* libcloud
* pysql
* tabulate

The login and management nodes are set up in the same manner as for a regular login node and SLURM management node, ready for accepting jobs. If users submit jobs to on-premises compute nodes (e.g. by specifying a proper partition), the jobs will be put on a regular queue.

## Installation and Configuration

On the (management) node (e.g. `skyway-dev` that is accessible from the `midway3` login node):

1. Create a folder named as `skyway` at root: `/opt/skyway`
2. Checkout this repo into `/opt/skyway/pkgs/skyway` ((or later `pip install skyway-cloud` via [PyPI](https://pypi.org/project/Skyway-cloud/))
3. Prepare a configuration folder `/opt/skyway/etc/`
4. Prepare several configuration files under `/opt/skyway/etc`
    * `root.yaml`: contains any attributes used by the management process.
    * `cloud.yaml`: contains global information for every cloud vendors and VM types (for all customers, note the differences between AWS and GCP).
    * `skyway.yaml`: defines configuration for the `skyway` python package
    * `accounts/*.yaml`: defines configuration for specific cloud accounts (see the .yaml files for setting up individual PIs and RCC's cloud accounts)
    * `services/*.yaml`: defines a service daemon process: The file name contains account (i.e. group) and partition in the format of `[group]-[cloud]`, for example, `cloud.rcc-aws.yaml`

    Below are some examples of the configuration files:
=== "root.xml"
    ```
    email: root@skyway-dev.rcc.uchicago.edu
    ```
=== "cloud.xml"
    ```
    aws:
        master_access_key_id: 'some-string'
        master_secret_access_key: '[another-string]'

        username: centos
        ami-id : ami-[id-string]
        key-name: rcc-skyway
        grace_sec: 300

        node-types:
            t1:  { name: t2.micro,    price: 0.0116, cores: 1,  memgb: 0.8 }
            c1:  { name: c5.large,    price: 0.085,  cores: 1,  memgb: 3.5 }
            c8:  { name: c5.4xlarge,  price: 0.68,   cores: 8,  memgb: 32 }
        ...

    gcp:

    ```
=== "skyway.xml"
    ```
    paths:
        etc: <ROOT>/etc/
        var: <ROOT>/var/
        run: <ROOT>/run/
        log: <ROOT>/log/
        files: <ROOT>/files/

    db:
        host: localhost
        port: 3306
        username: skyway
        password: "the-password"
        database: skyway
    ```
=== "services/cloud.rcc-aws.yaml"
    ```
    module: cloud
    kwargs:
      account: rcc-aws
    every: 15
    active: No
    ```
=== "accounts/rcc-aws.yml"
    ```
    cloud: aws
    group: rcc

    account:
      account_id: [account-id]
      role_name: rcc-skyway
      region: us-east-2
      security_group: ['sg-[some-string]']
      protected_nodes: []

    nodes:
      t1: 8

    users:
      - [user-name1]
      - [user-name2]
    ```
Finally, prepare the following script under `/opt/skyway/bin`, named `skyway`:

```
#!/bin/sh

export SKYWAYROOT=/skyway
export PYTHONPATH=$PYTHONPATH:/skyway/pkgs

if [ "`which python3 2>/dev/null`" = "" ]; then source /skyway/bin/bashrc; fi

if [ "$*" = "" ]; then python3 -m skyway
else python3 -m skyway.$*; fi
```

and give it execute-mode
```
chmod +x /opt/skyway/bin/skyway
```


On the head node (e.g. `skyway2-login1`):

* What should I do on the skyway login node so that users can submit jobs through skyway? – No need to do anything– just to make sure that SLURM functions normally.


## Deployment

* On the service node? How to launch the daemon? – see above: each cloud partition (or account) needs a separate process (daemon) to be launched via `skyway service [name-of-the-partition]`: a configuration file is expected under `/opt/skyway/etc/services`, for example, `cloud.rcc-aws.yaml` for the RCC account with AWS. There is also a so-called `watcher` (defined by `watcher.yaml`) that needs to be launched to overlook all cloud services.
* On the login node? No need to do anything, users just submit jobs to SLURM, specifying the constraint (e.g. `c4` or `g1`) and their account, then the `skyway` watcher on the management node will periodically query the SLURM queue to send the jobs to the cloud partition.

## Common commands

The following common commands are available on the service node.

```

skyway service
skyway service --status
skyway service --regist billing
skyway service --restart billing
skyway service --restart cloud-rcc-aws
skyway service --start cloud-rcc-aws
skyway service --stop cloud-rcc-aws

skyway cloud
skyway cloud rcc-aws --test
skyway cloud rcc-aws --connect rcc-aws-t1-001
skyway cloud rcc-aws --connect rcc-io
skyway cloud rcc-aws --ls
skyway cloud rcc-aws --rm i-0ecb224c29fdcb688

skyway billing
skyway billing rcc-aws --set amount=10
skyway billing rcc-aws --set rate=6.0
skyway billing rcc-aws --summary

skyway misc.db_test
skyway misc.nodes
skyway misc.nodes --update
skyway misc.sendmail

skyway slurm --update-conf

```

Some notes:

* Enable Skyway as a trusted operator:  Is it really possible from Skyway setting, or needs some sort of ITS support? – PIs ask ITS to use RCC Skyway to operate their AWS account: ITS is supposed to have a script that gives RCC permission to operate the given AWS account through their organizational AWS master access key.
* Suppose that I want to add another instance type to AWS and to GCP, what should I do? – see `/opt/skyway/etc/cloud.yml`
* Suppose that I want to add another cloud account (AWS and GCP) for a PI, what is the protocol and how can I achieve it from the configuration file? – add another yaml file under `/opt/skyway/etc/accounts`
* If I change the source code under `/opt/skyway/pkgs/skyway`, what are the steps to test the changes? no need to stop and restart the daemons, everything is python.

