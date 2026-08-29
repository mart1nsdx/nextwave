"""Volta backend. See docs/ARCHITECTURE.md for why the packages are split this way.

The import graph flows one way: vendor adapters (telephony, realtime) depend on the
composition layer (tools), which depends on deterministic authority (policy) and the
leaf types (domain). Nothing flows back up. tests/test_layering.py enforces it.
"""
