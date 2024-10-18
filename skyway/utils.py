# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
import yaml
from subprocess import PIPE, Popen

def load_config(cfg_name, cfg_path):
    cfg_file = cfg_path + cfg_name + '.yaml'
    if not os.path.isfile(cfg_file):
        raise Exception(f'Configuration file {cfg_file} cannot be found.')

    with open(cfg_file, 'r') as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)

# execute a command, return output as a list of rows, each row is converted to a list of words
def proc(command, strict=True):
    if isinstance(command, list):
        command = ' '.join(command)
    p = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = p.communicate()
    out = stdout.decode('ascii').strip()
    err = stderr.decode('utf-8').strip()
    
    if strict and err !="":
        raise Exception('Shell error: ' + err + '\nCommand: ' + command)
    
    if out == "": return []
    else: return out.split('\n')

# read in a script, combine lines into a string, excluding empty lines and comments starting with #
def script2cmd(script_name: str):
    cmd = ""
    with open(script_name, 'r') as f:        
        lines = f.readlines()

        for line in lines:
            l = line.strip()
            if len(l) == 0:
                continue
            if l[0] == '#':
                continue
            cmd += l + "; "
    return cmd

# get the username of a uid
def get_username(uid):
    uid = proc("getent passwd " + uid + " | awk -F: '{print $1}'")
    return None if uid==[] else uid[0]

def sendmail(email_address, to, subject, body):
    mail = "\r\n".join([
        'From: ' + email_address,
        'To: ' + to,
        'Subject: ' + subject,
        '',
        body
    ])
    proc("echo \"" + mail + "\" | sendmail -v '" + to + "'")