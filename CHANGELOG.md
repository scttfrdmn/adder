# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-03-27

### Added
- `adder.map()`: synchronous cloud map — distributes items across AWS ECS Fargate workers, returns results in original order
- `CloudExecutor`: `concurrent.futures.Executor` drop-in replacement for `ProcessPoolExecutor`
- `Pool`: reusable cluster that provisions workers once across multiple map calls
- `DetachedSession`: long-running sessions that survive process exit; reattach with `adder.attach(session_id)`
- joblib backend (`AdderBackend`): registered as `'adder'`; enables transparent cloud bursting for scikit-learn and any joblib-using library
- `adder/session.py`: full 7-step worker lifecycle (env snapshot → container build → session init → task decomposition → worker launch → execution → collection)
- `adder/serialize.py`: cloudpickle-based task/result serialization; handles lambdas, closures, interactively-defined functions
- `adder/worker.py`: self-contained ECS worker entrypoint (no adder package required in container)
- `adder/env.py`: environment snapshot via `importlib.metadata`, Docker image management via `burst-core`
- `adder/config.py`: `Config` dataclass reading/writing `~/.burst/config.json` (respects `BURST_CONFIG_PATH` env var)
- `adder/cost.py`: Fargate cost estimation and exact display format from ARCHITECTURE.md
- `adder/errors.py`: `BurstError` hierarchy — `BurstPartialError`, `BurstQuotaError`, `BurstCostLimitError`, `BurstTimeoutError`, `BurstSetupError`
- `adder/cli.py`: `adder` CLI — `setup`, `status`, `session list/status/cleanup`, `config set/show`, `version`
- Unit tests: moto-based, covering serialization, errors, config, cost, env, session lifecycle, executor, joblib backend
- Integration tests: substrate-based, covering full orchestration with S3 (worker completion simulated)
