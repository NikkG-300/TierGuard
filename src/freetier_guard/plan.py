"""Parsing and flattening of ``terraform show -json`` plan output.

Terraform's JSON plan has two views:

  * ``configuration`` — a tree of ``root_module`` with nested ``module_calls``.
    We recursively walk it (root + child modules) to enumerate every resource
    and to learn which attributes are *referenced in the config* (this is how
    we tell an attached Elastic IP from an unattached one at plan time).
  * ``resource_changes`` — a flat list, one entry per concrete resource
    (already including module context, count / for_each instances). This is
    where the resolved attribute values live (``change.after``).

We join the two views: the recursive walk produces the resource inven tory,
and ``resource_changes`` supplies the planned attribute values. Resources are
flattened into a single :class:`Plan`, so the checker never thinks about
module nesting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional


@dataclass
class Resource:
    """A single planned managed resource, flattened out of the plan JSON."""

    address: str
    type: str
    name: str
    module_address: str  # "" for root modules, e.g. "module.network"
    provider: str
    actions: list[str]
    attributes: dict[str, Any]  # planned "after" values (may hold None)
    config_keys: set[str] = field(default_factory=set)  # args written in .tf
    referenced_by_others: bool = False  # another resource points at this one

    @property
    def is_create(self) -> bool:
        return "create" in self.actions or self.actions == ["no-op"]

    @property
    def destroys(self) -> bool:
        return "delete" in self.actions


@dataclass
class Plan:
    """A parsed and flattened Terraform plan."""

    format_version: str
    terraform_version: str
    resources: list[Resource] = field(default_factory=list)

    referenced_addresses: set[str] = field(default_factory=set)

    def managed_resources(self) -> Iterator[Resource]:
        """Yield resources that will still exist after apply (not teardown)."""
        for resource in self.resources:
            if resource.destroys:
                continue
            yield resource


def parse_plan(data: dict[str, Any]) -> Plan:
    """Build a flattened :class:`Plan` from parsed ``terraform show -json`` data."""
    format_version = data.get("format_version", "?")
    terraform_version = data.get("terraform_version", "?")

    configuration = data.get("configuration") or {}
    changes = data.get("resource_changes") or []

    # Walk the configuration tree ONCE for the resource inventory and to learn
    # which attributes are written in the .tf files.
    config_resources = list(_walk_configuration(configuration))
    config_resources = [
        (mod, res) for mod, res in config_resources if res.get("mode") == "managed"
    ]

    # Build the set of resource addresses referenced by any OTHER resource:
    # turns "aws_eip.nat_eip" (referenced by the NAT gateway via allocation_id)
    # into "module.network.aws_eip.nat_eip". Used to avoid false positives for
    # things like Elastic IPs that ARE being used.
    referenced_addresses = _collect_referenced_addresses(config_resources)

    # --- index resource_changes by (module_address, local base address) ---
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for change in changes:
        if change.get("mode") != "managed":
            continue
        module_address = change.get("module_address") or ""
        local = change.get("address", "")
        if module_address:
            local = local.removeprefix(module_address + ".")
        local = local.split("[", 1)[0]  # strip [0] / ["x"] instance suffix
        by_key.setdefault((module_address, local), []).append(change)

    resources: list[Resource] = []
    matched_change_addresses: set[str] = set()

    for module_address, resource_node in config_resources:
        address = resource_node.get("address", "")
        local = address.split("[", 1)[0]
        config_keys = set((resource_node.get("expressions") or {}).keys())
        matched_changes = by_key.get((module_address, local), [])

        if not matched_changes:
            # No plan entry (e.g. already exists / unchanged): emit with the
            # attributes we can read directly from config constant values.
            resources.append(
                _resource_from_config_only(
                    module_address,
                    resource_node,
                    config_keys,
                    referenced_addresses,
                )
            )
            continue

        for change in matched_changes:
            matched_change_addresses.add(change.get("address", ""))
            resources.append(
                _resource_from_change(
                    module_address,
                    resource_node,
                    config_keys,
                    change,
                    referenced_addresses,
                )
            )

    # Any managed change not represented in the config tree (rare) still
    # needs to be checked — flatten it too.
    for change in changes:
        if change.get("mode") != "managed":
            continue
        if change.get("address") in matched_change_addresses:
            continue
        resources.append(
            _resource_from_change(
                change.get("module_address") or "",
                _node_from_change(change),
                set(),
                change,
                referenced_addresses,
            )
        )

    return Plan(
        format_version=format_version,
        terraform_version=terraform_version,
        resources=resources,
        referenced_addresses=referenced_addresses,
    )


def load_plan(path: Path) -> Plan:
    """Load a ``terraform show -json`` plan file from disk.

    Tolerates the weird encodings people end up with on Windows terminals
    (PowerShell's ``>`` redirect writes UTF-16, and some shells add a BOM).
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    data = json.loads(text)
    return parse_plan(data)


def _walk_configuration(configuration: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Recursively walk root_module + child modules, yielding resources.

    Yields ``(module_address, resource_node)`` pairs. Root resources get an
    empty module address; resources inside ``module "network"`` get
    ``"module.network"`` (mirroring Terraform's own module_address format).
    """
    root = configuration.get("root_module") or {}
    yield from _walk_module(root, "")


def _walk_module(module: dict[str, Any], module_address: str) -> Iterator[tuple[str, dict[str, Any]]]:
    for resource in module.get("resources", []):
        yield module_address, resource

    for name, call in (module.get("module_calls") or {}).items():
        child_module = call.get("module") or {}
        child_address = (
            f"module.{name}" if not module_address else f"{module_address}.module.{name}"
        )
        yield from _walk_module(child_module, child_address)


def _change_after(change: dict[str, Any]) -> dict[str, Any]:
    inner = change.get("change") or {}
    after = inner.get("after")
    return dict(after) if isinstance(after, dict) else {}


def _change_actions(change: dict[str, Any]) -> list[str]:
    inner = change.get("change") or {}
    return list(inner.get("actions") or [])


def _node_from_change(change: dict[str, Any]) -> dict[str, Any]:
    return {
        "address": change.get("address", ""),
        "type": change.get("type", ""),
        "name": change.get("name", ""),
    }


def _full_address(module_address: str, address: str) -> str:
    """Turn a module-relative address into the global address used in the plan."""
    if module_address:
        return f"{module_address}.{address}".split("[", 1)[0]
    return address.split("[", 1)[0]


def _as_local_address(address: str, module_address: str) -> str:
    """Strip a module prefix from a full address (change addresses carry it)."""
    if module_address and address.startswith(module_address + "."):
        return address[len(module_address) + 1 :]
    return address


def _global_address(address: str, module_address: str) -> str:
    """Canonical global address for a (possibly full) address with module context."""
    return _full_address(module_address, _as_local_address(address, module_address))


def _collect_referenced_addresses(
    config_resources: list[tuple[str, dict[str, Any]]],
) -> set[str]:
    """Find every resource address that another resource references in config.

    Referenced addresses are stored WITHOUT instance suffixes and WITH their
    module prefix, e.g. ``module.network.aws_eip.nat_eip``.
    """
    referenced: set[str] = set()
    for module_address, resource_node in config_resources:
        for reference in _iter_references(resource_node):
            local = _first_resource_segment(reference)
            if local:
                referenced.add(_full_address(module_address, local))
    return referenced


def _iter_references(resource_node: dict[str, Any]) -> Iterator[str]:
    """Recursively yield every ``references`` entry in a resource's config node."""

    def walk(node: Any) -> Iterator[str]:
        if isinstance(node, dict):
            if "references" in node and isinstance(node["references"], list):
                for ref in node["references"]:
                    if isinstance(ref, str):
                        yield ref
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    yield from walk(resource_node.get("expressions") or {})


def _first_resource_segment(reference: str) -> Optional[str]:
    """Extract ``type.name`` from a Terraform reference like ``aws_eip.nat_eip.id``."""
    parts = reference.split(".")
    if len(parts) < 2:
        return None
    if parts[0] == "module" or parts[0] in ("var", "local", "data", "each", "count"):
        return None
    return f"{parts[0]}.{parts[1]}".split("[", 1)[0]


def _resource_from_change(
    module_address: str,
    resource_node: dict[str, Any],
    config_keys: set[str],
    change: dict[str, Any],
    referenced_addresses: set[str],
) -> Resource:
    global_address = _global_address(
        change.get("address", resource_node.get("address", "")), module_address
    )
    return Resource(
        address=change.get("address", resource_node.get("address", "")),
        type=change.get("type", resource_node.get("type", "")),
        name=change.get("name", resource_node.get("name", "")),
        module_address=module_address,
        provider=change.get("provider_name", ""),
        actions=_change_actions(change),
        attributes=_change_after(change),
        config_keys=config_keys,
        referenced_by_others=global_address in referenced_addresses,
    )


def _resource_from_config_only(
    module_address: str,
    resource_node: dict[str, Any],
    config_keys: set[str],
    referenced_addresses: set[str],
) -> Resource:
    expressions = resource_node.get("expressions") or {}
    attributes: dict[str, Any] = {}
    for key, expr in expressions.items():
        if isinstance(expr, dict) and "constant_value" in expr:
            attributes[key] = expr["constant_value"]

    return Resource(
        address=resource_node.get("address", ""),
        type=resource_node.get("type", ""),
        name=resource_node.get("name", ""),
        module_address=module_address,
        provider=resource_node.get("provider_config_key", ""),
        actions=["no-op"],
        attributes=attributes,
        config_keys=config_keys,
        referenced_by_others=(
            _full_address(module_address, resource_node.get("address", ""))
            in referenced_addresses
        ),
    )