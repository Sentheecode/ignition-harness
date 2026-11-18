"""Best-effort redaction for adapter plans and execute reports.

Header values are removed from saved output. This is not a complete secret
scanner; callers can pass extra literals, and a person still reviews anything
that leaves the machine.
"""

import re

REDACTED = "[redacted]"
_MIN_LITERAL = 4
_PRIVATE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "apitoken",
    "apikey",
    "authorization",
    "cookie",
    "setcookie",
    "sessionid",
    "mcpsessionid",
    "accesstoken",
    "refreshtoken",
    "csrftoken",
}
_SCHEMA_CONTAINERS = {
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
}
_EXAMPLE_KEYS = {"default", "example", "examples"}


class Redactor:
    def __init__(self, literals=None):
        self.literals = set()
        for value in literals or []:
            self.add(value)

    def add(self, value):
        if isinstance(value, str) and len(value) >= _MIN_LITERAL:
            self.literals.add(value)

    def add_header_values(self, headers):
        for name, value in headers.items():
            if not isinstance(value, str):
                continue
            self.add(value)
            if " " in value:
                self.add(value.split(" ", 1)[1])
            if ":" in value:
                self.add(value.split(":", 1)[1])
            lowered = name.lower()
            if lowered in {"cookie", "set-cookie"} or "cookie" in lowered:
                for part in value.split(";"):
                    if "=" in part:
                        self.add(part.split("=", 1)[1].strip())

    def text(self, value):
        for literal in sorted(self.literals, key=len, reverse=True):
            value = value.replace(literal, REDACTED)
        value = re.sub(
            r"(?i)\b(?:bearer|password|passwd|api[_-]?key|token)\s*[=:]\s*\S+",
            REDACTED,
            value,
        )
        value = re.sub(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
            REDACTED,
            value,
        )
        return value

    def clean(self, value, schema_fields=False):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(item, schema_fields=schema_fields) for item in value]
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                normalized = re.sub(r"[^a-z]", "", str(key).lower())
                if not schema_fields and normalized in _PRIVATE_KEYS:
                    item = REDACTED
                elif not schema_fields and key in _EXAMPLE_KEYS:
                    if key == "examples" and isinstance(item, list):
                        item = ["[redacted-schema-value]"] * len(item)
                    else:
                        item = "[redacted-schema-value]"
                child_schema = (not schema_fields) and key in _SCHEMA_CONTAINERS
                cleaned[self.text(str(key))] = self.clean(item, schema_fields=child_schema)
            return cleaned
        return value
