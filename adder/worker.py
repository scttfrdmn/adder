#!/usr/bin/env python3
"""
adder worker entrypoint.
Reads environment variables, downloads task from S3, executes, uploads result.

This file is self-contained — no imports from the rest of the adder package.
It runs inside the ECS container where adder may not be installed.
"""
import os
import sys
import traceback

import boto3
import cloudpickle

SESSION_ID = os.environ["BURST_SESSION_ID"]
TASK_ID = os.environ["BURST_TASK_ID"]
BUCKET = os.environ["BURST_S3_BUCKET"]
REGION = os.environ["BURST_REGION"]


def main() -> None:
    s3 = boto3.client("s3", region_name=REGION)
    keys = {
        "task": f"sessions/{SESSION_ID}/tasks/{TASK_ID}.task",
        "result": f"sessions/{SESSION_ID}/tasks/{TASK_ID}.result",
        "status": f"sessions/{SESSION_ID}/tasks/{TASK_ID}.status",
        "error": f"sessions/{SESSION_ID}/tasks/{TASK_ID}.error",
    }

    # Signal running
    s3.put_object(Bucket=BUCKET, Key=keys["status"], Body=b"running")

    try:
        # Download and deserialize task
        task_data = s3.get_object(Bucket=BUCKET, Key=keys["task"])["Body"].read()
        payload = cloudpickle.loads(task_data)
        fn = payload["fn"]
        items = payload["items"]

        # Execute
        results = [fn(item) for item in items]

        # Serialize and upload result
        result_data = cloudpickle.dumps(results)
        s3.put_object(Bucket=BUCKET, Key=keys["result"], Body=result_data)
        s3.put_object(Bucket=BUCKET, Key=keys["status"], Body=b"done")

    except Exception:
        error_msg = traceback.format_exc()
        s3.put_object(Bucket=BUCKET, Key=keys["error"], Body=error_msg.encode())
        s3.put_object(Bucket=BUCKET, Key=keys["status"], Body=b"failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
