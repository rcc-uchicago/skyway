# Skyway Documentation

Skyway is an integrated platform developed at the RCC to allow users to burst computing workloads from the on-premise RCC cluster, Midway, to run on remote commercial cloud platforms such as Amazon AWS, Google GCP and Microsoft Azure. Skyway enables users to run computing tasks in the cloud from Midway in a seamless manner without needing to learn how to provision cloud resources. Since the user does not need to setup or manage cloud resources themselves, the result is improved productivity with a minimum learning curve.

The official [Skyway](https://github.com/rcc-uchicago/user-guide/issues/new) homepage gives useful information for getting started.

## Overview

From the user persepectives, Skyway functions in a similar way to a HPC cluster where they can transfer data in and out, compile software or load existing modules, submit jobs either to on-premises compute nodes, or to virtual machines (aka instances) from a cloud service provider. Skyway uses SLURM as a resource manager in the cloud. Resources in the cloud have the same configuration, software modules and file storage systems as Midway. The [User Guide](user_overview.md) provides more information.

From the admin perspectives, Skyway relies on SLURM to burst jobs to the corresponding cloud accounts and partitions given the requested instance features. Although Skyway manages user accounts and billing and monitors jobs, it relies on how the University IT Services support the secured connections between the cloud accounts and the Skyway login node.

After downloading and installing the Skyway package into root-access places, admins add configuration files, cloud services and accounts, and launch the daemon for individual accounts. The daemons run in the background periodically checks the SLURM queue for jobs submitted to the cloud, and instantiate (or activate) the virtual machines on the cloud given the user credential and the account specified in the job script. More information is given in the [Developer Guide](developer_overview.md).

The [Developer Guide](developer_overview.md) also serves to provide information on how to add more functionalities to Skyway.

|  <div style="width:100px">Documentation</div> | Description |  Audience |
| ----------- | ----------- | ----------- |
| **[User Guide](user_overview.md)** | Installing pre-requisite software and acquiring source code | End users |
| **[Developer Guide](developer_overview.md)** | Adding cloud services and starting the daemons | Admins and developers |


## Where to start?

* Researchers interested in using the RCC systems can [request an account](https://rcc.uchicago.edu/accounts-allocations/request-account){:target="_blank"}.  
* For Service Units (computing time) and storage resources, [request an allocation](https://rcc.uchicago.edu/accounts-allocations/request-allocation){:target="_blank"}.  
* If you would like to chat with an RCC specialist about what services are best for you, please email [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu)

<!---
## How to use this guide 
Here are a few things to keep in mind as you navigate the user guide:  

* The guide is organized by [system](#overview-of-rccs-hpc-systems); be sure you're in the right section!  
* You will see <img src="img/copy-icon.png" width="22" height="22" /> in the top-right of grey code blocks, which will allow you to **copy** the contents of the block to your clipboard.  

* Try the **search bar** in the top right to quickly find what you're looking for (e.g., search: "GPU").  

* If you come across any content that you think should be **changed or improved** (typo, out-of-date, etc.), please feel free to do any of the following to help make the guide better:
    1. Create an [Issue](https://github.com/rcc-uchicago/user-guide/issues/new){:target="_blank"} on GitHub  
    2. Edit the guide's [markdown source](https://github.com/rcc-uchicago/user-guide){:target="_blank"} directly and submit a [pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests){:target="_blank"}  
    3. Email [help@rcc.uchicago.edu](mailto:help@rcc.uchicago.edu)
-->
