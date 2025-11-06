#!/usr/bin/env python3
"""Setup script."""
import os

from setuptools import setup


def open_file(fname):
    """Open and return a file-like object for the relative filename."""
    return open(os.path.join(os.path.dirname(__file__), fname))


setup(
    name="azul-restapi-server",
    description="Public Azul RESTful API server.",
    author="Azul",
    author_email="azul@asd.gov.au",
    url="https://www.asd.gov.au/",
    packages=["azul_restapi_server"],
    include_package_data=True,
    python_requires=">=3.12",
    classifiers=[],
    entry_points={
        "console_scripts": [
            "azul-restapi-server = azul_restapi_server.cli:run",
        ],
        "azul_restapi.plugin": [
            "users = azul_restapi_server.api.v1.users:router",
        ],
    },
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    install_requires=[r.strip() for r in open_file("requirements.txt") if not r.startswith("#")],
)
