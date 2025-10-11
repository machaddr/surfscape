#!/usr/bin/env python3

from setuptools import setup, find_packages
import os

# Read the README file
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Read requirements
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="surfscape",
    version="1.1",
    author="André Machado",
    author_email="machaddr@falanet.org",
    description="Your Own Way to Navigate the Web with Freedom",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/machaddr/surfscape",
    packages=find_packages(),
    py_modules=["surfscape"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: X11 Applications :: Qt",
        "Topic :: Internet",
        "Topic :: Multimedia :: Graphics :: Viewers",
    ],
    python_requires=">=3.8",
    install_requires=read_requirements(),
    entry_points={
        "console_scripts": [
            "surfscape=surfscape:main",
        ],
    },
    data_files=[
        ("share/applications", ["debian/surfscape.desktop"]),
        ("share/icons/hicolor/256x256/apps", ["icon/icon.png"]),
        ("share/doc/surfscape", ["README.md", "LICENSE"]),
    ],
    include_package_data=True,
    zip_safe=False,
)
