# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
from datetime import datetime, timezone
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

    def get_warning_threshold(self):
        """Return the budget warning threshold as a fraction (0.0–1.0).

        Reads 'warning_threshold' (a percentage integer, e.g. 90) from the
        vendor section of cloud.yaml.  Falls back to 0.90 if the key is
        absent or empty.
        """
        raw = self.vendor.get('warning_threshold', None)
        if raw is None or raw == '':
            return 0.90
        return min(float(raw), 0.99)

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

    def get_unit_price_by_name(self, instance_type_name):
        """
        Look up the per-hour price from the vendor's node-types by the instance
        type name as recorded in the usage history (e.g. 'a3-megagpu-8g',
        'c5.4xlarge', 'v6e-8'). Unlike get_unit_price(), which takes a Skyway
        node-type key such as 'a3mg8', this resolves what the PKL actually
        stores. Returns -1.0 if the name is unknown.
        """
        if not instance_type_name:
            return -1.0
        name = str(instance_type_name)
        for cfg in self.vendor.get('node-types', {}).values():
            if cfg.get('name') == name or cfg.get('tpu-type') == name:
                return cfg['price']
        return -1.0

    def _close_usage_row(self, df, idx, end_time, unit_price):
        """
        Close out an existing usage row: set End and recompute Cost from the
        row's recorded Start, so the ledger holds actual runtime instead of the
        projection written at launch. Balance is refreshed to stay consistent
        with the corrected Cost. Cost is left untouched if Start cannot be
        parsed or would imply negative runtime.
        """
        df.loc[idx, 'End'] = end_time.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

        instance_id = df.loc[idx, 'InstanceID']
        # Stored timestamps vary (datetime objects on some backends, strings
        # with or without a colon in the offset on others), so let pandas
        # infer instead of pinning a format.
        start_time = pd.to_datetime(df.loc[idx, 'Start'], utc=True, errors='coerce')
        if pd.isna(start_time):
            print(f"WARNING: cannot parse Start for {instance_id}; keeping projected cost.")
            return

        elapsed_hours = (end_time - start_time.to_pydatetime()).total_seconds() / 3600.0
        if elapsed_hours < 0:
            print(f"WARNING: Start of {instance_id} is after End; keeping projected cost.")
            return

        df.loc[idx, 'Cost'] = elapsed_hours * unit_price

        row_user = df.loc[idx, 'User']
        if row_user in self.users:
            accumulated = df.loc[df['User'] == row_user].astype({'Cost': float})['Cost'].sum()
            df.loc[idx, 'Balance'] = float(self.users[row_user]['budget']) - accumulated

    def _find_session_row(self, df, instance_id, session_start,
                          tolerance_minutes=5):
        """
        Return the index of the usage row recording the session that began at
        session_start, or None if that session was never recorded.

        Rows are prepended newest-first, so callers used to just take
        index[0]. That is only right when every session got a row: create_nodes
        and restart_nodes write one, but an instance started outside Skyway
        does not, and then index[0] is an older, already-closed session whose
        End and Cost are correct. Closing it again rewrites a good historical
        record and bills the user for the whole gap in between.

        Matching on Start rather than on "is End still in the future" keeps the
        answer right for a session that outlived its projected walltime.
        """
        if session_start is None:
            return None
        rows = df[df['InstanceID'] == instance_id]
        if rows.empty:
            return None
        # Stored timestamps are heterogeneous (offset with/without a colon,
        # 3- or 6-digit fractional seconds), so let pandas infer per value.
        starts = pd.to_datetime(rows['Start'], format='mixed', utc=True,
                                errors='coerce')
        cutoff = pd.Timestamp(session_start)
        cutoff = cutoff.tz_localize('UTC') if cutoff.tz is None \
            else cutoff.tz_convert('UTC')
        cutoff -= pd.Timedelta(minutes=tolerance_minutes)
        matches = rows.index[starts.notna() & (starts >= cutoff)]
        return matches[0] if len(matches) else None

    def _abort_restart_session(self, df, unit_price, label, reason, stop_fn):
        """
        Roll back a restart whose walltime shutdown could not be armed.

        create_nodes() destroys an instance when it cannot schedule
        `shutdown -P`, on the reasoning that an instance with no timer runs
        until somebody notices. A restarted instance is in the same position,
        but it holds user data, so stop it instead of destroying it.

        restart_nodes() writes the session row before the SSH step, so close
        that row at the real end time; leaving it would bill a full-walltime
        projection for a session that lasted minutes, and leave the row looking
        like a legitimate open session.
        """
        print(f"Failed to schedule the walltime shutdown on {label}: {reason}")
        print("Stopping the instance to avoid unbounded charges; data is preserved.")
        try:
            stop_fn()
        except Exception as e:
            print(f"WARNING: could not stop {label}: {e}\n"
                  f"         Run 'skyway_stop' on it now — it has no shutdown timer.")
            return
        if df is not None and len(df) > 0:
            self._close_usage_row(df, df.index[0],
                                  datetime.now(timezone.utc), unit_price)
            df.to_pickle(self.usage_history)

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
