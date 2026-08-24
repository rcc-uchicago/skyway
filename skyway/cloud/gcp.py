# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# pip install apache-libcloud cryptography paramiko

# Maintainer: Trung Nguyen, Yuxing Peng
"""@package docstring
Documentation for GCP Class
"""

from datetime import datetime, timezone, timedelta
import io
import logging
import os
import random
import subprocess
from tabulate import tabulate
import time

from .core import Cloud
from .. import utils

from colorama import Fore
import pandas as pd

# apache-libcloud
from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
import libcloud.common.google

class GCP(Cloud):
    
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
        if account_cfg['cloud'] != 'gcp' :
            raise Exception(f'Service provider gcp is not associated with this account.')

        for k, v in account_cfg.items():
            setattr(self, k.replace('-','_'), v)

        self.keyfile = account_path + self.account['key_file'] + '.json'
        if not os.path.isfile(self.keyfile):
            raise Exception(f"The key file {self.keyfile} is not found.")

        self.usage_history = f"{account_path}usage-{account}.pkl"

        # load cloud.yaml under $SKYWAYROOT/etc/
        cloud_path = os.environ['SKYWAYROOT'] + '/etc/'
        vendor_cfg = utils.load_config('cloud', cloud_path)
        if 'gcp' not in vendor_cfg:
            raise Exception(f'Cloud vendor gcp is undefined.')
      
        self.vendor = vendor_cfg['gcp']
        self.account_name = account
        self.onpremises = False
        self.post_boot_script = self.account.get('post_boot_script', "")

        ComputeEngine = get_driver(Provider.GCE)
        try:
            self.driver = ComputeEngine(self.account['service_account'],
                                        self.keyfile,
                                        project=self.account['project_id'])
        except Exception as e:
            print(f"An error occurred: {e}")
        
        pem_file_full_path = account_path + self.account['key_name'] + '.pem'
        self.my_ssh_private_key =  f"~/.my_gcp_ssh_key.pem"
        cmd = f"cp {pem_file_full_path} {self.my_ssh_private_key}; chmod 600 {self.my_ssh_private_key}"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

        assert(self.driver != False)
        return

    def check_valid_user(self, user_name, verbose=False):
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

    def get_budget(self, user_name=None, verbose=True):
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

    def get_cost_and_usage_from_db(self, user_name):
        '''
        compute the accumulating cost from the pkl database
        and the remaining balance
        '''
        if user_name not in self.users:
            raise Exception(f"{user_name} is not listed in the user group of this account.")
                
        user_budget = self.users[user_name]['budget']

        if not os.path.isfile(self.usage_history):
            print(f"Usage history {self.usage_history} is not available")
            data = [user_name, "--", "--", "00:00:00", "00:00:00", 0.0, user_budget]
            df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)
            return 0, user_budget

        df = pd.read_pickle(self.usage_history)
        df_user = df.loc[df['User'] == user_name]
        df_user = df_user.astype({"Cost": float})
        accumulating_cost = df_user['Cost'].sum()
        remaining_balance = user_budget - accumulating_cost

        return accumulating_cost, remaining_balance

    def get_usage_history_from_db(self, user_name):
        '''
        compute the accumulating cost from the pkl database
        and the remaining balance
        '''
        if user_name not in self.users:
            raise Exception(f"{user_name} is not listed in the user group of this account.")
                
        user_budget = self.users[user_name]['budget']

        if not os.path.isfile(self.usage_history):
            print(f"Usage history {self.usage_history} is not available")
            data = [user_name, "--", "--", "00:00:00", "00:00:00", "0.0", user_budget]
            df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            #df = pd.DataFrame(columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)
            return 0, user_budget

        df = pd.read_pickle(self.usage_history)
        df_user = df.loc[df['User'] == user_name]
        
        history = df_user[['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance']]
        return history

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
        print(tabulate(node_info, headers=['Name', 'Instance Type', 'CPU Cores', 'Memory (GB)', 'GPU', 'GPU Type', 'Per-hour Cost ($)']))
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

    def list_nodes(self, show_protected_nodes=False, verbose=False):
        """Member function: list_nodes
        Get a list of all existed instances
        
        Return: a list of multiple turple. Each turple has four elements:
                (1) instance name (2) state (3) type (4) identifier
        """
        nodes = []
        current_time = datetime.now(timezone.utc)

        df = pd.read_pickle(self.usage_history)

        for node in self.driver.list_nodes():
            if node.state == 'terminated':
                continue

            # Get the creation time of the instance
            creation_time_str = node.extra.get('creationTimestamp')  # GCP
            if creation_time_str:
                # Convert the creation time from string to datetime object
                creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                
                # Calculate the running time
                if node.state == "running":
                    # since restart_nodes() prepends to the database with instance ID every time
                    # finds the first row with instance ID to find its start time
                    df_node = df.loc[df['InstanceID'] == node.id]
                    if df_node.empty:
                        continue
                    first_found_idx = df_node.index[0]
                    start_time = pd.to_datetime(df.loc[first_found_idx, 'Start'], format='%Y-%m-%dT%H:%M:%S.%f%z')
                    running_time = current_time - start_time #creation_time
                else:
                    df_node = df.loc[df['InstanceID'] == node.id]
                    if df_node.empty == False:
                        # since restart_nodes() prepends to the database with instance ID every time
                        # finds the first row with instance ID to find its start time
                        first_found_idx = df[df['InstanceID'] == node.id].index[0]
                        start_time = pd.to_datetime(df.loc[first_found_idx, 'Start'], format='%Y-%m-%dT%H:%M:%S.%f%z')
                        end_time = pd.to_datetime(df_node['End'].iloc[0], format='%Y-%m-%dT%H:%M:%S.%f%z')
                        running_time = end_time - start_time #creation_time
                    else:
                        continue

                # Calculate the running cost
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost

                node_user_name = self.get_instance_user_name(node)

                nodes.append([node.name, node_user_name, node.state, node.size, node.id, node.public_ips[0], running_time, running_cost])

        output_str = ''
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'User', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost'], maxcolwidths=None))
            print("")
        else:
            output_str = io.StringIO()
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost'], maxcolwidths=None), file=output_str)
            print("", file=output_str)
        return nodes, output_str
    
    def create_nodes(self, node_type: str, node_names = [], interactive = False, need_confirmation = True, walltime = None, image_id = "", location = ""):
        """Member function: create_compute
        Create a group of compute instances(nodes, servers, virtual-machines 
        ...) with the given type.
        
         - node_type: instance type information from the Skyway definitions
         - node_names: a list of names for the nodes, to get the number of nodes

        Return: a dictionary of instance ID (i.e., names) for created instances.
        """
        if node_type not in self.vendor['node-types']:
            raise Exception(f'Node type {node_type} is not available in this account.')

        user_name = os.environ['USER']
        user_budget = self.get_budget(user_name=user_name, verbose=False)
        usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
        running_cost = self.get_running_cost(verbose=False)
        usage = usage + running_cost
        remaining_balance = user_budget - usage
        unit_price = self.vendor['node-types'][node_type]['price']
        if need_confirmation == True:
            print(f"User budget: ${user_budget:.3f}")
            print(f"+ Usage    : ${usage:.3f}")
            print(f"+ Available: ${remaining_balance:.3f}")
            if remaining_balance <= 0:
                print("The current budget is not sufficient for this request.")
                return
            response = input(f"Do you want to create an instance of type {node_type} (${unit_price}/hr)? (y/n) ")
            if response == 'n':
                return

        count = len(node_names)
        if count <= 0:
            raise Exception(f'List of node names is empty.')

        print(Fore.BLUE + f"Allocating {count} instance ...", end=" ")

        if location != "":
           location_name = location
        else:
           location_name = self.account['location']
        print(f"\nLocation: {location_name}\n")

        vpc_name = self.account.get('vpc_name', 'vpc1')

        nodes = {}
        node_cfg = self.vendor['node-types'][node_type]
        #print(f"node_type = {node_type}: {node_cfg}")
        preemptible = node_cfg['preemptible'] if 'preemptible' in node_cfg else False

        scopes = [
            'https://www.googleapis.com/auth/cloud-platform'
        ]
        
        networks = self.driver.ex_list_networks() #'vpc1'      # get this from ex_list_networks()
        network = next((net for net in networks if net.name == vpc_name), None)

        subnets = self.driver.ex_list_subnetworks()
        subnet = next((sub for sub in subnets if sub.name == location_name), None)

        if walltime is None or walltime == "":
            walltime_str = "00:30:00"
        else:
            walltime_str = walltime

        # shutdown the instance after the walltime (in minutes)
        pt = datetime.strptime(walltime_str, "%H:%M:%S")
        walltime_in_minutes = int(pt.hour * 60 + pt.minute + pt.second/60)

        for node_name in node_names:
            gpu_type = None
            gpu_count = None           
            if 'gpu' in node_cfg:
                gpu_type = node_cfg['gpu-type']
                gpu_count = node_cfg['gpu']

            try:
                # google-cloud-compute changed at some point, making tags empty when query the list of nodes with libcloud
                tags = [{ 'node_name': node_name, 'user': user_name }]
                # instead, we add user and node name to labels when creating nodes
                vm_image = self.account['image_name']
                if image_id != "":
                    vm_image = image_id

                # retrieve the public key from the private key
                cmd = f"ssh-keygen -y -f {self.my_ssh_private_key}"
                p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                public_key_from_pem = p.stdout.split(' ')[1].strip()
                user_name_pub_key = f"{user_name}:ssh-rsa {public_key_from_pem}"

                node = self.driver.create_node(node_name,
                                                size = node_cfg['name'],
                                                image = vm_image, 
                                                location = location_name,
                                                ex_network=network,
                                                ex_subnetwork=subnet,
                                                ex_service_accounts=[{
                                                    'email': self.account['service_account'],
                                                    'scopes': scopes
                                                }],
                                                ex_labels={'goog-ec-src': 'vm_add-gcloud', 'node_name': node_name, 'user': user_name},
                                                ex_preemptible = preemptible,
                                                ex_accelerator_type = gpu_type,
                                                ex_accelerator_count = gpu_count,
                                                ex_on_host_maintenance = 'TERMINATE',
                                                ex_tags = tags,
                                                ex_metadata = {'ssh-keys': user_name_pub_key },)
                self.driver.wait_until_running([node])

                # record node_type, creation time
                creation_time_str = node.extra.get('creationTimestamp')
                #print(f"Creation timestamp: {creation_time_str}")
                creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                node_type = node_cfg['name']
                nodes[node_name] = [node_type, creation_time_str, node.public_ips[0]]

                print(f'\n\u2713 Created instance: {node.name}\n')

                # ssh to the node and execute a shutdown command scheduled for walltime
                host = node.public_ips[0]
                user_name = os.environ['USER']
                #print("Connecting to host: " + host)

                # record the running time and cost at launch time and expected walltime
                # then if destroy_nodes() is invoked then updated the end time and cost

                running_time = timedelta(hours=pt.hour, minutes=pt.minute, seconds=pt.second)
                instance_unit_cost = self.get_unit_price_instance(node)
                projected_running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
                end_time = creation_time + running_time
                end_time_str = end_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

                # store the record into the database
                data = [user_name, node.id, node.size,
                        creation_time_str, end_time_str, projected_running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                df.to_pickle(self.usage_history)

                print("\u2713 Preparing the instance...")
                time.sleep(30)
                #cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{host} 'sudo shutdown -P +{walltime_in_minutes}' "
                #p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                utils.ssh_until_success(
                    host,
                    user_name,
                    self.my_ssh_private_key,
                    f"sudo shutdown -P +{walltime_in_minutes}",
                )

                # execute the post boot script on the VM
                # need to install gcsfuse or nfs-utils on the VM (or having an image that has gcsfuse installed) to mount available storage
                if self.post_boot_script != "":
                    script_file = os.environ['SKYWAYROOT'] + "/etc/accounts/" + self.post_boot_script
                    script_cmd = utils.script2cmd(script_file)
                    cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{host} '{script_cmd}' "
                    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

                print("\u2713 To connect to the instance, run:")
                print(f"  ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{host} or")
                print(f"  skyway_connect --account={self.account_name} -J {node.name}")
                print(f"Instance public IP: {host}") 

            except libcloud.common.google.ResourceNotFoundError as e:
                print(f'Error: Resource not found. Details: {e}')
            except RuntimeError as e:
                print(f"SSH setup failed for {node_name}: {str(e)}. Terminating instance to avoid unbounded charges.")
                try:
                    self.driver.destroy_node(node)
                except Exception:
                    pass
            except libcloud.common.google.GoogleBaseError as e:
                print(f'Google Cloud error occurred: {e}')
            except Exception as e:
                print(f"Failed to create {node_name}. Reason: {str(e)}")
        
        return nodes

    def connect_node(self, node_id, separate_terminal=True):
        """
        Connect to an instance using account's pem file
        [account_name].pem file should be under $SKYWAYROOT/etc/accounts
        It is important to create the node using the account's key-name.

        To be able to ssh into the instance, we need to add the public key of the machine
        (user pub key on midway3, or on their local box) to the GCP account
        and then on GCP console of the Project, Compute Engine, Metadata, SSH Keys, Add Item,
        copy the public key of the machine into the key.
        Alternatively, use deploy_node with metadata with a public/private key pair,
        but still it requires keygen-ssh for the user on the local machine/login node.

        """
        #node = self.driver.ex_get_node(node_name)
        
        node = None
        for node in self.driver.list_nodes():
            if node.state == "running":
                if node.id == node_id:
                    break
        if node is not None:
            public_ip = node.public_ips[0]
            username = os.environ['USER']
            print(f"\u2713 Connecting to instance public IP address: {public_ip}")

            # set up SSH tunneling to the localhost
            port=random.randint(15000, 30000)
            cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new -f -N -L {port}:localhost:{port} {username}@{public_ip}"
            print(f"SSH tunneling to the VM using port = {port}")
            os.system(cmd)

            if separate_terminal == True:
                cmd = "gnome-terminal -q --title='Connecting to the node' -- bash -c "
                cmd += f" 'module purge; ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{public_ip}; exec bash' "
            else:
                cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{public_ip}"

            os.system(cmd)

        else:
            print(f"Node {node_id} does not exist.")

        node_info = {
            'private_key' : "",
            'login' : f"{username}@{public_ip}",
        }
        return node_info

    def stop_nodes(self, IDs=[], node_names=[], need_confirmation=True):
        '''
        stop all the nodes (instances) given the list of node names or IDs
        NOTE: should store the running cost and time before stopping the node(s)
        node_names = list of node names as strings
        '''
        if isinstance(node_names, str): node_names = [node_names]
        if isinstance(IDs, str): IDs = [IDs]

        user_name = os.environ['USER']

        for node in self.driver.list_nodes():
            if node.state != "running":
                continue
            
            if node.name in node_names or node.id in IDs:
                node_user_name = self.get_instance_user_name(node)
                if  node_user_name != user_name:
                    print(f"Cannot stop an instance {node.name} created by other users")
                    continue

                creation_time_str = node.extra.get('creationTimestamp')  # GCP
                # Convert the creation time from string to datetime object
                creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                current_time = datetime.now(timezone.utc)
                running_time = current_time - creation_time
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost

                if need_confirmation == True:
                    response = input(f"Do you want to stop {node.name} (running cost ${running_cost})? NOTE: Data on the node will be removed. (y/n) ")
                    if response != 'y':
                        continue

                self.driver.ex_stop_node(node)

                # record the running time and cost
                running_time = current_time - creation_time
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)

                current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

                # store the record into the database
                data = [node_user_name, node.id, node.size, creation_time, current_time_str, running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                if node.id not in df['InstanceID'].values:
                    df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                else:
                    # since restart_nodes() prepends to the database with instance ID every time
                    # finds the first row with instance ID to set the end time
                    first_found_idx = df[df['InstanceID'] == node.id].index[0]
                    df.loc[first_found_idx, 'End'] = current_time_str
                df.to_pickle(self.usage_history)

    def restart_nodes(self, IDs=[], node_names=[], need_confirmation=True, walltime = None):
        '''
        restart all the nodes (instances) given the list of node names
        node_names = list of node names as strings
        '''
        if isinstance(node_names, str): node_names = [node_names]
        if isinstance(IDs, str): IDs = [IDs]

        user_name = os.environ['USER']
        if walltime is None or walltime == "":
            walltime_str = "00:30:00"
        else:
            walltime_str = walltime

        # shutdown the instance after the walltime (in minutes)
        pt = datetime.strptime(walltime_str, "%H:%M:%S")
        walltime_in_minutes = int(pt.hour * 60 + pt.minute + pt.second/60)

        for node in self.driver.list_nodes():
            if node.state != "stopped":
                continue

            if node.name in node_names or node.id in IDs:
                node_user_name = self.get_instance_user_name(node)
                if  node_user_name != user_name:
                    print(f"Cannot restart an instance {node.name} created by other users")
                    continue

                user_budget = self.get_budget(user_name=user_name, verbose=False)
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
                running_cost = self.get_running_cost(verbose=False)
                usage = usage + running_cost
                remaining_balance = user_budget - usage
                unit_price = self.get_unit_price_instance(node)
                if need_confirmation == True:
                    print(f"User budget: ${user_budget:.3f}")
                    print(f"+ Usage    : ${usage:.3f}")
                    print(f"+ Available: ${remaining_balance:.3f}")
                
                    response = input(f"Do you want to restart the instance of type {node.size} (${unit_price}/hr)? (y/n) ")
                    if response == 'n':
                        return

                print(Fore.BLUE + f"Allocating an instance ...\n", end=" ")

                self.driver.ex_start_node(node)

                self.driver.wait_until_running([node])

                # creation time is the first time the instance was created
                creation_time_str = node.extra.get('creationTimestamp')
                creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')

                # for restarting a node, let's use current_time for start time
                local_tz = datetime.now().astimezone().tzinfo
                current_time = datetime.now(local_tz)
                current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')               

                time.sleep(30)

                # make sure to shutdown the instance after the walltime (in minutes)
                host = node.public_ips[0]
                utils.ssh_until_success(
                    host,
                    user_name,
                    self.my_ssh_private_key,
                    f"sudo shutdown -P +{walltime_in_minutes}",
                )

                # execute the post boot script on the VM
                # need to install gcsfuse or nfs-utils on the VM (or having an image that has gcsfuse installed) to mount available storage
                if self.post_boot_script != "":
                    script_file = os.environ['SKYWAYROOT'] + "/etc/accounts/" + self.post_boot_script
                    script_cmd = utils.script2cmd(script_file)
                    cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{host} '{script_cmd}' "
                    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

                print(f'\nInstance {node.name} is up.')
                print("To connect to the instance, run:")
                print(f"  ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{node.public_ips[0]} or")
                print(f"  skyway_connect --account={self.account_name} -J {node.name}")

                running_time = timedelta(hours=pt.hour, minutes=pt.minute, seconds=pt.second)
                instance_unit_cost = self.get_unit_price_instance(node)
                projected_running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
                end_time = current_time + running_time
                end_time_str = end_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

                # store the record into the database
                data = [user_name, node.id, node.size,
                        current_time_str, end_time_str, projected_running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                # prepend the database with the new session of this instance ID
                # meaning that there are duplicated instance IDs in the database (intentionally)
                df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                df.to_pickle(self.usage_history)

    def get_node_connection_info(self, node_id):
        node = None
        for node in self.driver.list_nodes():
            if node.state == "running":
                if node.id == node_id:
                    break
        if node is not None:                
            public_ip = node.public_ips[0]

        # GCP allows to specify user name when creating the VMs
        username = self.get_instance_user_name(node)
        node_info = {
            'private_key' : self.get_private_key(),
            'login' : f"{username}@{public_ip}",
        }
        return node_info

    def execute(self, node_id: str, **kwargs):
        '''
        execute commands on a node
        Example:
           execute(node_name='your-node', binary="python", arg1="input.txt", arg2="output.txt")
           execute(node_name='your-node', binary="mpirun -np 4 my_app", arg1="input.txt", arg2="output.txt")
        '''
        node = None
        for node in self.driver.list_nodes():
            if node.state == "running":
                if node.id == node_id:
                    break
        if node is not None:
            host = node.public_ips[0]
            user_name = os.environ['USER']

            command = ""
            for key, value in kwargs.items():
                command += value + " "

            cmd = "gnome-terminal --title='Connecting to the node' -- bash -c "
            cmd += f" 'ssh -o StrictHostKeyChecking=accept-new {user_name}@{host}' -t '{command}' "

            os.system(cmd)
        else:
            print(f"Node {node_id} does not exist.")

    def execute_script(self, node_id: str, script_name: str):
        '''
        execute all the lines in a script on a compute node
        '''
        node = None
        for node in self.driver.list_nodes():
            if node.state == "running":
                if node.id == node_id:
                    break
        if node is not None:
            host = node.public_ips[0]
            user_name = os.environ['USER']
            script_cmd = utils.script2cmd(script_name)
            
            cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {user_name}@{host} '{script_cmd}' "
            os.system(cmd)
        else:
            print(f"Node {node_id} does not exist.") 


    def destroy_nodes(self, IDs=[], node_names=[], need_confirmation=True):
        '''
        Destroy all the nodes (instances) given the list of node names
        NOTE: should store the running cost and time before terminating the node(s)
        node_names = list of node names as strings
        '''
        if isinstance(node_names, str): node_names = [node_names]
        if isinstance(IDs, str): IDs = [IDs]

        user_name = os.environ['USER']

        for node in self.driver.list_nodes():

            check_nodename = False
            check_id = False
            if node_names is not None:
                check_nodename = node.name in node_names
            if IDs is not None:
                check_id = node.id in IDs

            if check_nodename or check_id:
                node_user_name = self.get_instance_user_name(node)
                if  node_user_name != user_name:
                    print(f"Cannot destroy an instance {node.name} created by other users")
                    continue

                creation_time_str = node.extra.get('creationTimestamp')  # GCP
                # Convert the creation time from string to datetime object
                creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                current_time = datetime.now(timezone.utc)
                running_time = current_time - creation_time
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost

                if need_confirmation == True:
                    response = input(f"Do you want to destroy {node.name} (running cost ${running_cost})? NOTE: Data on the node will be removed. (y/n) ")
                    if response != 'y':
                        continue

                self.driver.destroy_node(node)

                # record the running time and cost
                running_time = current_time - creation_time
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)

                current_time_str = current_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

                # store the record into the database
                data = [node_user_name, node.id, node.size, creation_time, current_time_str, running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                if node.id not in df['InstanceID'].values:
                    df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                else:
                    # since restart_nodes() prepends to the database with instance ID every time
                    # finds the first row with instance ID to set the end time
                    first_found_idx = df[df['InstanceID'] == node.id].index[0]
                    df.loc[first_found_idx, 'End'] = current_time_str

                df.to_pickle(self.usage_history)

   
    def get_running_nodes(self, verbose=False):
        """Member function: running_nodes
        Return identifiers of all running instances
        """
        nodes = []
        
        current_time = datetime.now(timezone.utc)

        for node in self.driver.list_nodes():
            if node.state == "running":
                # Get the creation time of the instance
                creation_time_str = node.extra.get('creationTimestamp')  # GCP
                if creation_time_str:
                    # Convert the creation time from string to datetime object
                    creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                    
                    # Calculate the running time
                    running_time = current_time - creation_time

                    nodes.append([node.name, node.size, node.id, node.public_ips[0], running_time])

        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Type', 'Instance ID', 'Host', 'Running Time']))
            print("")

        return nodes
    
    def get_unit_price_instance(self, node):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. n1-standard-1)
        For GCE, node.size is the instance type.
        """

        for node_type in self.vendor['node-types']:
            if self.vendor['node-types'][node_type]['name'] == node.size:
                unit_price = self.vendor['node-types'][node_type]['price']
                return unit_price
        return -1.0

    def get_unit_price(self, node_type: str):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. t1)
        """
        if node_type in self.vendor['node-types']:
            return self.vendor['node-types'][node_type]['price']
        return -1.0

    def get_host_ip(self, node_name):
        return self.driver.ex_get_node(node_name).public_ips[0]

    def get_instance_user_name(self, node):
        '''
        return the user name that created the node
        '''
        # some change in the GCP cloud compute that makes tags empty
        #return node.extra.get('tags', {}).get('user')
        # adding user and node name to labels  when creating nodes
        return node.extra.get('labels').get('user')

    def get_instance_name(self, node):
        """Member function: get_instance_name
        Get the name information from the instance with given ID.
         - node: a node object
        """
        return node.name

    def get_instance_ID(self, instance_name: str):
        """Member function: get_instance_ID

        """
        for node in self.driver.list_nodes():
            if node.state == "running":
                if node.name == instance_name:
                    return node.id
        return ''


    def get_instances(self, filters = []):
        """Member function: get_instances
        Get a list of instance objects with give filters
        """
        return self.driver.list_nodes()

    def get_running_cost(self, verbose=True):

        current_time = datetime.now(timezone.utc)
        user_name = os.environ['USER']
        nodes = []
        total_cost = 0.0
        for node in self.driver.list_nodes():
            if self.get_instance_name(node) in self.account['protected_nodes']:
                continue
            if node.state == "running":
                node_user_name = self.get_instance_user_name(node)
                if user_name != node_user_name:
                    continue

                # Get the creation time of the instance
                creation_time_str = node.extra.get('creationTimestamp')  # GCP
                if creation_time_str:
                    # Convert the creation time from string to datetime object
                    creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                    
                    # Calculate the running time
                    running_time = current_time - creation_time

                    instance_unit_cost = self.get_unit_price_instance(node)
                    running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                    total_cost = total_cost + running_cost

                    nodes.append([node.name, node.size, node.id, node.public_ips[0], running_time, running_cost])

        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Type', 'Instance ID', 'Host', 'Running Time', 'Running Cost']))
            print("")

        return total_cost

    def get_private_key(self):
        return self.my_ssh_private_key