"""Tests for loading and validating the external rules YAML."""

from __future__ import annotations

import pytest

from freetier_guard.rules import load_rules, parse_rules

EXPECTED_RULE_IDS = {
    "nat-gateway-paid",
    "ec2-instance-type",
    "rds-instance-class",
    "rds-storage",
    "rds-multi-az",
    "eip-unattached",
    "load-balancer-paid",
    "ebs-size",
    "ebs-provisioned-iops",
    "secrets-manager-paid",
    "elasticache-paid",
    "ecs-service-paid",
    "backup-paid",
    "lambda-memory",
    "dynamodb-capacity",
    "dynamodb-pay-per-request",
    "cloudwatch-alarms",
    "s3-storage",
}


def test_packaged_rules_load() -> None:
    rules = load_rules(path=None)
    assert len(rules.rules) >= 10


def test_required_rules_exist() -> None:
    rules = load_rules(path=None)
    rule_ids = {rule.rule_id for rule in rules.rules}
    missing = EXPECTED_RULE_IDS - rule_ids
    assert not missing, f"missing rule ids: {sorted(missing)}"


def test_required_resource_types_covered() -> None:
    rules = load_rules(path=None)
    types_covered = {t for rule in rules.rules for t in rule.resource_types}
    for expected in (
        "aws_nat_gateway",
        "aws_instance",
        "aws_db_instance",
        "aws_eip",
        "aws_lb",
        "aws_ebs_volume",
    ):
        assert expected in types_covered, f"{expected} not covered by any rule"


def test_all_severities_are_valid() -> None:
    rules = load_rules(path=None)
    for rule in rules.rules:
        assert rule.severity in ("block", "warn")


def test_has_blocks_and_warns() -> None:
    rules = load_rules(path=None)
    assert any(rule.severity == "block" for rule in rules.rules)
    assert any(rule.severity == "warn" for rule in rules.rules)


def test_eip_rule_requires_unreferenced() -> None:
    rules = load_rules(path=None)
    eip_rule = rules.by_id["eip-unattached"]
    assert eip_rule.must_be_unreferenced is True
    assert "instance" in eip_rule.config_keys_absent


def test_parse_error_on_scalar() -> None:
    with pytest.raises(ValueError):
        parse_rules("just a string")


def test_parse_error_on_invalid_severity() -> None:
    invalid = """
rules:
  - id: x
    title: X
    resource_types: [aws_instance]
    severity: sometimes
    description: d
    message: m
    fix: f
"""
    with pytest.raises(ValueError):
        parse_rules(invalid)


def test_parse_error_on_missing_field() -> None:
    invalid = """
rules:
  - id: x
    title: X
    severity: block
    message: m
"""
    with pytest.raises(ValueError):
        parse_rules(invalid)