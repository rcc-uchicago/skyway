# Skyway

Skyway is a Python package developed at the University of Chicago, Research Computing Center to allow users to burst computing workloads from the on-premise cluster to cloud platforms such as Amazon Web Services (AWS), Google Cloud Platform (GCP), Oracle Cloud Infrastructure (OCI), and Microsoft Azure. 

## Installation

Installing Skyway is easy:

```
git clone 
python3 -m venv skyway-env
source skyway-env/bin/activate 
pip install -r requirements.txt
```

## Configuration

You need to set up a folder that contains a YAML file that lists the available cloud vendors, and separate YAML files each for a cloud account under `SKYWAYROOT`.


## Usage

1) List all the node types available to an account
```
   skyway_nodetypes --account=your-aws-account
   skyway_nodetypes --account=your-gcp-account
```

2) Submit an interactive job

```
  skyway_interative --account=rcc-aws --constraint=t1 --time=01:00:00
```


3) Submit a batch job
```
   skyway_batch --account=rcc-aws --constraint=t1 --time=01:00:00 --script=run_script.sh
```

4) List all the running VMs with an account
```
   skyway_list --account=rcc-aws
```

5) Cancel/terminate a job with Name "your-run"
```
   skyway_cancel --account=rcc-aws your-run
```

6) Launch the Skyway dashboard
```
   skyway_dashboard
```

