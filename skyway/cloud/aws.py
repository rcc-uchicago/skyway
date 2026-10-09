# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Trung Nguyen, Yuxing Peng

"""@package docstring
Documentation for AWS Class
"""

from datetime import datetime, timezone, timedelta
import io
import logging
import os
import random
import subprocess
from tabulate import tabulate
import traceback

from .core import Cloud, parse_walltime, walltime_boot_script, is_capacity_error
from .. import utils

from colorama import Fore
import pandas as pd
import time

# AWS python SDK
import boto3
import botocore.exceptions

# It is also possible to use libcloud EC2NodeDriver
from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
from libcloud.compute.drivers.ec2 import EC2NodeDriver

class AWS(Cloud):
    """Documentation for AWS Class
    This Class is used as the driver to operate Cloud resource for [Demo]
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
        if account_cfg['cloud'] != 'aws' :
            raise Exception(f'Service provider aws is not associated with this account.')

        for k, v in account_cfg.items():
            setattr(self, k.replace('-','_'), v)

        _hist_dir = self.account.get('usage_history_path') or account_path
        self.usage_history = os.path.join(_hist_dir, f"usage-{account}.pkl")

        # load cloud.yaml under $SKYWAYROOT/etc/
        cloud_path = os.environ['SKYWAYROOT'] + '/etc/'
        vendor_cfg = utils.load_config('cloud', cloud_path)
        if 'aws' not in vendor_cfg:
            raise Exception(f'Cloud vendor aws is undefined.')

        self.vendor = vendor_cfg['aws']
        self.account_name = account
        self.onpremises = False
        self.post_boot_script = self.account.get('post_boot_script', "")

        # using_trusted_agent = False means that no use of master account key and secret as defined in cloud.yaml
        self.using_trusted_agent = self.account.get('using_trusted_agent', False)
        if self.using_trusted_agent == False:
            # This is how the existing skyway creates the ec2 resource without master for rcc-aws
            self.ec2 = boto3.resource('ec2',
                                       aws_access_key_id = self.account['access_key_id'],
                                       aws_secret_access_key = self.account['secret_access_key'],
                                       region_name = self.account['region'])
        else:
            # This is how the testing skyway (midway3 VM) for rcc-aws (account id 391009850283, PI Test): uses the IAM rcc-skyway as a trusted agent from the RCC-Skyway account (345587500613)
            # the ITS created a cloud account for the PI in the RCC Organizational Unit (OU) which specifies the IAM role rcc-skyway to manage this PI account.
            self.client = boto3.client('sts',
                aws_access_key_id = self.vendor['master_access_key_id'],
                aws_secret_access_key = self.vendor['master_secret_access_key'])

            self.assumed_role = self.client.assume_role(
                RoleArn = "arn:aws:iam::%s:role/%s" % (self.account['account_id'], self.account['role_name']), 
                RoleSessionName = "RCCSkyway"
            )
            credentials = self.assumed_role['Credentials']
            self.ec2 = boto3.resource('ec2',
                                      aws_access_key_id = credentials['AccessKeyId'],
                                      aws_secret_access_key = credentials['SecretAccessKey'],
                                      aws_session_token= credentials['SessionToken'],
                                      region_name = self.account['region'])
        self.using_libcloud = False
        if self.using_libcloud:
            EC2 = get_driver(Provider.EC2)
            self.driver = EC2(self.account['access_key_id'], self.account['secret_access_key'], self.account['region'])
        
        # copy ssh pem file to ~/, change the permission to 600
        pem_file_full_path = account_path + self.account['key_name'] + '.pem'
        self.my_ssh_private_key =  f"~/.my_aws_ssh_key.pem"
        cmd = f"cp {pem_file_full_path} {self.my_ssh_private_key}; chmod 600 {self.my_ssh_private_key}"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

       
    def list_nodes(self, show_protected_nodes=False, verbose=False):
        """Member function: list_nodes
        Get a list of all existed instances
        
        Return: a list of multiple turple. Each turple has four elements:
                (1) instance name (2) state (3) type (4) identifier
        """
        
        instances = self.get_instances()
        nodes = []

        df = pd.read_pickle(self.usage_history)
       
        for instance in instances:
            node_name = self.get_instance_name(instance)
            if show_protected_nodes == False and node_name in self.account['protected_nodes']:
                continue

            if instance.state['Name'] != 'terminated':

                # Calculate the running time
                if instance.state['Name'] == "running":
                    running_time = datetime.now(timezone.utc) - instance.launch_time
                else:
                    df_node = df.loc[df['InstanceID'] == instance.instance_id]
                    if df_node.empty == False:
                        end_time = pd.to_datetime(df_node['End'].iloc[0], format='%Y-%m-%dT%H:%M:%S.%f%z')
                        running_time = end_time - instance.launch_time
                    else:
                        continue
                
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                instance_user_name = self.get_instance_user_name(instance)

                nodes.append([self.get_instance_name(instance),
                              instance_user_name,
                              instance.state['Name'],
                              instance.instance_type, 
                              instance.instance_id,
                              instance.public_ip_address,
                              running_time,
                              running_cost])
        
        output_str = ''
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'User', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost'], maxcolwidths=None))
            print("")
        else:
            output_str = io.StringIO()
            print(tabulate(nodes, headers=['Name', 'User', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost']), file=output_str)
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
        self.capacity_exhausted = False
        if node_type not in self.vendor['node-types']:
            raise Exception(f'Node type {node_type} is not available in this account.')

        user_name = os.environ['USER']
        user_budget = self.get_budget(user_name=user_name, verbose=False)
        usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
        running_cost = self.get_running_cost(verbose=False)
        usage = usage + running_cost
        remaining_balance = user_budget - usage
        unit_price = self.vendor['node-types'][node_type]['price']

        if walltime is None or walltime == "":
            walltime_str = "00:30:00"
        else:
            walltime_str = walltime
        walltime_hours, walltime_in_minutes = parse_walltime(walltime_str)
        projected_cost = unit_price * walltime_hours

        if remaining_balance <= 0 or remaining_balance < projected_cost:
            print(f"User budget: ${user_budget:.3f}")
            print(f"+ Usage    : ${usage:.3f}")
            print(f"+ Available: ${remaining_balance:.3f}")
            print(f"The current budget is not sufficient for {walltime_str} at ${unit_price}/hr (projected cost: ${projected_cost:.3f}).")
            return

        if need_confirmation == True:
            print(f"User budget: ${user_budget:.3f}")
            print(f"+ Usage    : ${usage:.3f}")
            print(f"+ Available: ${remaining_balance:.3f}")
            response = input(f"Do you want to create an instance of type {node_type} (${unit_price}/hr)? (y/n) ")
            if response == 'n':
                return

        count = len(node_names)      
        node_name = node_names[0]

        print(Fore.BLUE + f"Allocating {count} instance ...", end="\n")
        
        # ImageID and KeyName provided by the account then user can connect to the running node
        #   if ImageID is from the vendor, KeyName from the account, ssh connections is denied
        vm_image = self.account['ami_id']
        if image_id != "":
            vm_image = image_id

        create_kwargs = dict(
            ImageId          = vm_image,                  # self.vendor['ami_id']
            KeyName          = self.account['key_name'],  # self.vendor['key_name']
            SecurityGroupIds = self.account['security_group'],
            InstanceType     = self.vendor['node-types'][node_type]['name'],
            MaxCount         = count,
            MinCount         = count,
            # cloud-init runs user data once per instance, so the walltime
            # holds even if this command is interrupted before the SSH step
            UserData         = walltime_boot_script(walltime_in_minutes),
            TagSpecifications=[
                {
                    'ResourceType' : 'instance',
                    'Tags' : [
                         {
                            'Key' : 'Name',
                            'Value' : node_name
                         },
                         {
                            'Key' : 'User',
                            'Value' : user_name
                         }
                    ]
                },

            ])
        preferred_zone = location if location else None
        zones_to_try = [preferred_zone] if preferred_zone else [None]
        instance_type_name = self.vendor['node-types'][node_type]['name']

        instances = None
        capacity_hit = False  # some zone was out of stock
        for zone_idx, zone in enumerate(zones_to_try):
            attempt_kwargs = dict(**create_kwargs)
            if zone:
                attempt_kwargs['Placement'] = {'AvailabilityZone': zone}
            try:
                instances = self.ec2.create_instances(**attempt_kwargs)
                for instance in instances:
                    instance.wait_until_running()
                if zone and zone != preferred_zone:
                    print(f"  (using fallback zone: {zone})")
                break
            except botocore.exceptions.ClientError as e:
                code = e.response['Error']['Code']
                if code in ('InsufficientInstanceCapacity', 'Unsupported'):
                    capacity_hit = capacity_hit or is_capacity_error(e)
                    #print(f'- Zone {zone or "auto"}: {instance_type_name} is not available.')
                    if len(zones_to_try) == 1:
                        all_azs = [az['ZoneName'] for az in
                                   self.ec2.meta.client.describe_availability_zones(
                                       Filters=[{'Name': 'state', 'Values': ['available']}]
                                   )['AvailabilityZones']]
                        fallbacks = [z for z in all_azs if z != zone]
                        zones_to_try.extend(fallbacks)
                        #print(f"  Retry in other zones:")
                else:
                    raise

        if instances is None:
            print(f"Failed to create {node_name} in any available zone.")
            self.capacity_exhausted = capacity_hit
            return {}

        nodes = {}
        # .pem file is the private key of the local machine that has a correponding public key listed
        # as in ~/.ssh/authorized_keys on the node
        path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        username = self.vendor['username']
        region = self.account['region']

        for inode, instance in enumerate(instances):
            instance.load()

            # record node_type, launch time
            instance_type = str(instance.instance_type)
            launch_time = instance.launch_time.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
            nodes[node_names[inode]] = [instance_type, launch_time, str(instance.public_ip_address)]

            # perform post boot tasks on each node
            #   + mounting storage (/home, /software) from io-server 172.31.47.245 (private IP of the rcc-io node) (rcc-aws, not using a trusted agent)
            #   + executing some custom scripts
            #   + shut down the instance after the walltime
            io_server = "172.31.47.245"
            ip = instance.public_ip_address
            ip_converted = ip.replace('.','-')

            print(f"\n\u2713 Created instance: {node_names[inode]}")

            # record the running time and cost at launch time and expected walltime
            # then if destroy_nodes() is invoked then updated the end time and cost
            
            running_time = timedelta(hours=walltime_hours)
            instance_unit_cost = self.get_unit_price_instance(instance)
            projected_running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
            usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
            end_time = instance.launch_time + running_time

            # store the record into the database
            data = [user_name, instance.instance_id, instance.instance_type,
                    instance.launch_time, end_time, projected_running_cost, remaining_balance]

            if os.path.isfile(self.usage_history):
                df = pd.read_pickle(self.usage_history)
            else:
                df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)
            
            print("\u2713 Preparing the instance...")
            time.sleep(30)
            try:
                utils.ssh_until_success(
                    f"ec2-{ip_converted}.{region}.compute.amazonaws.com",
                    username,
                    self.my_ssh_private_key,
                    f"sudo shutdown -P +{walltime_in_minutes}",
                )
            except RuntimeError as e:
                print(f"SSH setup failed for {node_names[inode]}: {str(e)}. Terminating instance to avoid unbounded charges.")
                try:
                    instance.terminate()
                except Exception:
                    pass
                nodes.pop(node_names[inode], None)
                traceback.print_exc()
                continue

            print("\u2713 To connect to the instance, run:")
            print(f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com or ")
            print(f"  skyway_connect --account={self.account_name} -J {node_names[inode]}")
            print(f"Instance public IP: {ip}")

            # execute the post boot script on the VM
            # need to install nfs-utils on the VM (or having an image that has nfs-utils installed) to mount available storage
            #    cmd = f"ssh -i {pem_file_full_path} {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com -t 'sudo mount -t nfs 172.31.47.245:/skyway /home' "
            #    cmd += f"-t ' sudo mkdir -p /software; sudo mount -t nfs {io_server}:/skyway /home; sudo mount -t nfs {io_server}:/software /software' "
            if self.post_boot_script != "":
                script_file = os.environ['SKYWAYROOT'] + "/etc/accounts/" + self.post_boot_script
                script_cmd = utils.script2cmd(script_file)
                utils.run_post_boot_script(f"ec2-{ip_converted}.{region}.compute.amazonaws.com",
                                           username, self.my_ssh_private_key, script_cmd)

            #  mount the storage attached to the io_node (optional)
            cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com "
            cmd += f" 'sudo mkdir -p /cloud/rcc-aws; sudo mount -t nfs {io_server}:/cloud/rcc-aws /cloud/rcc-aws' "
            p = subprocess.run(cmd, shell=True, text=True, capture_output=True)


        return nodes

    def connect_node(self, instance_ID, separate_terminal=True):
        """
        Connect to an instance using account's pem file
        [account_name].pem file should be under $SKYWAYROOT/etc/accounts
        It is important to create the node using the account's key-name.
        """
        print(f"Instance ID: {instance_ID}")
        ip = self.get_host_ip(instance_ID)
        print(f"\u2713 Connecting to instance public IP address: {ip}")

        username = self.vendor['username']
        region = self.account['region']
        ip_converted = ip.replace('.','-')

        # set up SSH tunneling to the localhost
        port=random.randint(15000, 30000)
        cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -f -N -L {port}:localhost:{port} {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com"
        print(f"SSH tunneling to the VM using port = {port}")
        os.system(cmd)

        if separate_terminal == True:
            cmd = "gnome-terminal -q --title='Connecting to the node' -- bash -c "
            cmd += f" 'module purge; ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com; exec bash' "
        else:
            cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com"

        os.system(cmd)

        node_info = {
            'private_key' : self.my_ssh_private_key,
            'login' : f"{username}@ec2-{ip_converted}.{region}.compute.amazonaws.com",
        }
        return node_info

    def get_node_connection_info(self, instance_ID):
        username = self.vendor['username']
        ip = self.get_host_ip(instance_ID)
        ip_converted = ip.replace('.','-')
        region = self.account['region']
        node_info = {
            'private_key' : self.my_ssh_private_key,
            'login' : f"{username}@ec2-{ip_converted}.{region}.compute.amazonaws.com",
        }
        return node_info

    def execute(self, instance_ID: str, **kwargs):
        '''
        execute commands on a node
        Example:
           execute(node_name='your-node', binary="python", arg1="input.txt", arg2="output.txt")
           execute(node_name='your-node', binary="mpirun -np 4 my_app", arg1="input.txt", arg2="output.txt")
        '''
        ip = self.get_host_ip(instance_ID)

        path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        pem_file_full_path = path + self.account['key_name'] + '.pem'
        username = self.vendor['username']
        region = self.account['region']
        ip_converted = ip.replace('.','-')

        command = ""
        for key, value in kwargs.items():
            command += value + " "

        cmd = "gnome-terminal -q --title='Connecting to the node' -- bash -c "
        cmd += f" 'ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com' -t '{command}' "
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)


    def execute_script(self, instance_ID: str, script_name: str):
        '''
        execute all the lines in a script on an instance
        Return: the exit status of the script (0 on success), so that callers
                like skyway_batch can report how the job ended.
        '''
        ip = self.get_host_ip(instance_ID)

        path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        pem_file_full_path = path + self.account['key_name'] + '.pem'
        username = self.vendor['username']
        region = self.account['region']
        ip_converted = ip.replace('.','-')

        script_cmd = utils.script2cmd(script_name)
        cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {username}@ec2-{ip_converted}.{region}.compute.amazonaws.com -t 'eval {script_cmd}' "
        # let the script write to the terminal as it runs: capturing the output
        # here would discard everything the job printed
        p = subprocess.run(cmd, shell=True, text=True)
        return p.returncode


    def destroy_nodes(self, node_names=None, IDs=None, need_confirmation=True):
        """Member function: destroy nodes
        Destroy all the nodes (instances) given the list of node names
                 - node_names: a list of node names to be destroyed
        NOTE: should store the running cost and time before terminating the node(s)
        NOTE: may need to revise for using IDs instead of node names, as IDs are unique
              for ID in IDs:
                  instance = self.ec2.Instance(ID)
                  if self.get_instance_name(instance) in self.account['protected_nodes']:
                      continue
        """
        
        user_name = os.environ['USER']
        if node_names is None and IDs is None:
            raise ValueError(f"node_names and IDs cannot be both empty.")

        # get all the available instances running or stopped
        avail_instances = self.get_instances(filters = [{
            "Name" : "instance-state-name",
            "Values" : ["running", "stopped"]
        }])

        instances = []
        for instance in avail_instances:
            instance_name = self.get_instance_name(instance)
            instance_id = instance.instance_id
            if instance_name in self.account['protected_nodes']:
                continue

            check_nodename = False
            check_id = False
            if node_names is not None:
                check_nodename = instance_name in node_names
            if IDs is not None:
                check_id = instance_id in IDs

            if check_nodename or check_id:
                # A stopped instance was already accounted for when it stopped;
                # closing its usage row here would backdate End to the terminate
                # and bill every idle hour in between.
                was_running = instance.state['Name'] == 'running'

                running_time = datetime.now(timezone.utc) - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                instance_user_name = self.get_instance_user_name(instance)
                if instance_user_name != user_name:
                    print(f"Cannot destroy an instance {instance_name} created by other users")
                    continue

                if need_confirmation == True:
                    cost_note = f" (running cost ${running_cost:0.5f})" if was_running \
                        else " (already stopped, no additional cost)"
                    response = input(f"Do you want to terminate the node {instance_name} {instance_id}{cost_note}? NOTE: Data on the node will be removed. (y/n) ")
                    if response != 'y':
                        continue

                instance.terminate()

                if not was_running:
                    print(f"{instance_name} was already stopped; usage history left unchanged.")
                    instances.append(instance)
                    continue

                # record the running time and cost
                end_time = datetime.now(timezone.utc)
                running_time = end_time - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)

                # store the record into the database
                data = [instance_user_name, instance.instance_id, instance.instance_type,
                        instance.launch_time, end_time, running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                # close the row for this session if one exists. launch_time
                # resets on every start, so it identifies the session; an
                # instance started outside Skyway has no row for it, and
                # closing the newest older row instead would overwrite a
                # correct, already-closed record and bill the gap in between.
                session_idx = self._find_session_row(df, instance.instance_id,
                                                     instance.launch_time)
                if session_idx is None:
                    df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                else:
                    self._close_usage_row(df, session_idx, end_time, instance_unit_cost)
                df.to_pickle(self.usage_history)

                instances.append(instance)

    def stop_nodes(self, IDs=[], node_names=[], need_confirmation=True):
        '''
        stop all the nodes (instances) given the list of node names
        NOTE: should store the running cost and time before stopping the node(s)
        node_names = list of node names as strings
        '''
        if isinstance(node_names, str): node_names = [node_names]
        if isinstance(IDs, str): IDs = [IDs]

        user_name = os.environ['USER']
        
        if node_names is None and IDs is None:
            raise ValueError(f"node_names and IDs cannot be both empty.")

        avail_instances = self.get_instances(filters = [{
                    "Name" : "instance-state-name",
                    "Values" : ["running"]
                }])

        instances = []
        for instance in avail_instances:
            instance_name = self.get_instance_name(instance)
            instance_id = instance.instance_id
            if instance_name in self.account['protected_nodes']:
                continue

            if instance_name in node_names or instance_id in IDs:

                running_time = datetime.now(timezone.utc) - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                instance_user_name = self.get_instance_user_name(instance)
                if instance_user_name != user_name:
                    print(f"Cannot stop an instance {instance_name} created by other users")
                    continue

                instance.stop()
   
                # record the running time and cost
                end_time = datetime.now(timezone.utc)
                running_time = end_time - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)

                # store the record into the database
                data = [instance_user_name, instance.instance_id, instance.instance_type,
                        instance.launch_time, end_time, running_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                if instance.instance_id not in df['InstanceID'].values:
                    df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                else:
                    # restart_nodes prepends one row per session, so the first
                    # match is the newest; close only that one out and leave the
                    # earlier sessions' timestamps intact
                    first_found_idx = df[df['InstanceID'] == instance.instance_id].index[0]
                    self._close_usage_row(df, first_found_idx, end_time, instance_unit_cost)
                df.to_pickle(self.usage_history)

                instances.append(instance)

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
        walltime_hours, walltime_in_minutes = parse_walltime(walltime_str)

        if node_names is None and IDs is None:
            raise ValueError(f"node_names and IDs cannot be both empty.")

        # get all the available instances that are stopped
        avail_instances = self.get_instances(filters = [{
                "Name" : "instance-state-name",
                "Values" : ["stopped"]
            }])

        for instance in avail_instances:
            instance_name = self.get_instance_name(instance)
            instance_id = instance.instance_id

            if instance_id in IDs or instance_name in node_names:
                if instance_name in self.account['protected_nodes']:
                    continue

                instance_user_name = self.get_instance_user_name(instance)
                if instance_user_name != user_name:
                    print(f"Cannot restart an instance {instance_name} from other users")
                    continue

                user_budget = self.get_budget(user_name=user_name, verbose=False)
                usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
                running_cost = self.get_running_cost(verbose=False)
                usage = usage + running_cost
                remaining_balance = user_budget - usage
                node_type = instance.instance_type
                unit_price = self.get_unit_price_instance(instance)
                projected_cost = unit_price * walltime_hours

                if remaining_balance <= 0 or remaining_balance < projected_cost:
                    print(f"User budget: ${user_budget:.3f}")
                    print(f"+ Usage    : ${usage:.3f}")
                    print(f"+ Available: ${remaining_balance:.3f}")
                    print(f"The current budget is not sufficient for {walltime_str} at ${unit_price}/hr (projected cost: ${projected_cost:.3f}).")
                    return

                if need_confirmation == True:
                    print(f"User budget: ${user_budget:.3f}")
                    print(f"+ Usage    : ${usage:.3f}")
                    print(f"+ Available: ${remaining_balance:.3f}")
                    response = input(f"Do you want to restart the instance of type {node_type} (${unit_price}/hr)? (y/n) ")
                    if response == 'n':
                        return

                print(Fore.BLUE + f"Allocating an instance ...", end=" ")

                instance.start()
                instance.wait_until_running()

                node_name = self.get_instance_name(instance)

                # record the new session before the SSH step, so the session is
                # accounted for even if scheduling the shutdown fails
                current_time = datetime.now(timezone.utc)
                session_end = current_time + timedelta(hours=walltime_hours)
                data = [instance_user_name, instance.instance_id, instance.instance_type,
                        current_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z'),
                        session_end.strftime('%Y-%m-%dT%H:%M:%S.%f%z'),
                        projected_cost, remaining_balance]

                if os.path.isfile(self.usage_history):
                    df = pd.read_pickle(self.usage_history)
                else:
                    df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])

                # prepend so this session is the first match for this instance ID
                df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
                df.to_pickle(self.usage_history)

                time.sleep(30)

                # make sure to shutdown the instance after the walltime (in minutes)
                host = instance.public_ip_address
                cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{host} 'sudo shutdown -P +{walltime_in_minutes}' "
                p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
                if p.returncode != 0:
                    self._abort_restart_session(
                        df, unit_price, node_name,
                        (p.stderr or '').strip() or f"ssh exited {p.returncode}",
                        lambda: instance.stop())
                    continue

                print(f'\nInstance {node_name} is up.')
                print("To connect to the instance, run:")
                print(f"  ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{host} or")
                print(f"  skyway_connect --account={self.account_name} -J {instance_name}")

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
      
    def get_cost_and_usage(self, start_date, end_date, verbose=True):
        # NOTES:
        #   1) the current IAM role of the master account is not allowed to get a cost explorer client
        #   need to use direct access key and secret from the account's user in the admin group
        #   2) for resource-level cost info, user needs to opt-in for daily/hourly monitoring which costs $$
        client = boto3.client('ce',
                              aws_access_key_id = self.account['access_key_id'],
                              aws_secret_access_key = self.account['secret_access_key'],
                              region_name = self.account['region'])
    
        # Query the cost and usage data
        response = client.get_cost_and_usage_with_resources(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity='DAILY',
            Metrics=['BlendedCost', 'UsageQuantity'],
            Filter={
                "Dimensions": { "Key": "SERVICE", 'Values': ['Amazon Elastic Compute Cloud - Compute'] }
            },
            GroupBy=[
                {
                    'Type': 'DIMENSION',
                    'Key': 'RESOURCE_ID'
                }
            ]
        )
        
        # Return the response
        if verbose == True:
            print(response['ResultsByTime'])
        return response

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
            data = [user_name, "--", "--", "00:00:00", "00:00:00", "0.0", user_budget]
            df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            #df = pd.DataFrame(columns=['User','InstanceID','InstanceType','Start','End', 'Cost', 'Balance'])
            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)
            return 0, user_budget

        df = pd.read_pickle(self.usage_history)
        df_user = df.loc[df['User'] == user_name]
        df_user = df_user.astype({"Cost": float})
        accumulating_cost = df_user['Cost'].sum()
        user_budget = self.get_budget(user_name=user_name, verbose=False)
        remaining_balance = float(user_budget) - float(accumulating_cost)

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

    def get_budget_api(self):
        '''
        get the budget from the cloud account
        '''
        client = boto3.client('budgets',
                              aws_access_key_id = self.account['access_key_id'],
                              aws_secret_access_key = self.account['secret_access_key'],
                              region_name = self.account['region'])
        response = client.describe_budgets(
            AccountId=self.account['account_id']
        )

        print(response)

    def get_budget(self, user_name=None, verbose=True):
        '''
        get the budget from the account file
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

    def get_running_nodes(self, verbose=False):
        """Member function: running_nodes
        Return identifiers of all running instances
        """

        instances = self.get_instances(filters = [{
            "Name" : "instance-state-name",
            "Values" : ["running"]
        }])
        
        nodes = []
        
        for instance in instances:
            nodes.append([self.get_instance_name(instance),
                              instance.state['Name'], 
                              instance.instance_type, 
                              instance.instance_id])
        
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Host IP']))
            print("")


        return nodes

    def get_host_ip(self, instance_ID):
        """Member function: get the IP address of an instance (node) 
         - ID: instance identifier
        """
        
        if instance_ID[0:2] == 'i-':
            instances = self.get_instances(filters = [{
                "Name" : "instance-id",
                "Values" : [instance_ID]
            }])
        else:
            instances = self.get_instances(filters = [{
                "Name" : "tag:Name",
                "Values" : [instance_ID]
            }])
        
        return list(instances)[0].public_ip_address


    def get_all_images(self, owners=['self']):
        try:
            # Describe images to get all AMIs
            images = self.ec2.images.filter(Owners=owners)

            for image in images:
                print(f"Image ID: {image.id}, Name: {image.name}, Description: {image.description}")

        except Exception as e:
            print(f"An error occurred: {e}")

    def get_instance_name(self, instance):
        """Member function: get_instance_name
        Get the name information from the instance with given ID.
        Note: AWS doesn't use unique name for instances, instead, name is an
        attribute stored in the tags.
        
         - instance: an instance self.ec2.Instance()
        """
        
        if instance.tags is None: return ''

        for tag in instance.tags:
            if tag['Key'] == 'Name':
                return tag['Value']

        return ''

    def get_instance_ID(self, instance_name: str):
        """Member function: get_instance_name
        Get the instance ID from the instance name
        Note: AWS doesn't use unique name for instances, instead, name is an
        attribute stored in the tags.        
        """
        running_instances = self.get_instances(filters = [{
                    "Name" : "instance-state-name",
                    "Values" : ["running"]
        }])
                
        for instance in running_instances:
            if instance.tags is None: continue

            for tag in instance.tags:
                if tag['Key'] == 'Name':
                    if tag['Value'] == instance_name:
                        return instance.instance_id
        return ''

    def get_instance_user_name(self, instance):
        """Member function: get_instance_user_name
        Get the user name information from the instance.
        
         - instance: an instance self.ec2.Instance()
        """
        
        if instance.tags is None: return ''

        for tag in instance.tags:
            if tag['Key'] == 'User':
                return tag['Value']
        
        return ''


    def get_instances(self, filters = []):
        """Member function: get_instances
        Get a list of instance objects with give filters
        NOTE: if using libcloud then use self.driver.list_nodes()
        """
        return self.ec2.instances.filter(Filters = filters)

    def get_unit_price_instance(self, instance):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. t2.micro)
        """
        for node_type in self.vendor['node-types']:
            if self.vendor['node-types'][node_type]['name'] == instance.instance_type:
                unit_price = self.vendor['node-types'][node_type]['price']
                return unit_price
        return -1.0

    def get_unit_price(self, node_type: str):
        """
        Get the per-hour price of an instance depending on its node type (e.g. t1)
        """
        if node_type in self.vendor['node-types']:
            return self.vendor['node-types'][node_type]['price']
        return -1.0

    def get_running_cost(self, verbose=True, user_name=None):
        instances = self.get_instances()
        if user_name is None:
            user_name = os.environ['USER']

        nodes = []
        total_cost = 0.0
        for instance in instances:
            
            if self.get_instance_name(instance) in self.account['protected_nodes']:
                continue

            if instance.state['Name'] == 'running':
                instance_user_name = self.get_instance_user_name(instance)
                if user_name != instance_user_name:
                    continue

                running_time = datetime.now(timezone.utc) - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                total_cost = total_cost + running_cost
                nodes.append([self.get_instance_name(instance),
                                    instance.state['Name'], 
                                    instance.instance_type, 
                                    instance.instance_id,
                                    running_time,
                                    running_cost])
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'ElapsedTime', 'RunningCost']))

        return total_cost

    def get_private_key(self):
        return self.my_ssh_private_key