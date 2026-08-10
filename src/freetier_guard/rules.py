"""Loading and matching of AWS Free Tier rules (external YAML data, not code)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_RULES_PATH = files("freetier_guard.data").joinpath("free-tier-rules.yaml")

VALID_SEVERITIES = ("block", "warn")

# attribute operators -> predicate(value_from_plan, rule_arg)
_OPERATORS: dict[str, Any] = {}


def _op(operator):
    def decorator(fn):
        _OPERATORS[operator] = fn
        return fn

    return decorator


@_op("in")
def _in(value, arg):
    return value in arg


@_op("not_in")
def _not_in(value, arg):
    return value not in arg


@_op("eq")
def _eq(value, arg):
    return value == arg


@_op("ne")
def _ne(value, arg):
    return value != arg


@_op("gt")
def _gt(value, arg):
    return _to_number(value) is not None and _to_number(value) > arg


@_op("gte")
def _gte(value, arg):
    return _to_number(value) is not None and _to_number(value) >= arg


@_op("lt")
def _lt(value, arg):
    return _to_number(value) is not None and _to_number(value) < arg


@_op("lte")
def _lte(value, arg):
    return _to_number(value) is not None and _to_number(value) <= arg


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass
class Rule:
    """One firewall-style rule from the YAML rules file."""

    rule_id: str
    title: str
    resource_types: list[str]
    severity: str
    description: str
    message: str
    fix: str
    docs_url: str
    attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_keys_absent: list[str] = field(default_factory=list)
    must_be_unreferenced: bool = False

    def matches_type(self, resource_type: str) -> bool:
        """Exact match, or suffix match for provider wildcards (awscc_, moto_, ...)."""
        for expected in self.resource_types:
            if resource_type == expected:
                return True
            if resource_type.endswith("." + expected):
                return True
        return False

    def evaluate(
        self,
        attributes: dict[str, Any],
        config_keys: set[str],
        referenced_by_others: bool = False,
    ) -> bool:
        """Return True when the rule fires for this resource.

        All configured conditions must pass (they are ANDed). If an attribute
        the rule depends on is unknown at plan time, we refuse to fire rather
        than risk a false positive.
        """
        if self.must_be_unreferenced and referenced_by_others:
            return False

        if self.config_keys_absent:
            if any(key in config_keys for key in self.config_keys_absent):
                return False

        for attr, opmap in self.attributes.items():
            value = attributes.get(attr)
            if value is None:
                return False  # not resolvable at plan time -> do not fire
            for operator, arg in opmap.items():
                fn = _OPERATORS.get(operator)
                if fn is None:
                    raise ValueError(
                        f"Rule '{self.rule_id}' uses unknown operator '{operator}'"
                    )
                if not fn(value, arg):
                    return False
        return True

    def format_message(self, attributes: dict[str, Any]) -> str:
        """Fill {attr_name} placeholders in the message with actual values."""

        def _sub(match: "re.Match[str]") -> str:
            key = match.group(1)
            value = attributes.get(key)
            if value is None:
                return match.group(0)
            return str(value)

        return re.sub(r"\{([a-zA-Z0-9_]+)\}", _sub, self.message)


@dataclass
class Rules:
    rules: list[Rule]

    @property
    def by_id(self) -> dict[str, Rule]:
        return {rule.rule_id: rule for rule in self.rules}


def _required(node: dict[str, Any], key: str, rule_id: str) -> str:
    value = node.get(key)
    if value is None:
        raise ValueError(f"Rule '{rule_id}' is missing required field '{key}'")
    return value


def parse_rules(text: str) -> Rules:
    """Parse a rules YAML document into a validated Rules object.

    Accepts either a bare list of rules or a document with a ``rules`` key
    (``version`` / ``metadata`` are ignored).
    """
    doc = yaml.safe_load(text)
    if isinstance(doc, dict):
        list_node = doc.get("rules")
    else:
        list_node = doc
    if not isinstance(list_node, list):
        raise ValueError("Rules file must be a YAML list of rule definitions")

    parsed: list[Rule] = []
    for node in list_node:
        node = dict(node)
        rule_id = _required(node, "id", "?")
        title = _required(node, "title", rule_id)
        severity = _required(node, "severity", rule_id).lower()
        if severity not in VALID_SEVERITIES:
            raise ValueError(
                f"Rule '{rule_id}' has invalid severity '{severity}' "
                f"(expected one of {', '.join(VALID_SEVERITIES)})"
            )

        when = node.get("when") or {}

        parsed.append(
            Rule(
                rule_id=rule_id,
                title=title,
                resource_types=_required(node, "resource_types", rule_id),
                severity=severity,
                description=_required(node, "description", rule_id),
                message=_required(node, "message", rule_id),
                fix=_required(node, "fix", rule_id),
                docs_url=node.get("docs_url", ""),
                attributes=(when.get("attributes") or {}),
                config_keys_absent=(
                    (when.get("config_keys") or {}).get("all_absent") or []
                ),
                must_be_unreferenced=bool(when.get("must_be_unreferenced", False)),
            )
        )

    if not parsed:
        raise ValueError("Rules file contains no rules")

    return Rules(rules=parsed)


def load_rules(path: Optional[Path]) -> Rules:
    """Load rules from an explicit path, or the packaged default rules."""
    if path is not None:
        if not path.is_file():
            raise FileNotFoundError(f"Rules file not found: {path}")
        return parse_rules(path.read_text(encoding="utf-8"))

    with as_file(DEFAULT_RULES_PATH) as default_path:
        return parse_rules(default_path.read_text(encoding="utf-8"))