# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
import yaml
from . import utils

# SKYWAYROOT is the path to the on-premises folders (not the skyway source code folder)
#   bin: scripts to be executed on mgt and login nodes
#   etc: configuration files (skyway.yaml and root.yaml, accounts/, services/ and cloud nodes)
#   var: system data
#   run: rutime information
#   log: log files
#
#   post: scripts to be copied to, and executed on, the cloud VMs
#   files: files to be copied to the cloud VMs

if 'SKYWAYROOT' not in os.environ:
    raise Exception('SKYWAYROOT is not set in envrionment.')

cfg_path = os.environ['SKYWAYROOT'] + '/etc/'
debug = 'SKYWAYDEBUG' in os.environ

def load_config(cfg_name):
    cfg_file = cfg_path + cfg_name + '.yaml'

    if not os.path.isfile(cfg_file):
        raise Exception(f'Configuration file {cfg_name} cannot be found.')
    
    with open(cfg_file, 'r') as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)

# load the configuration from $SKYWAYROOT/etc/skyway.yaml into cfg, a dictionary
cfg = load_config('skyway')

# cfg lists all the relevant paths, replace <ROOT> with $SKYWAYROOT
for k in cfg['paths']:
    cfg['paths'][k] = cfg['paths'][k].replace('<ROOT>', os.environ['SKYWAYROOT'])


