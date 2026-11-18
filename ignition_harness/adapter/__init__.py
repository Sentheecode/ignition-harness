"""Thin verified Gateway adapter.

Domain operations are planned from supplied OpenAPI, modules, and tools lists.
The caller supplies request headers. This package does not log in or store secrets.
"""

from .capabilities import discover_capabilities
from .operations import execute, plan

__all__ = ["discover_capabilities", "execute", "plan"]
