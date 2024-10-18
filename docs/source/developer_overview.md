# Developer Guide
<!-- From these links:
https://cloud-skyway.rcc.uchicago.edu/ -->

This documentation provides information for admins and developers to install and deploy Skyway on the login node of a HPC system. 

## Pre-requisites

* Python 3.x

## Installation

Installing Skyway is straightforward

``` py linenums="1"
  git clone https://github.com/ndtrung81/skyway
  cd skyway
  python3 -m venv skyway-env
  source skyway-env/bin/activate 
  pip install -r requirements.txt
  export SKYWAYROOT=/path/to/skyway
  export PATH=$SKYWAYROOT:$PATH
```

Line 1: Check out the GitHub repo

Lines 3-4: Create a virtual environment and activate it

Line 5: Install the required packages into the environment

Lines 6-7: Set the environment variable `SKYWAYROOT` and preppend it to `PATH`

## Configuration

Under the `SKYWAYROOT` folder, create a folder structure
```
  etc/
    - accounts/
        - rcc-aws.yaml
    - cloud.yaml
```

where the content of the file `cloud.yaml` includes the following:
``` py linenums="1"
aws:
    master_access_key_id: 'AKIA--------------'
    master_secret_access_key: '7bqh-------------'

    username: ec2-user
    key_name: rcc-skyway
    ami_id : ami-0b9c9831f6e1cc731
    io-node: 18.224.41.227
    grace_sec: 300

    node-types:
        t1:  { name: t2.micro,    price: 0.0116, cores: 1,  memgb: 1 }
        c1:  { name: c5.large,    price: 0.085,  cores: 1,  memgb: 3.5 }
        c8:  { name: c5.4xlarge,  price: 0.68,   cores: 8,  memgb: 32 }
        g1:  { name: p3.2xlarge,  price: 3.06,   cores: 4,  memgb: 61,  gpu: 1 }
```

This file lists all the supported cloud vendors such as `aws` and their node (aka virtual machine (VM)) types.

* The `master_access_key_id` and `master_secret_access_key` is for the AWS account that
launches the ID of the `io-node` instance (`18.224.41.227` in this example) using the key pair named `rcc-skyway`.
* The `username` entry indicates the user name used for logging into the instance (e.g. via SSH).
* The `io-node` instance is up and running to provide the storage mount points (such as `/software` or `/cloud/rcc-aws`) if needed.
* The `amd_id` entry shows the image ID used to launch the `io-node` instance.
These entries will be deprecated in the future versions.

Under the `node-types` dictionary, we list all the VM configurations and their code names `t1`, `c1` and so on.
Each entry is a dictionary that defines the actual code name of the instance from the cloud vendor (`t2.micro` and `c5.large` for AWS in this example).
The prices are per hour for on-demand uses.

For Google Cloud Platform, you can add another entry `gcp` with similar settings.

``` py linenums="1"
gcp:
    username: rcc-user
    image-name: compute-019
    location: us-central1
    io-node: 35.225.118.145
    grace_sec: 60

    node-types:
        c1:   { name: n1-standard-1,   price: 0.050,  cores: 1,  memgb: 1.5 }
        c4:   { name: c2-standard-8,   price: 0.4176, cores: 4,  memgb: 24 }
        c16:  { name: c2-standard-32,  price: 1.6704, cores: 16, memgb: 96 }
        g1:   { name: n1-standard-8,   price: 2.00,   cores: 4,  memgb: 30, gpu: 1, gpu-type: nvidia-tesla-v100 }
        v1:   { name: custom-12-79872, price: 2.26,   cores: 6,  memgb: 78, gpu: 1, gpu-type: nvidia-tesla-v100 }
        a1:   { name: a2-highgpu-1g,   price: 2.79,   cores: 6,  memgb: 80, gpu: 1, gpu-type: nvidia-tesla-a100 }
```

The file `rcc-aws.yaml` has the following information for the cloud account named `rcc-aws`.

``` py linenums="1"
cloud: aws
group: rcc
account:
    access_key_id: 'AKIA53-------------'
    secret_access_key: '34oXS-------------'
    region: us-east-2
    security_group: ['sg-0a79--------------']
    protected_nodes: []
    account_id: '3910-------------'
    role_name: rcc-skyway
    ami_id: 'ami-0fbfb390428631854'
    key_name: rcc-aws
nodes:
    c1:   4
    c36:  2
    g1:   2
users:
    user1: { budget: 100 } 
    user2: { budget: 150 }
```

The `cloud` entry maps the cloud vendor as defined in the `cloud.yaml` file (`aws` in this example).
The `group` entry specifies the name of this particular cloud account.

Under the `account` dictionary, we need the following entries:

* The `access_key_id` and `secret_access_key` is for this particular AWS account (e.g. a PI cloud account)
that will be used to launch the instances. The `region` and `security_group` entries are used to create the instances.
* The `protected_nodes` entry lists the instance names that are not terminated, if any.
* The `role_name` entry indicates which role is used to create instances (can be left empty). This entry exists for historical reason
where the Skyway cloud account (that provides the `rcc-skway` role) needs to be added as a trusted agent to the cloud account to manage the instances.
* The `ami_id` (or `image_id`) entry indicates the image used for the instances. Will be deprecated in the future.
* The `key_name` entry indicates the key pair used for creating the instances.

Under the `nodes` dictionary, we specify the number of nodes for a certain VM type, as defined in the `aws` dictionary in `cloud.yaml`.
The numbers just need to be greater than zero.

Under the `users` dictionary, we specify the users that are allowed to use this cloud account and the corresponding budgets.

The cloud account file for `gcp` is something like the following

``` py linenums="1"
cloud: gcp
group: ndtrung

account:
  project_id: project-19299
  key_file: ndtrung-gcp
  location: us-central1-c
  service_account: '4631????????-compute@developer.gserviceaccount.com'
  protected_nodes: []
  image_name: debian-12-bookworm-v20240515
  key_name: my_instance_keypair

nodes:
  c1: 4
  c30: 10
  v1: 20
  a1: 16

users:
  user1:  { budget: 10 }
  user2:  { budget: 5 }
```


## Source code structure

The `skyway` Python package has a simple structure as below

```
skyway/
   - cloud/
      - aws.py
      - azure.py
      - core.py
      - gcp.py
      - oci.py
      - slurm.py
   - __init__.py
   - account.py
   - utils.py
docs/
examples/
README.md
```
