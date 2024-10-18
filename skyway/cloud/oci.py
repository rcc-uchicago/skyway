# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Trung Nguyen, Yuxing Peng

"""@package docstring
Documentation for OCI Class
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

# Oracle Cloud Infrastructure (OCI) Python SDK
import oci

class OCI(Cloud):
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
        if account_cfg['cloud'] != 'oci' :
            raise Exception(f'Service provider oci is not associated with this account.')

        for k, v in account_cfg.items():
            setattr(self, k.replace('-','_'), v)

        self.account_path = account_path

        # specific to OCI account config
        api_key_pem_full_path = account_path + self.account['api_key_name']
        if ".pem" not in api_key_pem_full_path:
            api_key_pem_full_path += ".pem"
        self.config = {
            "user": self.account['user'],
            "key_file": api_key_pem_full_path,
            "fingerprint": self.account['fingerprint'],
            "tenancy": self.account['tenancy'],
            "region": self.account['region']
        }

        self.identity_client = oci.identity.IdentityClient(self.config)
        self.compute_client = oci.core.ComputeClient(self.config)
        self.compute_client_composite_operations = oci.core.ComputeClientCompositeOperations(self.compute_client)

        self.usage_history = f"{account_path}usage-{account}.pkl"

        # load cloud.yaml under $SKYWAYROOT/etc/
        cloud_path = os.environ['SKYWAYROOT'] + '/etc/'
        vendor_cfg = utils.load_config('cloud', cloud_path)
        if 'oci' not in vendor_cfg:
            raise Exception(f'Cloud vendor oci is undefined.')

        self.vendor = vendor_cfg['oci']
        self.account_name = account
        self.onpremises = False

        # copy ssh pem file to ~/, change the permission to 400
        pem_file_full_path = account_path + self.account['private_key']
        self.my_ssh_private_key =  f"~/.my_oci_ssh_key.pem"
        cmd = f"cp {pem_file_full_path} {self.my_ssh_private_key}; chmod 400 {self.my_ssh_private_key}"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

    def list_nodes(self, show_protected_nodes=False, verbose=False):
        """Member function: list_nodes
        Get a list of all existed instances
        
        Return: a list of multiple turple. Each turple has four elements:
                (1) instance name (2) state (3) type (4) identifier
        """
        
        
        instances = self.get_instances()
        nodes = []

        for instance in instances:
            node_name = self.get_instance_name(instance)
            if show_protected_nodes == False and node_name in self.account['protected_nodes']:
                continue

            if instance.lifecycle_state != 'Terminated':
                running_time = datetime.now(timezone.utc) - instance.time_created
                
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost

                public_ip_address = self.get_host_ip(instance)
                instance_type = instance.shape
                nodes.append([instance.display_name,
                              instance.lifecycle_state,
                              instance_type,
                              instance.id,
                              public_ip_address,
                              running_time,
                              running_cost])
        
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
        """Member function: create_compute
        Create a group of compute instances(nodes, servers, virtual-machines 
        ...) with the given type.
        
         - node_type: instance type information from the Skyway definitions
         - node_names: a list of names for the nodes, to get the number of nodes
        
        Return: a dictionary of instance ID (i.e., names) for created instances.
        """
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
            response = input(f"Do you want to create an instance of type {node_type} (${unit_price}/hr)? (y/n) ")
            if response == 'n':
                return

        count = len(node_names)      
        node_name = node_names[0]
        print(Fore.BLUE + f"Allocating {count} instance ...", end=" ")

        # ImageID and KeyName provided by the account then user can connect to the running node
        #   if ImageID is from the vendor, KeyName from the account, ssh connection is denied

        vnic_details = oci.core.models.CreateVnicDetails(
            subnet_id=self.account['subnet_id'],
            assign_public_ip=True,
            display_name='my_instance_vnic',
            hostname_label='my-instance'
        )

        public_key_file = self.account_path + "/" + self.account['public_key']
        ssh_pub_key = open(public_key_file).read()

       
        list_availability_domains_response = oci.pagination.list_call_get_all_results(
            self.identity_client.list_availability_domains,
            self.account['compartment_id']
        )
        availability_domain = list_availability_domains_response.data[0]

        vm_image = self.account['image_id']
        if image_id != "":
            vm_image = image_id

        instance_details = oci.core.models.LaunchInstanceDetails(
            compartment_id = self.account['compartment_id'],
            availability_domain = availability_domain.name,
            shape = self.vendor['node-types'][node_type]['name'],
            shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=1, memory_in_gbs=1),
            display_name = 'my_instance',
            create_vnic_details = vnic_details,
            image_id = vm_image,
            metadata = {
                'ssh_authorized_keys': ssh_pub_key,
                'Name': node_name,
                'User': user_name,
                'node_type': self.vendor['node-types'][node_type]['name'],
            }
        )

        # Launch the instance
        launch_instance_response = self.compute_client_composite_operations.launch_instance_and_wait_for_state(
            instance_details,
            wait_for_states=[oci.core.models.Instance.LIFECYCLE_STATE_RUNNING]
        )
        instance = launch_instance_response.data

        nodes = {}
        # .pem file is the private key of the local machine that has a correponding public key listed
        # as in ~/.ssh/authorized_keys on the node
        path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        pem_file_full_path = path + self.account['private_key']
        username = self.vendor['username']
        public_ip = self.get_host_ip(instance)

        if walltime is None:
            walltime_str = "00:05:00"
        else:
            walltime_str = walltime

        # shutdown the instance after the walltime (in minutes)
        pt = datetime.strptime(walltime_str, "%H:%M:%S")
        walltime_in_minutes = int(pt.hour * 60 + pt.minute + pt.second/60)

        # record node_type, launch time
        instance_type = str(self.vendor['node-types'][node_type]['name'])
        launch_time = instance.time_created.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        nodes[node_names[0]] = [instance_type, launch_time, str(public_ip)]

        # perform post boot tasks on each node
        #   + mounting storage (/home, /software) from io-server 172.31.47.245 (private IP of the rcc-io node) (rcc-aws, not using a trusted agent)
        #   + executing some custom scripts
        #   + shut down the instance after the walltime
        #io_server = "172.31.47.245"
        
        #ip_converted = ip.replace('.','-')

        print(f"\nCreated instance: {instance.display_name}")

        # need to install nfs-utils on the VM (or having an image that has nfs-utils installed)
        print(f"To connect to the instance, run:")
        cmd = f"  ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{public_ip} or"
        print(f"  skyway_connect --account={self.account_name} -J {instance.display_name}")
        print(f"{cmd}")
        cmd += f" -t 'sudo shutdown -P {walltime_in_minutes}'; bash "
        #cmd += f"-t 'sudo shutdown -P {walltime_in_minutes}; sudo mount -t nfs {io_server}:/software /software' "
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

        return nodes

    def connect_node(self, instance, separate_terminal=True):
        """
        Connect to an instance using account's pem file
        It is important to create the node using the account's key-name.
        """
        public_ip = self.get_host_ip(instance)
        username = "opc"
        
        if separate_terminal == True:
            cmd = "gnome-terminal -q --title='Connecting to the node' -- bash -c "
            cmd += f" 'ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{public_ip}' "
        else:
            cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{public_ip}"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        #os.system(cmd)

        node_info = {
            'private_key' : self.my_ssh_private_key,
            'login' : f"{username}@{public_ip}",
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
        username = self.vendor['username']

        command = ""
        for key, value in kwargs.items():
            command += value + " "

        cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{ip}' -t '{command}'"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)


    def execute_script(self, instance_ID: str, script_name: str):
        '''
        execute all the lines in a script on an instance
        '''
        ip = self.get_host_ip(instance_ID)

        path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        pem_file_full_path = path + self.account['key_name'] + '.pem'
        username = self.vendor['username']
        region = self.account['region']
        ip_converted = ip.replace('.','-')

        script_cmd = utils.script2cmd(script_name)
        cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=accept-new {username}@{ip} -t 'eval {script_cmd}' "
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)


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

        # List all instances in the compartment
        instance_list = oci.pagination.list_call_get_all_results(
            self.compute_client.list_instances,
            self.account['compartment_id']
        ).data

        # Filter the instances to get only the running ones
        running_instances = [instance for instance in instance_list if instance.lifecycle_state == 'RUNNING']

        # Terminate instances with the given names
        for node in node_names:
            for instance in running_instances:
                if instance.display_name == node:
                    self.compute_client_composite_operations.terminate_instance_and_wait_for_state(
                        instance.id,
                        wait_for_states=[oci.core.models.Instance.LIFECYCLE_STATE_TERMINATED]
                    )


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
        pass

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
        
        history = df_user[['User','InstanceID','InstanceType','Start','End']]
        return history

    def get_budget_api(self):
        '''
        get the budget from the cloud account
        '''

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

    def get_host_ip(self, instance):
        """Member function: get the IP address of an instance (node) 
         - ID: instance identifier
        """
        public_ip = ""
        vn_client = oci.core.VirtualNetworkClient(self.config)

        vnic_attachments = self.compute_client.list_vnic_attachments(
            compartment_id=instance.compartment_id,
            instance_id=instance.id
        ).data

        if vnic_attachments:
            vnic_id = vnic_attachments[0].vnic_id

            # Get the VNIC details
            vnic = vn_client.get_vnic(vnic_id).data
            
            # Retrieve the public IP address
            public_ip = vnic.public_ip
            print(f"Public IP Address: {public_ip}")
        else:
            print("No VNIC attachments found for this instance.")
        
        return public_ip


    def get_all_images(self, owners=['self']):
        try:
            list_images_response = oci.pagination.list_call_get_all_results(
                self.compute.list_images,
                self.compartment_id,
            )
            images = list_images_response.data

            for image in images:
                print(f"Image ID: {image.id}, Name: {image.name}, Description: {image.description}")

        except Exception as e:
            print(f"An error occurred: {e}")

    def get_instance_name(self, instance):
        """Member function: get_instance_name
        Get the name information from the instance with given ID.
        Note: AWS doesn't use unique name for instances, instead, name is an
        attribute stored in the tags.
        
         - instance:
        """
        
        return instance.display_name

    def get_instance_ID(self, instance_name: str):
        """Member function: get_instance_name
        Get the instance ID from the instance name
        Note: AWS doesn't use unique name for instances, instead, name is an
        attribute stored in the tags.        
        """
        running_instances = self.get_instances()
                
        for instance in running_instances:
            if instance.tags is None: continue

            for tag in instance.tags:
                if tag['Key'] == 'Name':
                    if tag['Value'] == instance_name:
                        return instance.id
        return ''

    def get_instance_user_name(self, instance):
        """Member function: get_instance_user_name
        Get the user name information from the instance.
        
         - instance:
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
        instance_list = oci.pagination.list_call_get_all_results(
            self.compute_client.list_instances, self.account['compartment_id']
        ).data

        # Filter the instances to get only the running ones
        instances = [instance for instance in instance_list if instance.lifecycle_state == 'RUNNING']
        return instances

    def get_unit_price_instance(self, instance):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. t2.micro)
        """
        for node_type in self.vendor['node-types']:
            if self.vendor['node-types'][node_type]['name'] == instance.shape:
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

    def get_running_cost(self, verbose=True):
        instances = self.get_instances()

        nodes = []
        total_cost = 0.0
        for instance in instances:
            
            if self.get_instance_name(instance) in self.account['protected_nodes']:
                continue

            if instance.state['Name'] == 'running':
                running_time = datetime.now(timezone.utc) - instance.launch_time
                instance_unit_cost = self.get_unit_price_instance(instance)
                running_cost = running_time.seconds/3600.0 * instance_unit_cost
                total_cost = total_cost + running_cost
                nodes.append([self.get_instance_name(instance),
                                    instance.state['Name'], 
                                    instance.shape, 
                                    instance.instance_id,
                                    running_time,
                                    running_cost])
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'ElapsedTime', 'RunningCost']))

        return total_cost
    

    def get_availability_domain(identity, compartment_id):
        list_availability_domains_response = oci.pagination.list_call_get_all_results(
                    identity.list_availability_domains, compartment_id)
        # just return the first availability domain
        # but for Production code you should have a better way of determining what is needed
        availability_domain = list_availability_domains_response.data[0]
        return availability_domain.name