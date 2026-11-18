"""Check 2027 tag read/write bodies against the isolated Gateway OpenAPI excerpt.

The excerpt is the top-level type, property names, and required keys from
commit f44dc24, docs/evidence/isolated-linux-same-tab/beta1-tag-openapi-fields.json.
That file does not include item schemas. This module rejects a body that is
not the declared object or that uses a property the excerpt does not list.
"""

import json
from pathlib import Path

from .errors import AdapterError

_SCHEMA_PATH = Path(__file__).with_name("tag_request_schema.json")
SCHEMA_SOURCE = "f44dc24:docs/evidence/isolated-linux-same-tab/beta1-tag-openapi-fields.json"


def load_tag_request_schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def check_tag_request(kind, body):
    """Return body when it matches the excerpt. Otherwise raise."""
    schema = load_tag_request_schema().get(kind)
    if not isinstance(schema, dict):
        raise AdapterError("request_schema_mismatch")
    if schema.get("type") == "object" and not isinstance(body, dict):
        raise AdapterError("request_schema_mismatch")
    properties = schema.get("properties") or []
    required = schema.get("required") or []
    if not isinstance(properties, list) or not isinstance(required, list):
        raise AdapterError("request_schema_mismatch")
    if any(not isinstance(key, str) for key in properties + required):
        raise AdapterError("request_schema_mismatch")
    if any(key not in body for key in required):
        raise AdapterError("request_schema_mismatch")
    if any(key not in properties for key in body):
        raise AdapterError("request_schema_mismatch")
    return body
