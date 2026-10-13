# module load python/anaconda-2021.05
# python -m venv skyway-env
# source activate skyway-env
# pip install pandas pyyaml pymysql tabulate boto3 apache-libcloud cryptography paramiko
# export SKYWAYROOT=/home/ndtrung/Codes/skyway-github
# export SKYWAYROOT=/project/rcc/trung/skyway-github

# for PI-test to create nodes: needs an ami-id and a security group, and a key pair 

from datetime import datetime, timezone

import skyway
from skyway import account

#from skyway.cloud import aws
#from skyway.cloud import gcp
from skyway.cloud.aws import *
from skyway.cloud.gcp import *
from skyway.cloud.azure import *
from skyway.cloud.slurm import *
from skyway.cloud.oci import *
from datetime import datetime, timezone

import tabulate

#from skyway import service
#from skyway.service import core

# Test account
#account.list()
#account.show("ndtrung-aws")
#account.show("ndtrung-gcp")
#account.show("ndtrung-azure")

# Test cloud nodes
account = AWS('rcc-aws')
#account = GCP('rcc-gcp')
#account = GCP('ndtrung-gcp')
#account = AZURE('rcc-azure')
#account = OCI('ndtrung-oci')
#account = SLURMCluster('rcc-slurm')

# list all the node types available
account.get_node_types()

# list all the users in this account
#account.get_group_members()

# check if the current user is valid (and able to submit jobs)
user_name = os.environ['USER']
#account.check_valid_user(user_name)
#account.get_budget()

# create 1 node (instance)
#nodes = account.create_nodes('t1', ['your-run'], walltime="00:15:00")
#nodes = account.create_nodes('c1', ['your-run'], walltime="00:15:00")
#account.get_all_images()

# list all the nodes (instances)
#nodes, output_str = account.list_nodes(verbose=True)
user_budget = account.get_budget(user_name=user_name, verbose=False)
usage, balance = account.get_cost_and_usage_from_db(user_name=user_name)

data = [[user_name, user_budget, usage, balance]]
print(tabulate.tabulate(data, headers=["User", 'Allocation', 'Usage', 'Balance']))
#account.get_cost_and_usage("2024-05-30", "2024-10-04", verbose=True)
#account.get_budget_api()
#nodes = account.get_running_nodes(verbose=True)

#account.connect_node('node1')
#account.connect_node('midway3-0038')

# get the current cost of all the running instances
#account.get_running_cost()

# terminate an instance
#account.destroy_nodes(node_names=['yourRun'])
#account.destroy_nodes(IDs=['i-06fc520e0c8e6fd34'])

# Slurm service needs job IDs
#account.destroy_nodes(IDs=['21138341'])





