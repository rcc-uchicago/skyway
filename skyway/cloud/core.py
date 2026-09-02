# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
from datetime import datetime
import pandas as pd
import yaml
from tabulate import tabulate
from .. import utils

def parse_walltime(walltime_str):
    """Parse HH:MM:SS or D-HH:MM:SS and return (total_hours, total_minutes_int)."""
    days = 0
    if '-' in walltime_str:
        day_part, time_part = walltime_str.split('-', 1)
        days = int(day_part)
    else:
        time_part = walltime_str
    h, m, s = (int(x) for x in time_part.split(':'))
    total_minutes = days * 1440 + h * 60 + m + s // 60
    return total_minutes / 60, total_minutes


# Provide the API for child classes to override

class Cloud():
    
    def __init__(self, vendor_cfg, kwargs):
        self.vendor = vendor_cfg
        self.onpremises = False

        for k, v in kwargs.items():
            setattr(self, k.replace('-','_'), v)
            

    # account info

    def check_valid_user(self, user_name, verbose=False):
        '''
        check if a user name is in the cloud account
        '''
        pass

    def get_node_types(self):
        '''
        get the node types available to the account
        '''
        pass

    def get_group_members(self):
        '''
        get all the user names in this account (listed in the .yaml file)
        '''
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
        pass

    def get_budget_api(self):
        '''
        get the budget from the cloud account API
        '''
        pass

    def get_cost_and_usage_from_db(self, user_name):
        '''
        compute the accumulating cost from the pkl database
        and the remaining balance
        '''
        accumulating_cost = 0
        remaining_balance = 0
        return accumulating_cost, remaining_balance

    def get_usage_history_from_db(self, user_name):
        '''
        return the list of jobs/instances
        '''
        pass

    # instance operations

    def list_nodes(self, show_protected_nodes=False, verbose=False):
        '''
        list all the running/stopped nodes (aka instances)
        '''
        pass

    def create_nodes(self, node_type: str, node_names = [], need_confirmation = True, walltime = None, image_id = ""):
        '''
        create several nodes (aka instances) given a list of node names
        '''
        pass

    def connect_node(self, node_name, separate_terminal=True):
        '''
        connect to a node (aka instance) via SSH
        '''
        pass

    def destroy_nodes(self, node_names, ids, need_confirmation=True):
        '''
        destroy several nodes (aka instances) given a list of node names
        '''
        pass

    def stop_nodes(self, node_names, ids, need_confirmation=True):
        '''
        stop several nodes (aka instances) given a list of node names
        '''
        pass

    def restart_nodes(self, node_names, need_confirmation=True):
        '''
        restart several nodes (aka instances) given a list of node names
        '''
        pass

    def get_running_nodes(self, verbose=False):
        '''
        list all the running nodes (aka instances)
        '''
        pass

    def execute(self, node_name: str, **kwargs):
        '''
        execute commands on a node
        '''
        pass

    def execute_script(self, node_id: str, script_name: str):
        '''
        execute all the lines in a script on a compute node
        '''
        pass

    def get_host_ip(self, node_name):
        '''
        get the public IP of a node name
        '''
        pass

    def get_node_connection_info(self, node_name):
        '''
        get the username and host ip for ssh connection
        '''
        pass

    def get_unit_price(self, node):
        '''
        get the unit price of a node object (inferring from its name and from the cloud.yaml file)
        '''
        pass

    def get_instance_name(self, node):
        '''
        get the name of a node object (from the vendor API)
        '''
        pass

    def get_instance_user_name(self, node):
        '''
        return the user name that created the node
        '''
        
    def get_instances(self, filters = []):
        '''
        get the reference to the node (aka instance) object (from the vendor API)
        '''
        pass

    def get_running_cost(self, verbose=True):
        '''
        get the running cost of all the nodes (aka instances) (from the vendor API for running time and the unit cost)
        '''
        pass

    def update_budget(self, user_name, new_budget, note=""):
        '''
        update a user's budget in the account YAML and append a record to the
        budget adjustment log (budget-log-<account>.pkl)
        '''
        account_path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        cfg_file = f"{account_path}{self.account_name}.yaml"
        budget_log = f"{account_path}budget-log-{self.account_name}.pkl"

        if user_name not in self.users:
            raise Exception(f"{user_name} is not listed in the user group of this account.")

        old_budget = float(self.users[user_name]['budget'])

        # update the YAML file
        with open(cfg_file, 'r') as f:
            cfg = yaml.load(f, Loader=yaml.FullLoader)
        cfg['users'][user_name]['budget'] = new_budget
        with open(cfg_file, 'w') as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        # update in-memory
        self.users[user_name]['budget'] = new_budget

        # append to adjustment log
        adjusted_by = os.environ.get('USER', 'unknown')
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        cols = ['Timestamp', 'Account', 'User', 'OldBudget', 'NewBudget', 'AdjustedBy', 'Note']
        new_row = pd.DataFrame([[timestamp, self.account_name, user_name,
                                  old_budget, float(new_budget), adjusted_by, note]],
                               columns=cols)
        if os.path.isfile(budget_log):
            df = pd.read_pickle(budget_log)
            df = pd.concat([df, new_row], ignore_index=True)
        else:
            df = new_row
        df.to_pickle(budget_log)

        return old_budget, float(new_budget)

    def get_budget_history(self, user_name=None):
        '''
        return the budget adjustment log for the account, optionally filtered by user
        '''
        account_path = os.environ['SKYWAYROOT'] + '/etc/accounts/'
        budget_log = f"{account_path}budget-log-{self.account_name}.pkl"
        cols = ['Timestamp', 'Account', 'User', 'OldBudget', 'NewBudget', 'AdjustedBy', 'Note']

        if not os.path.isfile(budget_log):
            return pd.DataFrame(columns=cols)

        df = pd.read_pickle(budget_log)
        if user_name is not None:
            df = df.loc[df['User'] == user_name]
        return df.reset_index(drop=True)

    def get_private_key(self):
        '''
        get the private key used for SSH public key authentication
        '''
        return ""

    @staticmethod
    def create(vendor: str, kwargs):
        print(f"Vendor: {vendor}")
        vendor = vendor.lower()
        # load cloud.yaml under $SKYWAYROOT/etc/
        vendor_cfg = utils.load_config('cloud')
        print(f"Vendor cfg: {vendor_cfg}")
        if vendor not in vendor_cfg:
            raise Exception(f'Cloud vendor {vendor} is undefined.')

        from importlib import import_module
        module = import_module('skyway.cloud.' + vendor)
        cloud_class = getattr(module, vendor.upper())
        return cloud_class(vendor_cfg[vendor], kwargs)
