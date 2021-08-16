#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    author="DCSO GmbH",
    author_email="sascha.steinbiss@dcso.de",
    classifiers=[
        # https://pypi.org/classifiers/
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: BSD License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
    ],
    description="Application to extend FEVER BLF detection via Threat Bus IoCs",
    entry_points={"console_scripts": ["fever-threatbus=fever_threatbus.fever:main"]},
    include_package_data=True,
    install_requires=[
        "black >= 19.10b",
        "dynaconf >= 3.1.4",
        "pyzmq >= 19",
        "stix2 >= 2.1, < 3.0",
        "threatbus >= 2021.5.27",
    ],
    keywords=[
        "open source",
        "threatbus",
        "Threat Bus",
        "threat intelligence",
        "TI",
        "TI dissemination",
    ],
    license="BSD 3-clause",
    long_description=long_description,
    long_description_content_type="text/markdown",
    name="fever-threatbus",
    packages=["fever_threatbus"],
    python_requires=">=3.7",
    setup_requires=["setuptools", "wheel"],
    url="https://github.com/satta/fever-threatbus",
    version="0.1",
)
