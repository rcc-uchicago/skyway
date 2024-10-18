# Skyway Dashboard
# Contact: Trung Nguyen (ndtrung@uchicago.edu)
# module load python/anaconda-2021.05
# python -m venv skyway-env
# source activate skyway-env
# pip install pandas pyyaml pymysql tabulate boto3 apache-libcloud cryptography paramiko streamlit
# export SKYWAYROOT=/home/ndtrung/Codes/skyway-github
# export SKYWAYROOT=/project/rcc/trung/skyway-github

import skyway
from skyway.cloud.aws import *
from skyway.cloud.gcp import *
from skyway.cloud.azure import *
from skyway.cloud.oci import *
from skyway.cloud.slurm import *

import os
import subprocess
from datetime import datetime, timezone
from io import StringIO

import streamlit as st
from streamlit_autorefresh import st_autorefresh

import pandas as pd
#import nest_asyncio

import colorama

class InstanceDescriptor:
    def __init__(self, jobname: str, account_name: str, node_type: str, walltime: str, vendor_name: str, job_script: str):
        self.jobname = jobname
        self.account_name = account_name
        self.node_type = node_type.split(' ')[0]
        self.walltime = walltime
        self.vendor_name = vendor_name
        self.job_script = job_script

        self.account = None
        if 'aws' in vendor_name:
            self.account = AWS(account_name)
        elif 'gcp' in vendor_name:
            self.account = GCP(account_name)
        elif 'azure' in vendor_name:
            self.account = AZURE(account_name)
        elif 'oci' in vendor_name:
            self.account = OCI(account_name)
        elif 'midway3' in vendor_name:
            self.account = SLURMCluster(account_name)

        self.user = os.environ['USER']

    def submitJob(self):
        #st.warning("Do you want to create this instance?")
        #if st.button("Yes"):

        print(f"creating node from {self.vendor_name} with account {self.account_name}")
        self.account.create_nodes(self.node_type, [self.jobname], need_confirmation=False, walltime=self.walltime)
        nodes_ready = False
        while nodes_ready == False:
            instanceID = self.account.get_instance_ID(self.jobname)
            if instanceID != "":
                nodes_ready = True

        if self.job_script != "":
            args = self.parse_script(job_script)
            skyway_cmd = args['skyway_cmd']

            # execute pre-execute commands after nodes are available: e.g. data transfers
            if skyway_cmd != "":
                # append the command with account and job name
                pre_execute = skyway_cmd + " --account=" + self.account_name + " -J" + self.jobname
                os.system(pre_execute)

            instanceID = self.account.get_instance_ID(self.jobname)
            self.account.execute_script(instanceID, self.job_script)

        initializing = True
        return initializing

    def connectJob(self, node_names):
        '''
        only get on a on-premise compute node for now with rcc-staff
        '''
        
        if "midway3" in self.vendor_name:
            instanceID = self.account.get_host_ip(self.jobname)
            self.account.connect_node(instanceID)

        elif "aws" in self.vendor_name:
            instanceID = self.account.get_instance_ID(self.jobname)
            self.account.connect_node(instanceID)

        elif "gcp" in self.vendor_name:
            instanceID = self.account.get_instance_ID(self.jobname)
            self.account.connect_node(instanceID)

        elif "oci" in self.vendor_name:
            instanceID = self.account.get_instance_ID(self.jobname)
            self.account.connect_node(instanceID)

    def terminateJob(self, node_names = [], instance_id=""):
        if "midway3" in self.vendor_name:
            instanceID = self.account.get_instance_ID(self.jobname)
            st.write(f"Terminating instance ID {instanceID} ...")
            self.account.destroy_nodes(IDs=[instanceID], need_confirmation=False)
        else:
            if instance_id == "":
                st.write(f"Terminating instance name {node_names} ...")
                self.account.destroy_nodes(node_names=node_names, need_confirmation=False)
            else:
                st.write(f"Terminating instance ID {instance_id}...")
                self.account.destroy_nodes(node_names=node_names, IDs=[instance_id], need_confirmation=False)

    def getBalance(self):
        # retrieve from database for the given account
        accumulating_cost, remaining_balance = self.account.get_cost_and_usage_from_db(user_name=self.user)
        return remaining_balance

    def getEstimateCost(self):
        pt = datetime.strptime(self.walltime, "%H:%M:%S")
        walltime_in_hours = int(pt.hour + pt.minute/60)
        if "midway3" in self.vendor_name:
            unit_price = 1.0 # float(self.account.get_unit_price(self.node_type))
        else:
            unit_price = float(self.account.get_unit_price(self.node_type))
        cost = walltime_in_hours * unit_price
        return cost
  
    def list_nodes(self):
        nodes, list_of_nodes = self.account.list_nodes(verbose=False) 
        return nodes


    '''
    parse the job script to get the account information, node type (constraint) and walltime
    '''
    def parse_script(self, filename):
        jobname = "my-run"
        account = ""
        constraint = ""
        walltime = ""
        skyway_cmd = ""
        with open(filename, 'r') as f:
            lines = f.readlines()
            for line in lines:
                # extract only lines with #SBATCH, remove \n characters
                # remove all the spaces
                # split at '='
                if "#SBATCH" in line:
                    # remove #SBATCH
                    line = line.replace('#SBATCH ','').strip('\n')
                    line = line.replace(' ','')
                    args = line.split('=')
                    if len(args) == 2:
                        if args[0] == "-job-name":
                            jobname = args[1]
                        if args[0] == "--account":
                            account = args[1]
                        if args[0] == "--constraint":
                            constraint = args[1]
                        if args[0] == "--time":
                            walltime = args[1]                        
                elif "skyway_" in line:
                    skyway_cmd = line.strip('\n')
                else:
                    continue

        return { 'jobname': jobname,
                'account': account,
                'constraint': constraint,
                'walltime': walltime,
                'skyway_cmd': skyway_cmd
                }

if __name__ == "__main__":

    colorama.init(autoreset=True)

    #nest_asyncio.apply()    
    st.set_page_config(layout='wide')
    logo_file = os.path.join(os.path.dirname(__file__), 'logo.png')
    if os.path.isfile(logo_file):
        st.image(logo_file,width=450)


    # autorefresh every 30 seconds, maximum 200 times
    count = st_autorefresh(interval=30000, limit=200, key="autorefreshcounter")

    job_script = ""
    skyway_cmd = ""

    #st.markdown("### :blue_book:  RCC User Guide Chatbot 🤖") 
    st.markdown("## Skyway Dashboard")

    col1, col2, col3 = st.columns((1,2,3))

    with col1:
        st.markdown("Instances")
        st.markdown("Usage")

    with col2:
        st.markdown("#### Requested resources")
        job_name = st.text_input(r"$\textsf{\large Job name}$", "your-run")
        
        vendor = st.selectbox(r"$\textsf{\large Service provider}$", ('Amazon Web Services (AWS)', 'Google Cloud Platform (GCP)', 'Microsoft Azure', 'Oracle Cloud Infrastructure (OCI)', 'RCC Midway3'), help='Cloud vendors or on-premise clusters')

        # populate this select box depending on the allocation (account.yaml)
        vendor_name = vendor.lower()
        if 'aws' in vendor_name:
            node_types = ('t1 (t2.micro, 1-core CPU)', 'c1 (c5.large, 1-core CPU)', 'c36 (c5.18xlarge, 36-core CPU)', 'g1 (p3.2xlarge, 1 V100 GPU)', 'g5 (p5.2xlarge, 1 A10G GPU)')
            vendor_short = "aws"
            accounts = ('rcc-aws', 'ndtrung-aws')
        elif 'gcp' in vendor_name:
            node_types = ('t1 (n1-standard-1, 1-core CPU)', 'c1 (n1-standard-2, 1-core CPU, 2 hardware threads)', 'c4 (c2-standard-8, 4-core CPU)', 'g1 (n1-standard-8, 4-core CPU)')
            vendor_short = "gcp"
            accounts = ('rcc-gcp', 'ndtrung-gcp')
        elif 'azure' in vendor_name:
            node_types = ('c1 (Standard_DS1_v2, 1-core CPU)', 'b4 (Standard_B2ts_v2, 2-core CPU)', 'b32 (Standard_B32ls_v2, 32-core)', 'g1 (Standard_NC6s_A100_v3, 1 A100 GPU)')
            vendor_short = "azure"
            accounts = ('rcc-azure', 'ndtrung-azure')
        elif 'oci' in vendor_name:
            node_types = ('c1 (VM.Standard.A1.Flex, 1-core CPU)', 'e4 ( VM.Standard.E4.Flex, 16-core CPU)')
            vendor_short = "oci"
            accounts = ('ndtrung-oci')            
        elif 'midway3' in vendor_name:
            node_types = ('t1 (1 CPU core + 4 GB RAM)', 'c4 (4 CPU cores + 16 GB RAM)', 'c16 (16 CPU cores + 64 GB RAM)', 'c48 (48 CPU cores + 128 GB RAM)', 'g1 (8 CPU cores + 1 V100 GPU)', 'bigmem (16 CPU cores + 512 GB RAM)')
            accounts = ('rcc-midway3',)
            vendor_short = "midway3"

        # account or allocation
        #allocation = st.text_input(r"$\textsf{\large Account}$", "rcc-aws", key='account', help='Your cloud account (e.g. rcc-aws) or on-premises allocation (e.g. rcc-staff)')
        allocation = st.selectbox(r"$\textsf{\large Account}$", accounts, key='account', help='Your cloud account (e.g. rcc-aws) or on-premises allocation (e.g. rcc-staff)')
        node_type = st.selectbox(r"$\textsf{\large Node type}$", node_types, help='Instance type, or node configuration')
        walltime = st.text_input(r"$\textsf{\large Walltime (HH:MM:SS)}$", "02:00:00", help='Max walltime for the instance')

        envs = st.selectbox(r"$\textsf{\large Interaction with the node}$", ('Command Line Interface', 'Graphical User Interface'), help='Whether a CLI or GUI image should be loaded on the instance.')
        if envs == 'Command Line Interface':
            cmd = ""
        elif envs == 'Graphical User Interface':
            cmd = ""      
        else:
            cmd = ""

        uploaded_file = st.file_uploader(r"$\textsf{\large Choose a script to be executed on the node}$", help='The script contains the body of the job script.')
        if uploaded_file is not None:
            job_script = uploaded_file.name

            # To read file as bytes:
            #bytes_data = uploaded_file.getvalue()
            #st.write(bytes_data)

            # To convert to a string based IO:
            stringio = StringIO(uploaded_file.getvalue().decode("utf-8"))
            #st.write(stringio)

            # To read file as string:
            string_data = stringio.read()
            st.write(string_data)

            # Can be used wherever a "file-like" object is accepted:
            #dataframe = pd.read_csv(uploaded_file)
            #st.write(dataframe)
    

    with col3:
      
        account_name = allocation.lower()

        # estimate number of SUs
        instanceDescriptor = InstanceDescriptor(job_name, account_name, node_type, walltime, vendor_name, job_script)
        estimatedSU = instanceDescriptor.getEstimateCost()

        st.markdown("#### Estimated cost for the node")
        balance = instanceDescriptor.getBalance()
        if "midway3" in vendor_name.lower():
            st.markdown(f"{int(estimatedSU)} SUs", help="Estimated based on the requested node type and walltime")
            st.markdown(f"Current balance: {int(balance)} SUs")
            st.markdown(f"Balance after job completion would be: {int(balance - estimatedSU)} SUs")
        else:
            st.markdown(f"${estimatedSU:0.3f}", help="Estimated based on the requested node type and walltime")
            st.markdown(f"Current balance: ${balance:0.3f}")
            st.markdown(f"Balance after job completion would be: ${balance - estimatedSU:0.3f}")

        pending = False
        jobs = st.empty()
        if st.button('Submit', type='primary', help='Create a cloud node or a compute node', on_click=instanceDescriptor.submitJob):
            #st.markdown("#### Job status")
            jobs.write("Node initializing..")

        st.markdown("#### Running nodes")
        headers=['Name', 'User', 'Status',  'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']

        # listing all the running nodes/instances
        nodes = instanceDescriptor.list_nodes()

        df = pd.DataFrame(nodes, columns=headers)
        df.style.hide(axis="index")
        st.table(df)

        # handle the button clicks
        if st.button('Connect', type='primary', help="Create an interactive session on the instance"):
            instanceDescriptor.connectJob(node_names=['your_run'])
        st.markdown("NOTE: Only support interactive sessions on the nodes provided by AWS, GCP, OCI and RCC Midway3 for now.")

        instance_id = st.text_input(r"$\textsf{Instance ID to terminate}$", "")
        if st.button('Terminate', help=f'Destroy the instance with given an instance ID', type='primary'):
            instanceDescriptor.terminateJob(node_names=[job_name], instance_id=instance_id)


        #st.markdown("#### Usage statistics")

    st.markdown("""Skyway 2.0.0, Copyright 2022-2024, UChicago Research Computing Center""")
