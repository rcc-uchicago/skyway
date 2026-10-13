from setuptools import setup
from glob import glob
import os

setup(name='skyway',
    version='2.0.0',
    description='Cloud computing',
    url='https://github.com/ndtrung81/skyway',
    author='Trung Nguyen',
    author_email='ndactrung@gmail.com',
    license='GPL',
    packages=['skyway'],
    entry_points = {
        "console_scripts": [
                           ]
    },
    install_requires=[
        'apache-libcloud>=3.8.0',
        'boto3>=1.34.156',
        'apache-libcloud>=3.8.0',
        'azure-common>=1.1.28',
        'azure-core>=1.30.2',
        'azure-mgmt-compute>=32.0.0',
        'azure-mgmt-core>=1.4.0',
        'azure-mgmt-network>=26.0.0',
        'azure-mgmt-resource>=23.1.1',
        'azure-mgmt-storage>=21.2.1',
        'google-api-core>=2.19.0',
        'google-auth>=2.30.0',
        'google-cloud-compute>=1.19.0',
        'googleapis-common-protos>=1.63.1',
        'Jinja2>=3.1.4',
        'oci>=2.128.0',
        'pandas>=2.0.3',
        'streamlit>=1.35.0',
        'streamlit-autorefresh>=1.0.1',
        'tabulate>=0.9.0',
    ]
)
