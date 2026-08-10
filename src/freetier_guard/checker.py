"""Core check logic: match every planned resource against the Free Tier rules."""

from __future__ import annotations

from dataclasses import dataclass

from freetier_guard.plan import Plan, Resource
from freetier_guard.rules import Rule, Rules


@dataclass
class Finding:
    """One rule firing against one planned resource."""

    severity: str
    rule_id: str
    rule_title: str
    resource_address: str
    resource_type: str
    module_address: str
    message: str
    fix: str
    docs_url: str


def check_plan(plan: Plan, rules: Rules) -> list[Finding]:
    """Evaluate a flattened plan against every rule.

    Returns findings sorted by severity (block first) then by address.
    """
    findings: list[Finding] = []
    for resource in plan.managed_resources():
        for rule in rules.rules:
            if not rule.matches_type(resource.type):
                continue
            if rule.evaluate(resource.attributes, resource.config_keys, resource.referenced_by_others):
                findings.append(_to_finding(resource, rule))

    findings.sort(key=lambda f: (0 if f.severity == "block" else 1, f.resource_address))
    return findings


def block_count(findings: list[Finding]) -> int:
    return sum(1 for finding in findings if finding.severity == "block")


def warn_count(findings: list[Finding]) -> int:
    return sum(1 for finding in findings if finding.severity == "warn")


def _to_finding(resource: Resource, rule: Rule) -> Finding:
    return Finding(
        severity=rule.severity,
        rule_id=rule.rule_id,
        rule_title=rule.title,
        resource_address=resource.address,
        resource_type=resource.type,
        module_address=resource.module_address,
        message=rule.format_message(resource.attributes),
        fix=rule.fix,
        docs_url=rule.docs_url,
    )