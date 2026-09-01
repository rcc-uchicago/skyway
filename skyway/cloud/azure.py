# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Trung Nguyen
"""@package docstring
Documentation for Azure Class
"""

from datetime import datetime, timezone
import io
import logging
import os
import random
import subprocess
from tabulate import tabulate
import time
import traceback

from .core import Cloud
from .. import utils

from colorama import Fore
import pandas as pd

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.network.models import PublicIPAddress, PublicIPAddressSku, NetworkSecurityGroup, SecurityRule
from azure.core.exceptions import HttpResponseError
from azure.mgmt.compute.models import (
    HardwareProfile,
    StorageProfile,
    OSProfile,
    NetworkProfile,
    LinuxConfiguration,
    SshConfiguration,
    SshPublicKey,
    VirtualMachine
)

from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
from libcloud.compute.drivers.azure_arm import AzureImage, NodeAuthSSHKey

class AZURE(Cloud):

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
        if account_cfg['cloud'] != 'azure' :
            raise Exception(f'Cloud vendor azure is not associated with this account.')

        for k, v in account_cfg.items():
            setattr(self, k.replace('-','_'), v)

        public_key_file = account_path + self.account['public_key']
        with open(public_key_file, "r") as f:
            content = f.read()
            self.public_key = content.strip()

        self.private_key_file = account_path + self.account['private_key']

        self.usage_history = f"{account_path}usage-{account}.pkl"

        # load cloud.yaml under $SKYWAYROOT/etc/
        cloud_path = os.environ['SKYWAYROOT'] + '/etc/'
        vendor_cfg = utils.load_config('cloud', cloud_path)
        if 'azure' not in vendor_cfg:
            raise Exception(f'Service provider azure is undefined.')
      
        self.vendor = vendor_cfg['azure']
        self.account_name = account
        self.onpremises = False
        self.post_boot_script = self.account.get('post_boot_script', "")

        self.credentials = ClientSecretCredential(client_id=self.account['client_id'],
                                                  client_secret=self.account['client_secret'],
                                                  tenant_id=self.account['tenant_id'])

        # copy ssh pem file to ~/, change the permission to 600
        pem_file_full_path = self.private_key_file
        self.my_ssh_private_key =  f"~/.my_azure_ssh_key.pem"
        cmd = f"cp {pem_file_full_path} {self.my_ssh_private_key}; chmod 600 {self.my_ssh_private_key}"
        p = subprocess.run(cmd, shell=True, text=True, capture_output=True)
       

    def list_nodes(self, show_protected_nodes=False, verbose=False):
        """Member function: list_nodes
        Get a list of all existed instances
        
        Return: a list of multiple turple. Each turple has four elements:
                (1) instance name (2) state (3) type (4) running time
                node.id is useful for destroying
        """
        nodes = []
        current_time = datetime.now(timezone.utc)

        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        
        for node in compute_client.virtual_machines.list_all():

            # Get the creation time of the instance

            # Convert the creation time from string to datetime object
            # Azure returns 7-digit after '.' for seconds, so need to truncate the last digit 
            # to cast into %Y-%m-%dT%H:%M:%S.%f%z format
            
            creation_time = node.time_created
            
            # Calculate the running time
            running_time = current_time - creation_time

            # get the node type
            node_type = node.hardware_profile.vm_size
            instance_unit_cost = self.get_unit_price_instance(node)
            
            running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
            state = self.get_instance_status(node)
            public_ip = self.get_host_ip(node.name)
            nodes.append([node.name, node.tags.get('user'), state, node_type, node.vm_id, public_ip, running_time, running_cost])

        output_str = ''
        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'User','Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost'], maxcolwidths=None))
            print("")
        else:
            output_str = io.StringIO()
            print(tabulate(nodes, headers=['Name', 'User', 'Status', 'Type', 'Instance ID', 'Host', 'Elapsed Time', 'Running Cost'], maxcolwidths=None), file=output_str)
            print("", file=output_str)
        return nodes, output_str            

    def create_nodes(self, node_type: str, node_names = [], interactive = False, need_confirmation = True, walltime = None, image_id = "", location = ""):

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
        pt = datetime.strptime(walltime_str, "%H:%M:%S")
        walltime_hours = pt.hour + pt.minute / 60 + pt.second / 3600
        walltime_in_minutes = int(pt.hour * 60 + pt.minute + pt.second / 60)
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
        print(Fore.BLUE + f"Allocating {count} instance ...", end="\n")

        nodes = {}
        node_cfg = self.vendor['node-types'][node_type]
        size_name = node_cfg['name']           # e.g. "Standard_DS1_v2"

        if location != "":
           location_name = location
        else:
           location_name = 'Central US'
        print(f"\nLocation: {location_name}\n")
        #location_name = 'Central US'  # Replace with your desired location
        #locations = self.driver.list_locations()
        #location = next((loc for loc in locations if loc.name == location_name), None)
        #if location is None:
            #raise ValueError(f"Location '{location_name}' not found.")

        # authentication with public key on this machine per-user (id_rsa_azure.pub)
        # need to read in from ~/.ssh/id_rsa_azure.pub from the account .yaml file
        #auth = NodeAuthSSHKey(self.public_key)

        # Initialize Azure management clients
        subscription_id = self.account['subscription_id']
        resource_client = ResourceManagementClient(self.credentials, subscription_id)
        network_client = NetworkManagementClient(self.credentials, subscription_id)
        compute_client = ComputeManagementClient(self.credentials, subscription_id)

        #sizes = self.driver.list_sizes(location=location)
        #size = next((s for s in sizes if s.name == size_name), None)
        #if size is None:
        #    raise ValueError(f"Size '{size_name}' not found.")

        # select an image -- ignore image_id for now (see below when creating VM)
        #publisher = 'Canonical'
        #offer = 'UbuntuServer'
        #sku = '22.04-LTS'
        #version = 'latest'
        #image = AzureImage(version=version, publisher=publisher, sku=sku, offer=offer, driver=self.driver, location=location)

        # Step 2: Create a resource group if it doesn't exist    
        # resource group is already created on the subscription (could move to account)
        resource_group_name = self.account['resource_group']   #"rg_skyway"
        resource_client.resource_groups.create_or_update(resource_group_name, {"location": location_name})

        # then for each node in the list
        for node_name in node_names:
            
            # Step 3: Create Virtual Network and Subnet if they don't exist
            vnet_name = f"vnet-{user_name}-{node_name}"
            subnet_name = f"subnet-{user_name}-{node_name}"
            vnet_params = {
                "location": location_name,
                "address_space": {"address_prefixes": ["10.0.0.0/16"]}
            }
            network_client.virtual_networks.begin_create_or_update(resource_group_name, vnet_name, vnet_params).result()

            subnet_params = {
                "address_prefix": "10.0.0.0/24"
            }
            network_client.subnets.begin_create_or_update(resource_group_name, vnet_name, subnet_name, subnet_params).result()

            subnet = network_client.subnets.get(resource_group_name, vnet_name, subnet_name)

            # Create Network Security Group with inbound SSH rule
            nsg_name = f"nsg-{user_name}-{node_name}"
            nsg = network_client.network_security_groups.begin_create_or_update(
                resource_group_name,
                nsg_name,
                NetworkSecurityGroup(location=location_name)
            ).result()

            
            # Inbound SSH rule
            network_client.security_rules.begin_create_or_update(
                resource_group_name,
                nsg.name,
                "AllowSSH",
                SecurityRule(
                    protocol="Tcp",
                    direction="Inbound",
                    source_address_prefix="*",
                    destination_address_prefix="*",
                    access="Allow",
                    priority=1000,
                    source_port_range="*",
                    destination_port_range="22",
                    name="AllowSSH"
                )
            ).result()

            # Step 4: Create a network interface with the NSG and public IP address
  
            public_ip_name=f'my_public_ip-{user_name}-{node_name}'
            public_ip_params = PublicIPAddress(
                    location=location_name,
                    sku=PublicIPAddressSku(name="Standard"),  # <- avoid Basic SKU limit
                    public_ip_allocation_method="Static",
                )

            public_ip = network_client.public_ip_addresses.begin_create_or_update(
                    resource_group_name, public_ip_name, public_ip_params
                ).result()

            nic_name = f"my-nic-{user_name}-{node_name}"
            ip_config = {
                "name": "ipconfig1",
                "subnet": { "id": subnet.id },
                "public_ip_address": {"id": public_ip.id}
            }
        
            nic_params = {
                "location": location_name,
                "ip_configurations": [ip_config],
                "network_security_group": NetworkSecurityGroup(id=nsg.id),
            }
            network_interface = network_client.network_interfaces.begin_create_or_update(resource_group_name,
                                                                                         nic_name,
                                                                                         nic_params).result()
            # Step 5: Create the instance
            node = None
            try:
                tags = { 'node_name': node_name, 'user': user_name }
                vm_params = VirtualMachine(
                    location=location_name,
                    hardware_profile=HardwareProfile(vm_size=size_name),
                    storage_profile=StorageProfile(
                        image_reference={
                            "publisher": "Canonical",
                            "offer": "UbuntuServer",
                            "sku": "18.04-LTS",
                            "version": "latest",
                        }
                    ),
                    os_profile=OSProfile(
                        computer_name=node_name,
                        admin_username=user_name,
                        linux_configuration=LinuxConfiguration(
                            disable_password_authentication=True,
                            ssh=SshConfiguration(
                                public_keys=[SshPublicKey(path=f"/home/{user_name}/.ssh/authorized_keys",
                                                           key_data=self.public_key)]
                            )
                        )
                    ),
                    network_profile=NetworkProfile(network_interfaces=[{"id": network_interface.id}]),
                    tags=tags,
                )

                node = compute_client.virtual_machines.begin_create_or_update(resource_group_name, node_name, vm_params).result()

            except Exception as ex:
                logging.info("Failed to create %s. Reason: %s" % (node_name, str(ex)))
            except HttpResponseError as e:
                print(f"VM creation failed: {e.message}")

            #node_type = node.extra.get('properties')['hardwareProfile']['vmSize']
            if node is not None:
                node_type = size_name
                #creation_time_str = node.extra.get('properties')['timeCreated']
                creation_time_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f%z')
                nodes[node_name] = [str(node.id), node_type, creation_time_str]

                print(f"\n\u2713 Created instance: {node_name}")
                # ssh to the node and execute a shutdown command scheduled for walltime
                public_ip_address = network_client.public_ip_addresses.get(
                    resource_group_name, public_ip_name
                )
                public_ip = public_ip_address.ip_address

                print("\u2713 Preparing the instance...")
                time.sleep(30)
                try:
                    utils.ssh_until_success(
                        public_ip,
                        user_name,
                        self.my_ssh_private_key,
                        f"sudo shutdown -P +{walltime_in_minutes}",
                    )
                except RuntimeError as e:
                    print(f"SSH setup failed for {node_name}: {str(e)}. Terminating instance to avoid unbounded charges.")
                    try:
                        compute_client.virtual_machines.begin_delete(resource_group_name, node_name).result()
                    except Exception:
                        pass
                    nodes.pop(node_name, None)
                    traceback.print_exc()
                    continue

                print(f"Instance public IP: {public_ip}")

                # execute the post boot script on the VM
                # need to install gcsfuse or nfs-utils on the VM (or having an image that has gcsfuse installed) to mount available storage
                if self.post_boot_script != "":
                    script_file = os.environ['SKYWAYROOT'] + "/etc/accounts/" + self.post_boot_script
                    script_cmd = utils.script2cmd(script_file)
                    cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{public_ip} '{script_cmd}' "
                    p = subprocess.run(cmd, shell=True, text=True, capture_output=True)

        return nodes

    def execute(self, instance_ID: str, **kwargs):
        '''
        execute commands on a node
        Example:
           execute(node_name='your-node', binary="python", arg1="input.txt", arg2="output.txt")
           execute(node_name='your-node', binary="mpirun -np 4 my_app", arg1="input.txt", arg2="output.txt")
        '''
        
        command = ""
        for key, value in kwargs.items():
            command += value + " "

        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        vm = None
        for instance in compute_client.virtual_machines.list_all():
            if instance.vm_id == instance_ID:
                vm = instance
                break

        if vm is None:
            print(f"No VM found for {instance_ID} with user {os.environ['USER']}")
            return

        node_name = vm.name
        host = self.get_host_ip(node_name)
        user_name = os.environ['USER']

        cmd = "gnome-terminal -q --title='Connecting to the node' -- bash -c "
        cmd += f" 'ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{host}' -t '{command}' "
        subprocess.run(cmd, shell=True, text=True, capture_output=True)
        

    def connect_node(self, instance_ID, separate_terminal=True):
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        vm = None
        for instance in compute_client.virtual_machines.list_all():
            if instance.vm_id == instance_ID:
                vm = instance
                break

        if vm is None:
            print(f"No VM found for {instance_ID} with user {os.environ['USER']}")
            return

        node_name = vm.name
        public_ip = self.get_host_ip(node_name)
        user_name = os.environ['USER']
        
        print(f"\u2713 Connecting to instance public IP address: {public_ip}")

        node_info = {
            'private_key' : self.my_ssh_private_key,
            'login' : f"{user_name}@{public_ip}",
        }

        # set up SSH tunneling to the localhost
        port=random.randint(15000, 30000)
        cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -f -N -L {port}:localhost:{port} {user_name}@{public_ip}"
        print(f"SSH tunneling to the VM using port = {port}")
        os.system(cmd)

        if separate_terminal == True:
            cmd = "gnome-terminal --title='Connecting to the node' -- bash -c "
            cmd += f" 'ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{public_ip}; exec bash' "
        else:
            cmd = f"ssh -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{public_ip}"

        os.system(cmd)

        return node_info

    def execute_script(self, instance_ID: str, script_name: str):
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        vm = None
        for instance in compute_client.virtual_machines.list_all():
            if instance.vm_id == instance_ID:
                vm = instance
                break
        if vm is None:
            print(f"Node {instance_ID} does not exist.")
            return
        host = self.get_host_ip(vm.name)
        user_name = os.environ['USER']
        script_cmd = utils.script2cmd(script_name)
        cmd = f"ssh -t -i {self.my_ssh_private_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {user_name}@{host} '{script_cmd}' "
        os.system(cmd)

    def stop_nodes(self, IDs=[], node_names=[], need_confirmation=True):
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        resource_group_name = self.account['resource_group']
        user_name = os.environ['USER']
        if need_confirmation:
            response = input(f"Do you want to stop (deallocate) {node_names or IDs}? (y/n) ")
            if response != 'y':
                return
        for vm_name in node_names:
            print(f"Stopping VM: {vm_name}")
            compute_client.virtual_machines.begin_deallocate(resource_group_name, vm_name).result()
            print(f"  VM {vm_name} stopped.")

    def restart_nodes(self, IDs=[], node_names=[], need_confirmation=True, walltime=None):
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        resource_group_name = self.account['resource_group']

        user_name = os.environ['USER']
        user_budget = self.get_budget(user_name=user_name, verbose=False)
        usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
        running_cost = self.get_running_cost(verbose=False)
        usage = usage + running_cost
        remaining_balance = user_budget - usage

        if walltime is None or walltime == "":
            walltime_str = "00:30:00"
        else:
            walltime_str = walltime
        pt = datetime.strptime(walltime_str, "%H:%M:%S")
        walltime_hours = pt.hour + pt.minute / 60 + pt.second / 3600

        for vm_name in node_names:
            vm = compute_client.virtual_machines.get(resource_group_name, vm_name)
            unit_price = self.get_unit_price_instance(vm)
            projected_cost = unit_price * walltime_hours if unit_price is not None else 0.0

            if remaining_balance <= 0 or remaining_balance < projected_cost:
                print(f"User budget: ${user_budget:.3f}")
                print(f"+ Usage    : ${usage:.3f}")
                print(f"+ Available: ${remaining_balance:.3f}")
                print(f"The current budget is not sufficient for {walltime_str} at ${unit_price}/hr (projected cost: ${projected_cost:.3f}).")
                return

            if need_confirmation:
                print(f"User budget: ${user_budget:.3f}")
                print(f"+ Usage    : ${usage:.3f}")
                print(f"+ Available: ${remaining_balance:.3f}")
                response = input(f"Do you want to restart {vm_name}? (y/n) ")
                if response != 'y':
                    return

            print(f"Starting VM: {vm_name}")
            compute_client.virtual_machines.begin_start(resource_group_name, vm_name).result()
            print(f"  VM {vm_name} started.")

    def get_node_connection_info(self, instance_ID):
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        vm = None
        for instance in compute_client.virtual_machines.list_all():
            if instance.vm_id == instance_ID:
                vm = instance
                break

        if vm is None:
            print(f"No VM found for {instance_ID} with user {os.environ['USER']}")
            return

        node_name = vm.name
        host = self.get_host_ip(node_name)
        user_name = os.environ['USER']
        node_info = {
            'private_key' : self.my_ssh_private_key,
            'login' : f"{user_name}@{host}",
        }
        return node_info

    def _parse_resource_id(self, resource_id):
        """Parse Azure resource ID to extract resource group and name"""
        parts = resource_id.split('/')
        return parts[4], parts[-1]  # (resource_group, resource_name)

    def destroy_nodes(self, node_names=[], IDs=[], need_confirmation=True):
        '''
        Destroy all the nodes given the list of node names
        NOTE: should store the running cost and time before terminating the node(s)
        node_names = list of node names as strings
        '''
        if node_names is None:
            node_names = []
        if len(node_names) == 0:
            raise Exception("No node names are provided to destroy.")

        if isinstance(node_names, str): node_names = [node_names]
        user_name = os.environ['USER']

        subscription_id = self.account['subscription_id']
        compute_client = ComputeManagementClient(self.credentials, subscription_id)
        network_client = NetworkManagementClient(self.credentials, subscription_id)
        resource_group_name = self.account['resource_group']

        for vm_name in node_names:
            node = compute_client.virtual_machines.get(resource_group_name, vm_name)

            if node is None:
                raise ValueError(f"Node {vm_name} not found.")

            node_user_name = self.get_instance_user_name(node)
            if  node_user_name != user_name:
                print(f"Cannot destroy an instance {vm_name} created by other users")
                continue

            creation_time_str = node.time_created.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

            # Convert the creation time from string to datetime object
            # Azure returns 7-digit after '.' for seconds, so need to truncate the last digit 
            # to cast into %Y-%m-%dT%H:%M:%S.%f%z format
            idx = creation_time_str.find('+')
            creation_time_str = creation_time_str[:idx-1] + creation_time_str[idx:]
            creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
            # Calculate the running time
            running_time = datetime.now(timezone.utc) - creation_time
            # get the node type
            node_type = node.hardware_profile.vm_size
            instance_unit_cost = self.get_unit_price_instance(node)
            running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost

            if need_confirmation == True:
                response = input(f"Do you want to destroy {node.name} (running cost ${running_cost:0.5f})? NOTE: Data on the node will be removed. (y/n) ")
                if response != 'y':
                    continue
            # record the running time and cost
            running_time = datetime.now(timezone.utc) - creation_time
            running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
            usage, remaining_balance = self.get_cost_and_usage_from_db(user_name=user_name)
            
            # store the record into the database
            data = [node_user_name, node.id, node_type, 
                    creation_time, datetime.now(timezone.utc), running_cost, remaining_balance]
            
            if os.path.isfile(self.usage_history):
                df = pd.read_pickle(self.usage_history)
            else:
                df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End', 'Cost','Balance'])

            df = pd.concat([pd.DataFrame([data], columns=df.columns), df], ignore_index=True)
            df.to_pickle(self.usage_history)

            try:
                # order to destroy: VM, NIC, IP, VNET
                # Collect resource IDs before deletion
                nic_ids = [nic.id for nic in node.network_profile.network_interfaces] if node.network_profile else []
                os_disk_name = node.storage_profile.os_disk.name if node.storage_profile and node.storage_profile.os_disk else None
                data_disk_names = [disk.name for disk in node.storage_profile.data_disks] if node.storage_profile else []

                # Step 1: Delete the VM
                print(f"  Deleting VM: {vm_name}")
                compute_client.virtual_machines.begin_delete(resource_group_name, vm_name).result()
                print(f"  ✓ VM deleted")

                # Step 2: Delete NICs and collect associated resources
                public_ip_ids = []
                nsg_ids = []
                subnet_ids = []
                
                for nic_id in nic_ids:
                    rg, nic_name = self._parse_resource_id(nic_id)
                    
                    # Get NIC details to find public IP, NSG, and subnet
                    try:
                        nic = network_client.network_interfaces.get(rg, nic_name)
                        
                        # Collect public IP IDs
                        for ip_config in nic.ip_configurations:
                            if ip_config.public_ip_address:
                                public_ip_ids.append(ip_config.public_ip_address.id)
                            if ip_config.subnet:
                                subnet_ids.append(ip_config.subnet.id)
                        
                        # Collect NSG ID
                        if nic.network_security_group:
                            nsg_ids.append(nic.network_security_group.id)
                        
                        # Delete NIC
                        print(f"  Deleting NIC: {nic_name}")
                        network_client.network_interfaces.begin_delete(rg, nic_name).result()
                        print(f"  ✓ NIC deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting NIC {nic_name}: {e}")
                
                # Step 3: Delete Public IPs
                for public_ip_id in public_ip_ids:
                    rg, public_ip_name = self._parse_resource_id(public_ip_id)
                    try:
                        print(f"  Deleting Public IP: {public_ip_name}")
                        network_client.public_ip_addresses.begin_delete(rg, public_ip_name).result()
                        print(f"  ✓ Public IP deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting Public IP {public_ip_name}: {e}")
                
                # Step 4: Delete network security groups (NSGs)
                for nsg_id in set(nsg_ids):  # Use set to avoid duplicates
                    rg, nsg_name = self._parse_resource_id(nsg_id)
                    try:
                        print(f"  Deleting NSG: {nsg_name}")
                        network_client.network_security_groups.begin_delete(rg, nsg_name).result()
                        print(f"  ✓ NSG deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting NSG {nsg_name}: {e}")
                
                # Step 5: Delete Disks (OS disk and data disks)
                if os_disk_name:
                    try:
                        print(f"  Deleting OS Disk: {os_disk_name}")
                        compute_client.disks.begin_delete(resource_group_name, os_disk_name).result()
                        print(f"  ✓ OS Disk deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting OS Disk {os_disk_name}: {e}")
                
                for data_disk_name in data_disk_names:
                    try:
                        print(f"  Deleting Data Disk: {data_disk_name}")
                        compute_client.disks.begin_delete(resource_group_name, data_disk_name).result()
                        print(f"  ✓ Data Disk deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting Data Disk {data_disk_name}: {e}")
                
                # Step 6: Delete Subnets and VNets (optional - only if you want to clean these up)
                # Note: Be careful with this if other VMs share the same VNet/Subnet
                vnet_names = set()
                for subnet_id in subnet_ids:
                    parts = subnet_id.split('/')
                    vnet_name = parts[-3]  # VNet name is 3 positions before subnet name
                    vnet_names.add(vnet_name)
                
                # Uncomment the following if you want to delete VNets
                # WARNING: This will delete the entire VNet including all subnets
                for vnet_name in vnet_names:
                    try:
                        print(f"  Deleting VNet: {vnet_name}")
                        network_client.virtual_networks.begin_delete(resource_group_name, vnet_name).result()
                        print(f"  ✓ VNet deleted")
                    except Exception as e:
                        print(f"  ⚠ Error deleting VNet {vnet_name}: {e}")
                
                print(f"✓ Successfully deleted VM and associated resources")
            
            except Exception as e:
                print(f"✗ Error during deletion: {e}")
                raise

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
            df = pd.DataFrame([], columns=['User','InstanceID','InstanceType','Start','End','Cost','Balance'])
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

    def get_running_nodes(self, verbose=False):
        """Member function: list_nodes
        Get a list of all existed instances
        
        Return: a list of multiple turple. Each turple has four elements:
                (1) instance name (2) state (3) type (4) identifier
        """
        nodes = []
        current_time = datetime.now(timezone.utc)
        for node in self.driver.list_nodes():
            if node.state == "running":
                # Get the creation time of the instance
                creation_time_str = node.extra.get('properties')['timeCreated']  # Azure
                if creation_time_str:
                    # Convert the creation time from string to datetime object
                    # Azure returns 7-digit after '.' for seconds, so need to truncate the last digit 
                    # to cast into %Y-%m-%dT%H:%M:%S.%f%z format
                    idx = creation_time_str.find('+')
                    creation_time_str = creation_time_str[:idx-1] + creation_time_str[idx:]

                    creation_time = datetime.strptime(creation_time_str, '%Y-%m-%dT%H:%M:%S.%f%z')
                    
                    # Calculate the running time
                    running_time = current_time - creation_time

                    # get the node type
                    node_type = node.extra.get('properties')['hardwareProfile']['vmSize']

                    nodes.append([node.name, node.state, node_type, node.id, running_time])

        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Status', 'Type', 'Instance ID', 'Running Time']))
            print("")

    def get_unit_price_instance(self, node):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. t2.micro) from the cloud.yaml file
        """
        for node_type in self.vendor['node-types']:
            #vmtype = node.extra.get('properties')['hardwareProfile']['vmSize']
            vmtype = node.hardware_profile.vm_size
            if self.vendor['node-types'][node_type]['name'] == vmtype:
                instance_type = self.vendor['node-types'][node_type]['name']
                unit_price = self.vendor['node-types'][node_type]['price']
                return unit_price

    def get_unit_price(self, node_type: str):
        """
        Get the per-hour price of an instance depending on its instance_type (e.g. t1) from the cloud.yaml file
        """
        if node_type in self.vendor['node-types']:
            return self.vendor['node-types'][node_type]['price']
        return -1.0

    def get_host_ip(self, node_name):
        try:
            vm = None
            compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
            network_client = NetworkManagementClient(self.credentials, self.account['subscription_id'])
            for instance in compute_client.virtual_machines.list_all():
                if instance.name == node_name:
                    vm = instance
                    break

            if vm is None:
                print(f"No VM found for {node_name} with user {os.environ['USER']}")
                return None

            # Navigate: VM -> NIC -> Public IP
            nic_id = vm.network_profile.network_interfaces[0].id
            rg, nic_name = self._parse_resource_id(nic_id)

            nic = network_client.network_interfaces.get(rg, nic_name)
            
            public_ip_id = nic.ip_configurations[0].public_ip_address.id
            rg, public_ip_name = self._parse_resource_id(public_ip_id)

            public_ip = network_client.public_ip_addresses.get(rg, public_ip_name)

            return public_ip.ip_address

        except (AttributeError, IndexError, TypeError):
            return None  # VM doesn't have a public IP

    def get_instance_name(self, node):
        """Member function: get_instance_name
        Get the name information from the instance with given ID.
        Note: AWS doesn't use unique name for instances, instead, name is an
        attribute stored in the tags.
        
         - node: a node object
        """
        return node.name

    def get_instance_user_name(self, node):
        '''
        return the user name that created the node
        '''
        return node.tags.get('user') if node.tags else 'N/A'

    def get_instance_ID(self, instance_name: str):
        """Member function: get_instance_ID
        Get the (first) instance ID from the instance name
        """
        resource_group_name = self.account['resource_group']
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        instance_id = ''
        for node in compute_client.virtual_machines.list_all():
            if node.name == instance_name:
                instance_id = node.vm_id
                break

        return instance_id

    def get_instance_status(self, node):
        # instance_view contains runtime information including statuses
        resource_group_name = self.account['resource_group']
        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        instance_view = compute_client.virtual_machines.instance_view(resource_group_name, node.name)
        # Look for the power state in the statuses
        for status in instance_view.statuses:
            if status.code.startswith('PowerState/'):
                # Extract the state after 'PowerState/'
                power_state = status.code.split('/')[-1]
                return power_state.lower()
        return 'unknown'

    def get_running_cost(self, verbose=True, user_name=None):

        current_time = datetime.now(timezone.utc)
        if user_name is None:
            user_name = os.environ['USER']

        nodes = []
        total_cost = 0.0

        compute_client = ComputeManagementClient(self.credentials, self.account['subscription_id'])
        
        for node in compute_client.virtual_machines.list_all():
            if self.get_instance_name(node) in self.account['protected_nodes']:
                continue
            state = self.get_instance_status(node)

            if state.lower() == "running":
                node_user_name = self.get_instance_user_name(node)
                if user_name != node_user_name:
                    continue

                creation_time = node.time_created
                running_time = current_time - creation_time

                node_type = node.hardware_profile.vm_size
                instance_unit_cost = self.get_unit_price_instance(node)
                running_cost = running_time.total_seconds()/3600.0 * instance_unit_cost
                total_cost = total_cost + running_cost

                nodes.append([node.name, node_type, running_time, running_cost])

        if verbose == True:
            print(tabulate(nodes, headers=['Name', 'Type', 'Running Time', 'Running Cost']))
            print("")

        return total_cost

    def get_private_key(self):
        return self.my_ssh_private_key