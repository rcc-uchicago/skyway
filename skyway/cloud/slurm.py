# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Trung Nguyen

"""@package docstring
Documentation for SLURMCluster Class
"""

from datetime import datetime, timezone
import io
import logging
import os
import subprocess
from tabulate import tabulate

from .core import Cloud
from .. import utils

from colorama import Fore
import pandas as pd

class SLURMJob:
    def __init__(self, jobid, state, job_name, instance_type, host, running_time="", start_time=""):
        self.jobid = jobid
        self.state = state
        self.job_name = job_name
        self.instance_type = instance_type
        self.host = host
        self.running_time = running_time
        self.start_time = start_time

class SLURMCluster(Cloud):
    """Documentation for SLURMCluster
    This Class is used as the driver to operate SLURM-provisioned resource for [Demo]
    """
    
    def __init__(self, account):
        """Constructor:
        The construct initialize the connection to the cloud platform, by using
        setting informations passed by [cfg], such as the credentials.        

        account [string]
        """

        #super().__init__(vendor_cfg, kwargs)

        # load [account].yaml under $SKYWAYROOT/etc/accounts
        account_path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        account_cfg = utils.load_config(account, account_path)
        if account_cfg['cloud'] != 'slurm' :
            raise Exception(f'Service provider slurm is not associated with this account.')

        for k, v in account_cfg.items():
            setattr(self, k.replace('-','_'), v)

        self.usage_history = f"{account_path}usage-{account}.pkl"

        # load cloud.yaml under $SKYWAYROOT/etc/
        cloud_path = os.environ['SKYWAYROOT'] + '/etc/'
        vendor_cfg = utils.load_config('cloud', cloud_path)
        if 'slurm' not in vendor_cfg:
            raise Exception(f'Service provider slurm is undefined.')

        self.vendor = vendor_cfg['slurm']
        self.account_name = account
        self.onpremises = True
       
    # account info

    def check_valid_user(self, user_name, verbose=False):
        '''
        check if a user name is in the cloud account
        '''
        if user_name not in self.users:
            if verbose == True:
                print(f"{user_name} is not listed in the user group of this account.")
            return False

        if verbose == True:
            user_info = []
            user_info.append([user_name, self.users[user_name]['budget']])
            print(tabulate(user_info, headers=['User', 'Budget']))
            print("")
        return True
      

    def get_node_types(self):
        """
        List all the node (instance) types provided by the vendor and their unit prices
        """
        node_info = []
        for node_type in self.vendor['node-types']:
            if 'gpu' in self.vendor['node-types'][node_type]:
                node_info.append([node_type, self.vendor['node-types'][node_type]['name'],
                              self.vendor['node-types'][node_type]['cores'],
                              self.vendor['node-types'][node_type]['memgb'],
                              self.vendor['node-types'][node_type]['gpu'],
                              self.vendor['node-types'][node_type]['gpu-type'],
                              self.vendor['node-types'][node_type]['price']])
            else:
                node_info.append([node_type, self.vendor['node-types'][node_type]['name'],
                              self.vendor['node-types'][node_type]['cores'],
                              self.vendor['node-types'][node_type]['memgb'],
                              "0",
                              "--",
                              self.vendor['node-types'][node_type]['price']])
        print(tabulate(node_info, headers=['Name', 'Instance Type', 'CPU Cores', 'Memory (GB)', 'GPU', 'GPU Type', 'Per-hour Cost (SU)']))
        print("")

    def get_group_members(self):
        """
        List all the users in this account
        """
        user_info = []
        for user in self.users:
            user_info.append([user, self.users[user]['budget']])
        print(tabulate(user_info, headers=['User', 'Budget']))
        print("")

    # billing operations

    def get_budget(self, user_name=None, verbose=True):
        '''
        get the current budget of the whole account, or of a user name from the account yaml file
        '''
        if user_name is not None:
            if user_name not in self.users:
                print(f"{user_name} is not listed in the user group of this account.")
                return -1
        
            if verbose == True:
                user_info = []
                user_info.append([user_name, self.users[user_name]['budget']])
                print(tabulate(user_info, headers=['User', 'Budget']))
                print("")
            return self.users[user_name]['budget']
        else:
            user_info = []
            total_budget = 0.0
            for name in self.users:
                total_budget += float(self.users[name]['budget'])
                if verbose == True:
                    user_info.append([name, self.users[name]['budget']])
            if verbose == True:
                print(tabulate(user_info, headers=['User', 'Budget']))
                print(f"Total: ${total_budget}")
            return total_budget

    def get_budget_api(self):
        '''
        get the budget from the service provide API
           accounts balance
        '''
        pass

    def get_cost_and_usage_from_db(self, user_name):
        '''
        compute the accumulating cost from the SLURM database
        and the remaining balance
        '''
        user_name = os.environ['USER']
        user_budget = self.users[user_name]['budget']

        if not os.path.isfile(self.usage_history):
            print(f"Usage history {self.usage_history} is not available")
            data = [user_name, "--", "--", "00:00:00", "00:00:00", "0.0", user_budget]
            df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            #df = pd.DataFrame(columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)
            return 0, user_budget

        cmd = f"rcchelp usage --user {user_name} | awk \'$1 == \"{user_name}\" " 
        cmd += "{print $2}\' "
        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        out = out.decode('utf-8').strip()
        accumulating_cost = float(out)

        cmd = "rcchelp balance -a rcc-staff | awk \'$1 == \"rcc-staff\" {print $4}\' "
        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
        out = out.decode('utf-8').strip()
        remaining_balance = float(out)

        return accumulating_cost, remaining_balance

    # instance operations

    def list_nodes(self, show_protected_nodes=False, verbose=False):
        '''
        list all the running/queueing nodes (aka instances) using squeue
        '''
        user_name = os.environ['USER']
        # job_id state job_name account nodelist   runningtime starttime comment user_name"
        cmd = f"export SQUEUE_FORMAT=\"%13i %.4t %24j %16a %N %M %V %k %u\"; squeue -u {user_name} -h"

        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
      
        # encode output as utf-8 from bytes, remove newline character
        m = out.decode('utf-8').strip()

        i = 0
        nodes = []
        for line in m.splitlines():

            node_info = line.split()

            jobid = node_info[0]
            state = node_info[1]
            job_name = node_info[2]
            instance_type = node_info[7] # node_info getting from comment 
            instance_id = node_info[4]   # nodelist, can be used as public_host_ip
            running_time = node_info[5]  
            #start_time = node_info[6]

            unit_price = 1.0 #self.vendor['node-types'][node_type]['price']
            time_stamp = running_time.split(':')
            running_time_hours = 0
            # we don't expect any instance run longer than a day
            if len(time_stamp) == 3:
                pt = datetime.strptime(running_time, "%H:%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            elif len(time_stamp) == 2:
                pt = datetime.strptime(running_time, "%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            else:
                print(f"Running time: {running_time} {time_stamp}")

            running_cost = running_time_hours * unit_price

            nodes.append([job_name,
                          state,
                          instance_type,
                          jobid,
                          instance_id,
                          running_time,
                          running_cost])
            i = i + 1
        
        output_str = ''
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']))
            print("")
        else:
            output_str = io.StringIO()
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']), file=output_str)
            print("", file=output_str)
        return nodes, output_str


    def create_nodes(self, node_type: str, node_names = [], interactive = False, need_confirmation = True, walltime = None, image_id = ""):
        '''
        create several nodes (aka instances) given a list of node names using salloc
        for SLURM it is a wrapper of salloc
        '''
        user_name = os.environ['USER']
        user_budget = self.get_budget(user_name=user_name, verbose=False)
        usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
        running_cost = self.get_running_cost(verbose=False)
        usage = usage + running_cost
        remaining_balance = user_budget - usage
        unit_price = self.vendor['node-types'][node_type]['price']
        if need_confirmation == True:
            print(f"User budget: {user_budget:.3f} SU")
            print(f"+ Usage    : {usage:.3f} SU")
            print(f"+ Available: {remaining_balance:.3f} SU")
            response = input(f"Do you want to create an instance of type {node_type} (${unit_price}/hr)? (y/n) ")
            if response == 'n':
                return

        if walltime is None:
            walltime_str = "01:00:00"
        else:
            walltime_str = walltime
        
        ntasks_per_node = self.vendor['node-types'][node_type]['cores']
        memgb = int(self.vendor['node-types'][node_type]['memgb'])

        count = len(node_names)
        if count <= 0:
            raise Exception(f'List of node names is empty.')

        job_name = node_names[0]
        cmd = f"salloc"
        if interactive == True:
            cmd = f"sinteractive"
        cmd += f" --account={self.account['account_id']}"
        cmd += f" -J {job_name}"
        cmd += f" --nodes={count}"
        cmd += f" --ntasks-per-node={ntasks_per_node}"
        cmd += f" --mem={memgb}GB"
        cmd += f" --time={walltime_str}"
        cmd += f" --comment={node_type}"
        cmd += " --wait-all-nodes=1"
        if node_type == 'g1':
            cmd += f" --gres=gpu:1 --partition=gpu"
        if node_type == 'g2':
            cmd += f" --gres=gpu:2 --partition=gpu"
        print(f"{cmd}")
        #p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        os.system(cmd)

    def connect_node(self, node_name, separate_terminal=True):
        '''
        connect to a node (aka instance) via SSH: for slurm, node name is alias to the host IP
        '''
        print(f"Node name: {node_name}")
        if separate_terminal == True:
            cmd = f"gnome-terminal --title='Connecting to the node' -- bash -c 'ssh  -o StrictHostKeyChecking=accept-new {node_name}' "
        else:
            cmd = f"ssh  -o StrictHostKeyChecking=accept-new {node_name}"
        print(f"{cmd}")
        os.system(cmd)

    def get_node_connection_info(self, node_name):
        node_info = {
            'private_key' : "",
            'login' : f"{node_name}",
        }
        return node_info

    def destroy_nodes(self, IDs = [], need_confirmation=True):
        '''
        destroy several nodes (aka instances) given a list of node names using scancel
        '''
        user_name = os.environ['USER']

        # maybe no need to check if the job ID belongs the current user because scancel will throw errors otherwise

        for instanceID in IDs:
            print(f"Cancelling job {instanceID}")
            
            user_name = os.environ['USER']
            # job_id state job_name account nodelist   runningtime starttime comment user_name"
            cmd = f"export SQUEUE_FORMAT=\"%13i %.4t %24j %16a %N %M %V %k %u\"; squeue -j {instanceID} -h"

            proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
            (out, err) = proc.communicate()
        
            # encode output as utf-8 from bytes, remove newline character
            line = out.decode('utf-8').strip()

            
            node_info = line.split()

            job_user_name = node_info[8]
            if job_user_name != user_name:
                continue
            jobid = node_info[0]
            state = node_info[1]        
            job_name = node_info[2]     
            instance_type = node_info[7] # node_info getting from comment 
            instance_id = node_info[4]   # nodelist, can be used as public_host_ip
            running_time = node_info[5]  
            start_time = node_info[6]
            
            unit_price = self.vendor['node-types'][instance_type]['price']
            time_stamp = running_time.split(':')
            running_time_hours = 0
            # we don't expect any instance run longer than a day
            if len(time_stamp) == 3:
                pt = datetime.strptime(running_time, "%H:%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            elif len(time_stamp) == 2:
                pt = datetime.strptime(running_time, "%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            else:
                print(f"Running time: {running_time} {time_stamp}")

            running_cost = running_time_hours * unit_price
        
            # store the record into the database
            usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
            data = [job_user_name, jobid, instance_type, start_time, datetime.now(timezone.utc), running_cost, remaining_balance]

            if os.path.isfile(self.usage_history):
                df = pd.read_pickle(self.usage_history)
            else:
                df = pd.DataFrame([], columns=['User','JobID','InstanceType','Start','End', 'Cost', 'Balance'])

            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)

            cmd = f"scancel {instanceID}"
            os.system(cmd)

    def get_running_nodes(self, verbose=False):
        '''
        list all the running nodes (aka instances)
        '''
        user_name = os.environ['USER']

        # job_id state job_name account nodelist   runningtime starttime comment user_name"
        cmd = f"export SQUEUE_FORMAT=\"%13i %.4t %24j %16a %N %M %V %k %u\"; squeue -u {user_name} -h"

        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
      
        # encode output as utf-8 from bytes, remove newline character
        m = out.decode('utf-8').strip()

        i = 0
        nodes = []
        for line in m.splitlines():
            
            node_info = line.split()

            jobid = node_info[0]
            state = node_info[1]
            if state.lower() != "r":
                continue
            job_name = node_info[2]
            instance_type = node_info[7] # node_info getting from comment 
            host = node_info[4]   # nodelist, can be used as public_host_ip
            running_time = node_info[5]  # datetime.now(timezone.utc) - start_time  
            start_time = node_info[6]

            unit_price = 1.0 #self.vendor['node-types'][node_type]['price']
            time_stamp = running_time.split(':')
            running_time_hours = 0
            # we don't expect any instance run longer than a day
            if len(time_stamp) == 3:
                pt = datetime.strptime(running_time, "%H:%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            elif len(time_stamp) == 2:
                pt = datetime.strptime(running_time, "%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            else:
                print(f"Running time: {running_time} {time_stamp}")

            running_cost = running_time_hours * unit_price

            nodes.append([job_name,
                          state,
                          instance_type,
                          jobid,
                          host,
                          running_time,
                          running_cost])
            i = i + 1
        
        output_str = ''
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']))
            print("")
        else:
            output_str = io.StringIO()
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']), file=output_str)
            print("", file=output_str)
        return nodes, output_str

    def get_running_cost(self, verbose=True):
        total_cost = 0.0
        user_name = os.environ['USER']

        # job_id state job_name account nodelist   runningtime starttime comment user_name"
        cmd = f"export SQUEUE_FORMAT=\"%13i %.4t %24j %16a %N %M %V %k %u\"; squeue -u {user_name} -h"

        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
      
        # encode output as utf-8 from bytes, remove newline character
        m = out.decode('utf-8').strip()

        i = 0
        nodes = []
        for line in m.splitlines():

            node_info = line.split()
            state = node_info[1]
            if state.lower() != "r":
                continue
            running_time = node_info[5]

            unit_price = 1.0 #self.vendor['node-types'][node_type]['price']
            time_stamp = running_time.split(':')
            running_time_hours = 0
            # we don't expect any instance run longer than a day
            if len(time_stamp) == 3:
                pt = datetime.strptime(running_time, "%H:%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            elif len(time_stamp) == 2:
                pt = datetime.strptime(running_time, "%M:%S")
                running_time_hours = float(pt.second)/3600.0 + float(pt.minute)/60.0 + pt.hour
            else:
                print(f"Running time: {running_time} {time_stamp}")

            total_cost = total_cost + running_time_hours * unit_price
            i = i + 1

        return total_cost

    def execute(self, node_name: str, **kwargs):
        '''
        execute commands on a node
        Example:
           execute(node_name='your-node', binary="python", arg1="input.txt", arg2="output.txt")
           execute(node_name='your-node', binary="mpirun -np 4 my_app", arg1="input.txt", arg2="output.txt")
        '''
        command = ""
        for key, value in kwargs.items():
            command += value + " "

        cmd = "gnome-terminal --title='Connecting to the node' -- bash -c "
        cmd += f" 'ssh  -o StrictHostKeyChecking=accept-new {node_name}' -t '{command}' "

        os.system(cmd)

    def execute_script(self, node_name: str, script_name: str):
        '''
        execute all the lines in a script on a compute node
        '''
        script_cmd = utils.script2cmd(script_name)
        cmd = f"ssh  -o StrictHostKeyChecking=accept-new {node_name} -t 'eval {script_cmd}' "
        os.system(cmd)

    def get_instance_ID(self, instance_name: str):
        '''
        return the job ID of a job name (instance name) used for scancel in destroy_nodes()
        '''
        nodes, _ = self.get_running_nodes(verbose=False)
        instance_ID = None
        for node in nodes:
            # node = [job_name, state, instance_type, jobid, instance_id, running_time, running_cost]
            if node[0] == instance_name:
                instance_ID = node[3]
        return instance_ID


    def get_host_ip(self, instance_name):
        '''
        get the public IP or host (node list for SLURM) of a instance (job) name
        
        '''
        nodes, _ = self.get_running_nodes(verbose=False)
        instance_ID = None
        for node in nodes:
            # node = [job_name, state, instance_type, jobid, instance_id, running_time, running_cost]
            if node[0] == instance_name:
                instance_ID = node[4]
        return instance_ID

    def get_unit_price(self, node_type: str):
        '''
        get the unit price of a node object (inferring from its name and from the cloud.yaml file)
        '''
        if node_type in self.vendor['node-types']:
            return self.vendor['node-types'][node_type]['price']
        return -1.0

    def get_instances(self, filters = []):
        """Member function: get_instances
        Get a list of instance objects with give filters
        """
        user_name = os.environ['USER']

        # job_id state job_name account nodelist   runningtime starttime comment user_name"
        cmd = f"export SQUEUE_FORMAT=\"%13i %.4t %24j %16a %N %M %V %k %u\"; squeue -u {user_name} -h"

        proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)
        (out, err) = proc.communicate()
      
        # encode output as utf-8 from bytes, remove newline character
        m = out.decode('utf-8').strip()

        i = 0
        nodes = []
        for line in m.splitlines():
  
            node_info = line.split()
            
            jobid = node_info[0]
            state = node_info[1]
            job_name = node_info[2]
            instance_type = node_info[7] # node_info getting from comment 
            instance_id = node_info[4]   # nodelist, can be used as public_host_ip
            running_time = node_info[5]
            start_time = node_info[6]

            instance = SLURMJob(jobid, state, job_name, instance_type, instance_id, running_time, start_time)
            nodes.append(instance)
            
        return nodes