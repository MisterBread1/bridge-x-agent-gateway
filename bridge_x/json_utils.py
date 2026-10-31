"""Unambiguous JSON decoding for requests and executable tool arguments."""
import json
import math


def _constant(_value):
    raise ValueError("Non-finite JSON constant")


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def loads(value):
    return json.loads(value, parse_constant=_constant, object_pairs_hook=_object)


def valid_value(value, max_depth=64):
    """Check depth, finite numbers and UTF-8 without recursive traversal."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            return False
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError:
                return False
        elif isinstance(item, float) and not math.isfinite(item):
            return False
        elif isinstance(item, dict):
            pending.extend((part, depth + 1) for part in item.keys())
            pending.extend((part, depth + 1) for part in item.values())
        elif isinstance(item, list):
            pending.extend((part, depth + 1) for part in item)
    return True
