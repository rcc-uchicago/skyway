# Copyright (c) 2019-2024 The University of Chicago.
# Part of skyway, released under the BSD 3-Clause License.

# Maintainer: Yuxing Peng, Trung Nguyen

import os
import time
from tqdm import tqdm
import subprocess
from subprocess import PIPE, Popen
import yaml


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

# run a command over ssh
def run_ssh(host, user, key, remote_cmd, timeout=10):
    cmd = [
        "ssh",
        "-i", key,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        f"{user}@{host}",
        remote_cmd,
    ]

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

# wait for ssh connection to be ready
def wait_for_ssh(host, user, key, timeout=300):
    start = time.time()

    while time.time() - start < timeout:
        r = run_ssh(host, user, key, "echo READY")

        if r.returncode == 0 and r.stdout.strip() == "READY":
            return True

        time.sleep(5)

    return False    

# try ssh command until 
def ssh_until_success(host, user, key, remote_cmd,
                      retries=60,
                      interval=5):

    for _ in range(retries):
        r = run_ssh(host, user, key, remote_cmd)

        if r.returncode == 0:
            return r

        time.sleep(interval)

    raise RuntimeError(
        f"Failed to execute '{remote_cmd}' on {host}"
    )

def sendmail(email_address, to, subject, body):
    mail = "\r\n".join([
        'From: ' + email_address,
        'To: ' + to,
        'Subject: ' + subject,
        '',
        body
    ])
    proc("echo \"" + mail + "\" | sendmail -v '" + to + "'")

# wait for total time (seconds) for steps and with the description
def wait_progress(total_time, description):
    
    for _ in tqdm(range(total_time), desc=description, bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt}"):
        time.sleep(1)