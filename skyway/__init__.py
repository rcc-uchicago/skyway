# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
import yaml
from . import utils

# SKYWAYROOT is the path to the on-premises folders (not the skyway source code folder)
#   bin: scripts to be executed on mgt and login nodes
#   etc: configuration files (accounts/, services/, cloud.yaml)
#   var: system data
#   run: runtime information
#   log: log files

if 'SKYWAYROOT' not in os.environ:
    raise Exception('SKYWAYROOT is not yet set in the environment. Setting it to the path where the Python module skyway and the executables skyway_* reside.')

cfg_path = os.environ['SKYWAYROOT'] + '/etc/'
debug = 'SKYWAYDEBUG' in os.environ

def load_config(cfg_name, path=None):
    if path is None:
        path = cfg_path
    cfg_file = path + cfg_name + '.yaml'

    if not os.path.isfile(cfg_file):
        raise Exception(f'Configuration file {cfg_name} cannot be found.')

    with open(cfg_file, 'r') as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)
