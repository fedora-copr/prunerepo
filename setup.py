#!/usr/bin/python3
# This file is used only for EPEL 10 (and older) compatibility.
# Fedora builds use pyproject.toml with %pyproject_* macros.

import os

from setuptools import setup, find_packages

setup(
    name=os.getenv('name'),
    version=os.getenv('version'),
    description=os.getenv('summary'),
    author='clime',
    author_email='clime@redhat.com',
    download_url='https://pagure.io/copr/copr.git',
    license='GPLv2+',
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Build Tools",
    ],
    entry_points={
        'console_scripts': [
            'prunerepo=prunerepo.main:main'],
    },
    include_package_data=True,
    packages=find_packages(),
)
