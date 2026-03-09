"""Kubernetes configuration file generation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml


def write_kubeconfig(
    cluster_name: str,
    server: str,
    ca_data: str,
    token: str,
) -> Path:
    """Write a kubeconfig file for a cluster and return the path.

    The file is written to a temp directory. The caller is responsible
    for cleanup (or it's cleaned up when the process exits).
    """
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": cluster_name,
        "clusters": [
            {
                "name": cluster_name,
                "cluster": {
                    "server": server,
                    "certificate-authority-data": ca_data,
                },
            }
        ],
        "contexts": [
            {
                "name": cluster_name,
                "context": {
                    "cluster": cluster_name,
                    "user": cluster_name,
                },
            }
        ],
        "users": [
            {
                "name": cluster_name,
                "user": {
                    "token": token,
                },
            }
        ],
    }

    tmpdir = tempfile.mkdtemp(prefix="vip-kube-")
    os.chmod(tmpdir, 0o700)
    path = Path(tmpdir) / "config"
    path.write_text(yaml.dump(config, default_flow_style=False))
    os.chmod(path, 0o600)
    return path
