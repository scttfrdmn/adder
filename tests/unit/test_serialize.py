"""Unit tests for adder/serialize.py."""

from adder.serialize import (
    deserialize_result,
    deserialize_task,
    serialize_result,
    serialize_task,
)


def test_serialize_task_roundtrip_lambda():
    """cloudpickle must handle lambda functions."""
    def fn(x):
        return x * 2
    items = [1, 2, 3]
    data = serialize_task(fn, items)
    assert isinstance(data, bytes)
    fn2, items2 = deserialize_task(data)
    assert items2 == items
    assert fn2(5) == 10


def test_serialize_task_roundtrip_closure():
    """cloudpickle must handle closures."""
    multiplier = 7

    def fn(x):
        return x * multiplier

    items = [1, 2, 3]
    data = serialize_task(fn, items)
    fn2, items2 = deserialize_task(data)
    assert fn2(3) == 21
    assert items2 == items


def test_serialize_task_includes_python_version():
    """Task payload includes python_version field."""
    import cloudpickle
    import sys

    def fn(x):
        return x
    data = serialize_task(fn, [])
    payload = cloudpickle.loads(data)
    assert "python_version" in payload
    assert payload["python_version"] == sys.version_info[:3]


def test_serialize_result_roundtrip():
    """Results round-trip through cloudpickle."""
    results = [1, "hello", {"key": "value"}, None, [1, 2, 3]]
    data = serialize_result(results)
    assert isinstance(data, bytes)
    assert deserialize_result(data) == results


def test_serialize_result_complex_objects():
    """Results can contain complex objects."""
    import datetime

    results = [datetime.date(2026, 3, 15), {"nested": [1, 2, 3]}]
    data = serialize_result(results)
    assert deserialize_result(data) == results


def test_serialize_task_interactively_defined():
    """cloudpickle handles functions defined in non-module scope."""
    # Simulate a function defined in __main__ by using exec
    ns = {}
    exec("def my_fn(x): return x + 100", ns)
    fn = ns["my_fn"]
    items = [1, 2, 3]
    data = serialize_task(fn, items)
    fn2, items2 = deserialize_task(data)
    assert fn2(5) == 105
