"""Environment snapshot and Docker image management."""

from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

EXCLUDE_PACKAGES = frozenset(
    {
        "pip",
        "setuptools",
        "wheel",
        "pkg-resources",
        "pkg_resources",
        "distribute",
        "packaging",
        "hatchling",
        "hatch",
        "hatch-vcs",
    }
)


def capture_environment() -> tuple[str, str]:
    """Capture the current Python environment.

    Returns:
        (requirements_txt, env_hash) where requirements_txt is a sorted
        'package==version' newline-joined string and env_hash is its SHA256.
    """
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "")
        version = dist.metadata.get("Version", "")
        if name and version and name.lower() not in EXCLUDE_PACKAGES:
            packages.append(f"{name}=={version}")
    packages.sort()
    requirements = "\n".join(packages)
    env_hash = hashlib.sha256(requirements.encode()).hexdigest()
    return requirements, env_hash


def _python_version() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}"


def _render_dockerfile(requirements: str) -> str:
    python_version = _python_version()
    template = Path(__file__).parent.parent / "Dockerfile.worker"
    if template.exists():
        content = template.read_text()
        return content.replace("{python_version}", python_version)
    # Fallback inline template
    return (
        f"FROM python:{python_version}-slim\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY worker_entrypoint.py .\n"
        "ENV PYTHONUNBUFFERED=1\n"
        'CMD ["python", "worker_entrypoint.py"]\n'
    )


def build_image(env_hash: str, dockerfile_path: str) -> str:
    """Shell out to burst-core to build and push the Docker image.

    Returns the ECR image URI.
    """
    result = subprocess.run(
        [
            "burst-core",
            "image",
            "build",
            "--lang",
            "python",
            "--env-hash",
            env_hash,
            "--dockerfile",
            dockerfile_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def ensure_image(cfg: "Config") -> str:
    """Ensure a Docker image exists in ECR for the current environment.

    Checks ECR for an existing image tagged with the env hash.
    Builds and pushes via burst-core if not present.

    Returns the ECR image URI.
    """
    import boto3

    requirements, env_hash = capture_environment()

    # Check ECR for existing image
    ecr = boto3.client("ecr", region_name=cfg.region)
    repo_name = "burst-workers-python"
    try:
        resp = ecr.describe_images(
            repositoryName=repo_name,
            imageIds=[{"imageTag": env_hash}],
        )
        if resp.get("imageDetails"):
            cfg.ecr_base_uri.split(".")[0]
            return f"{cfg.ecr_base_uri}/{repo_name}:{env_hash}"
    except ecr.exceptions.ImageNotFoundException:
        pass
    except Exception:
        pass

    # Build and push via burst-core
    with tempfile.TemporaryDirectory() as tmpdir:
        req_path = Path(tmpdir) / "requirements.txt"
        req_path.write_text(requirements)

        dockerfile_content = _render_dockerfile(requirements)
        dockerfile_path = Path(tmpdir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        # Also write the worker entrypoint
        worker_src = Path(__file__).parent / "worker.py"
        worker_dst = Path(tmpdir) / "worker_entrypoint.py"
        worker_dst.write_bytes(worker_src.read_bytes())

        return build_image(env_hash, str(dockerfile_path))
