# adder

Cloud bursting for Python — AWS parallel map.

`adder` is a drop-in replacement for `ProcessPoolExecutor` that runs your workloads
on AWS ECS Fargate workers. It also provides a joblib backend, making scikit-learn
and other parallel libraries transparently burst to the cloud.

## Installation

```bash
pip install adder
```

Also requires [`burst-core`](https://burst-core.dev/install) in your PATH:

```bash
curl -fsSL https://burst-core.dev/install | sh
```

## Quick start

### One-line cloud map

```python
import adder

# Runs fn on each item using 50 cloud workers
results = adder.map(items, fn, workers=50)
```

### Drop-in for ProcessPoolExecutor

```python
from adder import CloudExecutor

with CloudExecutor(workers=50) as executor:
    results = list(executor.map(fn, items))
```

### scikit-learn / joblib

```python
from joblib import parallel_backend
import adder  # registers 'adder' backend

with parallel_backend('adder', workers=50, cpu=4):
    grid_search = GridSearchCV(model, param_grid, n_jobs=-1)
    grid_search.fit(X, y)
```

## Setup

```bash
adder setup
```

This provisions the required AWS resources (S3 bucket, ECS cluster, IAM roles, ECR repository)
in your account. Takes about 30 seconds. Idempotent — safe to run multiple times.

## API

### `adder.map()`

```python
adder.map(
    items,          # Iterable of inputs
    fn,             # Function to apply to each item
    workers=10,     # Number of parallel ECS workers
    cpu=2,          # vCPUs per worker
    memory="4GB",   # Memory per worker
    backend="fargate",  # "fargate" or "ec2"
    spot=False,     # Use Fargate Spot (~70% cheaper, may be interrupted)
    max_cost=None,  # Cancel if estimated cost exceeds this USD amount
    cost_alert=None, # Warn if estimated cost exceeds this USD amount
    timeout=None,   # Maximum seconds to wait
    region=None,    # AWS region (default: ~/.burst/config.json)
)
```

### Detached sessions

For long-running jobs where you want the process to be able to exit:

```python
import adder

# Start a detached session
session = adder.session(workers=100, detached=True)
session_id = session.submit(items, fn)
# Process can exit — workers continue running

# Later (or in a different process):
session = adder.attach(session_id)
status = session.status()
print(f"{status.tasks_complete}/{status.tasks_total} complete")
results = session.collect()  # Blocks until done
session.cleanup()
```

### Pool

Reuse the same worker cluster across multiple map operations:

```python
from adder import Pool

pool = Pool(workers=20, cpu=4)
results1 = pool.map(items1, fn1)
results2 = pool.map(items2, fn2)
pool.shutdown()
```

## Error handling

```python
from adder import BurstPartialError, BurstCostLimitError

try:
    results = adder.map(items, fn, workers=50, max_cost=5.00)
except BurstPartialError as e:
    print(f"{e.failed_count} tasks failed")
    # e.results contains None where tasks failed, results where they succeeded
    # e.errors contains the error messages
except BurstCostLimitError as e:
    print(f"Cost limit ${e.limit:.2f} exceeded")
```

## Cost

adder prints estimated and actual cost for every run:

```
🚀 Starting burst cluster with 50 workers
💰 Estimated cost: ~$2.80/hour
📊 Processing 1000 items with 50 workers
📦 Created 50 chunks (avg 20 items per chunk)
🚀 Submitting tasks...
✓ Submitted 50 tasks
⏳ Progress: 35/50 tasks (12.3s elapsed)

✓ Completed in 18.4s
💰 Actual cost: $0.14
```

## Requirements

- Python 3.10+
- AWS credentials configured (`aws configure`)
- `burst-core` in PATH
- Docker (for the first run — builds your environment image)

## License

Apache-2.0
