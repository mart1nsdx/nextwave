"""The architecture, as a test.

Volta's one idea is that speech is probabilistic and authority is deterministic. That
split is only real if the untrusted side *cannot reach* the trusted side, so the layering
below is enforced here rather than asserted in a doc.

ALLOWED is the contract. Read it bottom-up: the import graph flows one way, from the
vendor adapters that hear the counterparty down toward policy/, which imports nothing but
types. policy/ therefore cannot call a model, touch the network, or be influenced by
anything said on a call — which is what makes "the LLM never writes a commitment"
(AGENTS.md invariant #1) a property of the graph instead of a rule someone has to recall
at 4am.

Changing ALLOWED is an architectural decision. Say so in the PR and log it in
docs/DECISION_LOG.md; do not widen a row to make an import go away.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

ALLOWED: dict[str, set[str]] = {
    "__root__": set(),  # app/__init__.py
    "domain": set(),  # leaf: types only
    "config": set(),  # leaf: env only
    "policy": {"domain"},  # pure, sync, no I/O
    "repo": {"domain", "config"},
    "ledger": {"domain", "repo"},
    "notify": {"domain", "config"},
    "agent": {"domain"},
    "market": {"domain", "policy", "repo", "ledger"},
    "tools": {"domain", "policy", "repo", "ledger", "market", "notify"},
    "realtime": {"domain", "config", "agent", "tools"},
    "telephony": {"domain", "config", "realtime"},
}

# The composition root wires everything together; that is its whole job.
UNRESTRICTED = {"main"}


def _package_of(path: Path) -> str:
    """Which ALLOWED key does this file belong to?"""
    rel = path.relative_to(APP)
    if len(rel.parts) == 1:
        return "__root__" if rel.name == "__init__.py" else rel.stem
    return rel.parts[0]


def _imported_packages(tree: ast.AST, path: Path) -> set[str]:
    """Every app.<package> this file imports, absolute or relative."""
    own_parts = ("app",) + path.relative_to(APP).parts[:-1]
    found: set[str] = set()

    for node in ast.walk(tree):
        target: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "app" and len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # from ..policy import x  ->  climb level-1 packages from own package
                base = list(own_parts[: len(own_parts) - (node.level - 1)])
                target = base + (node.module.split(".") if node.module else [])
            elif node.module:
                target = node.module.split(".")
            if len(target) > 1 and target[0] == "app":
                found.add(target[1])

    return found


def test_imports_respect_layering() -> None:
    violations: list[str] = []

    for path in sorted(APP.rglob("*.py")):
        package = _package_of(path)
        if package in UNRESTRICTED:
            continue

        permitted = ALLOWED[package] | {package}
        for imported in sorted(_imported_packages(ast.parse(path.read_text()), path)):
            if imported not in permitted:
                violations.append(
                    f"  {path.relative_to(APP.parent)}: "
                    f"{package!r} may not import {imported!r} "
                    f"(allowed: {sorted(ALLOWED[package]) or 'nothing'})"
                )

    assert not violations, (
        "Import graph violates the layering contract in tests/test_layering.py:\n"
        + "\n".join(violations)
        + "\n\nThe fix is almost never to widen ALLOWED. Move the code, invert the "
        "dependency, or pass the value in from the composition root (app/main.py)."
    )


def test_every_package_declares_its_contract() -> None:
    """A new directory under app/ must declare its layer before it can hold code.

    This is the point where adding a package becomes a deliberate act rather than a
    side effect of someone needing somewhere to put a file.
    """
    on_disk = {p.name for p in APP.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))}
    declared = set(ALLOWED) - {"__root__"}
    assert on_disk <= declared, (
        f"Undeclared package(s): {sorted(on_disk - declared)}. "
        "Add a row to ALLOWED stating what it may import, and say why in the PR."
    )


def test_layering_map_is_acyclic() -> None:
    """A cycle would mean two packages are really one, and the split is decorative."""
    for package in ALLOWED:
        seen: set[str] = set()
        stack = list(ALLOWED[package])
        while stack:
            current = stack.pop()
            assert current != package, f"Import cycle through {package!r}"
            if current in seen:
                continue
            seen.add(current)
            stack.extend(ALLOWED.get(current, set()))
