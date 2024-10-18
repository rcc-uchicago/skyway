# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
import yaml
from . import cfg
from . import utils

# return the list of accounts, that is the list of the .yaml files under $SKYWAYROOT/accounts
def accounts():
    acct_list = []
    for f in os.listdir(cfg['paths']['etc'] + '/accounts'):
        if f.endswith('.yaml'):
           acct_list.append(f.split('.')[0])
    return sorted(acct_list)

def load_cfg(account):
    if account not in accounts():
        raise Exception(f'Account {account} does not exist.')

    cfg_file = f"{cfg['paths']['etc']}/accounts/{account}.yaml"
    with open(cfg_file, "r") as f:
        acct_cfg = yaml.load(f, Loader=yaml.FullLoader)
    
    return acct_cfg

def list():
    print("\nAccounts:\n\n" + yaml.dump(accounts()))

def show(acct):
    print("\nAccount " + acct + ":\n\n" + yaml.dump(load_cfg(acct)))

# update pluggable authenication modules (PAM)
def update_pam():
    users = []
    for acct in accounts():
        users += load_cfg(acct)['users']

    nerror = 0
    for u in set(users):
        if utils.proc('getent passwd ' + u) == []:
            print('Unknown user: ' + u)
            nerror += 1    
    if nerror > 0:
        raise Exception('Unknown user(s) found!')

    passwd_ext = "\n".join(utils.proc('getent passwd '+ u)[0] for u in set(users))
    group_ext  = "\n".join(utils.proc('getent group  '+ u)[0] for u in set(users))
    shadow_ext = "\n".join(utils.proc('getent shadow '+ u)[0] for u in set(users))

    # path to the files and scripts to be copied to the VMs
    cloud_etc_path = os.environ['SKYWAYROOT'] + '/files/etc/'

    # read in the passwd file
    with open(cfg['paths']['var'] + 'passwd', 'r') as f:
        rows = f.read().strip()
    # write to cfg['paths']['files']/etc/passwd ($SKYWAYROOT/files/etc/group)
    with open(cloud_etc_path + 'passwd', "w") as f:
        f.write(rows + "\n" + passwd_ext + "\n")

    # read in the group file
    with open(cfg['paths']['var'] + 'group', 'r') as f:
        rows = f.read().strip()
    # write to  cfg['paths']['files']/etc/group ($SKYWAYROOT/files/etc/group)
    with open(cloud_etc_path + 'group', "w") as f:
        f.write(rows + "\n" + group_ext + "\n")

    # read in the shadow file
    with open(cfg['paths']['var'] + 'shadow', 'r') as f:
        rows = f.read().strip()
    # write to  cfg['paths']['files']/etc/shadow ($SKYWAYROOT/files/etc/shadow)
    with open(cloud_etc_path + 'shadow', "w") as f:
        f.write(rows + "\n" + shadow_ext + "\n")

