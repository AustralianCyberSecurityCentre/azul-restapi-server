"""This script is run in the docker file to install plugins."""

import importlib.metadata

eps = importlib.metadata.entry_points().select(group="azul_restapi.plugin")
for ep in eps:
    print(ep.dist.name)
