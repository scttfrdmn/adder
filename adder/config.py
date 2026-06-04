"""Config file read/write for ~/.burst/config.json."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

_DEFAULT_CONFIG_PATH = Path.home() / ".burst" / "config.json"


def _config_path() -> Path:
    env = os.environ.get("BURST_CONFIG_PATH")
    if env:
        return Path(env)
    return _DEFAULT_CONFIG_PATH


@dataclass
class Config:
    region: str = "us-east-1"
    s3_bucket: str = ""
    ecs_cluster: str = "burst-cluster"
    ecr_base_uri: str = ""
    execution_role_arn: str = ""
    task_role_arn: str = ""
    default_cpu: int = 2
    default_memory_gb: int = 4
    default_workers: int = 10
    max_cost_per_job: float = 0.0
    cost_alert_threshold: float = 0.0
    backend: str = "fargate"
    spot: bool = False
    fargate_quota_vcpu: float = 0.0

    def validate(self) -> None:
        """Raise BurstSetupError if required fields are missing."""
        from .errors import BurstSetupError

        required = [
            "s3_bucket",
            "ecs_cluster",
            "ecr_base_uri",
            "execution_role_arn",
            "task_role_arn",
        ]
        missing = [f for f in required if not getattr(self, f)]
        if missing:
            raise BurstSetupError(
                step="config",
                cause=f"Missing required config fields: {', '.join(missing)}",
                remediation="Run `adder setup` or `burst-core setup` to provision AWS resources.",
            )


def load() -> Config:
    """Load config from ~/.burst/config.json (or BURST_CONFIG_PATH)."""
    path = _config_path()
    if not path.exists():
        return Config()
    with open(path) as f:
        data = json.load(f)
    # Only set fields that exist in Config; ignore unknown keys
    valid_fields = {f.name for f in Config.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return Config(**filtered)


def save(cfg: Config) -> None:
    """Write config to ~/.burst/config.json with 0600 permissions."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
