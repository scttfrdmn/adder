"""Additional unit tests for adder/env.py covering ensure_image paths."""

from unittest.mock import MagicMock, patch


from adder.config import Config
from adder.env import _python_version, _render_dockerfile, ensure_image


def test_python_version_format():
    v = _python_version()
    parts = v.split(".")
    assert len(parts) == 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()


def test_render_dockerfile_contains_python_version():
    content = _render_dockerfile("boto3==1.34.0")
    v = _python_version()
    assert v in content
    assert "FROM python:" in content
    assert "requirements.txt" in content
    assert "worker_entrypoint.py" in content


def test_ensure_image_uses_existing_ecr_image():
    """ensure_image returns URI from ECR if image exists."""
    cfg = Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecr_base_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123:role/exec",
        task_role_arn="arn:aws:iam::123:role/task",
    )

    mock_ecr = MagicMock()
    mock_ecr.describe_images.return_value = {
        "imageDetails": [{"imageDigest": "sha256:abc", "imageTags": ["deadbeef"]}]
    }

    with (
        patch("boto3.client", return_value=mock_ecr),
        patch("adder.env.capture_environment", return_value=("boto3==1.34", "deadbeef")),
    ):
        uri = ensure_image(cfg)

    assert "deadbeef" in uri
    assert "burst-workers-python" in uri
    # Should NOT call build_image since image exists
    mock_ecr.describe_images.assert_called_once()


def test_ensure_image_builds_when_not_found():
    """ensure_image calls build_image when ECR image not found."""
    cfg = Config(
        region="us-east-1",
        s3_bucket="burst-us-east-1",
        ecr_base_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com",
        execution_role_arn="arn:aws:iam::123:role/exec",
        task_role_arn="arn:aws:iam::123:role/task",
    )

    mock_ecr = MagicMock()
    mock_ecr.describe_images.side_effect = Exception("ImageNotFoundException")
    # Make exceptions accessible
    mock_ecr.exceptions.ImageNotFoundException = Exception

    expected_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/burst-workers-python:newhash"

    with (
        patch("boto3.client", return_value=mock_ecr),
        patch("adder.env.capture_environment", return_value=("boto3==1.34", "newHash")),
        patch("adder.env.build_image", return_value=expected_uri) as mock_build,
    ):
        uri = ensure_image(cfg)

    assert uri == expected_uri
    mock_build.assert_called_once()
