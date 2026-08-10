"""End-to-end checks against the REAL terraform plan fixture."""

from __future__ import annotations

import pytest

from tierguard.checker import block_count, check_plan, warn_count
from tierguard.plan import load_plan
from tierguard.rules import load_rules

from conftest import PLAN_JSON

@pytest.fixture(scope="module")
def findings():
    plan = load_plan(PLAN_JSON)
    rules = load_rules(path=None)
    return check_plan(plan, rules)


@pytest.fixture(scope="module")
def by_resource(findings):
    return {finding.resource_address: finding for finding in findings}


BLOCK_RESOURCES = [
    "module.network.aws_nat_gateway.nat",
    "aws_instance.bad_type",
    "aws_db_instance.big_class",
    "aws_db_instance.big_storage",
    "aws_eip.unattached",
    "aws_lb.app_lb",
    "aws_ebs_volume.big_volume",
    "aws_ebs_volume.io1_volume",
    "aws_secretsmanager_secret.my_secret",
]

WARN_RESOURCES = [
    "aws_lambda_function.big_memory",
    "aws_dynamodb_table.on_demand",
    "aws_dynamodb_table.big_provisioned",
    "aws_cloudwatch_metric_alarm.high_cpu",
]

CLEAN_RESOURCES = [
    "aws_instance.good",                      # t3.micro
    "aws_eip.attached",                        # attached via config
    "module.network.aws_eip.nat_eip",          # used by the NAT gateway
    "aws_db_instance.good_db",                 # db.t3.micro, 20 GB, no multi-az
    "aws_ebs_volume.good_volume",              # 25 GB gp3 (default)
    "module.network.aws_vpc.vpc",              # free-tier safe
    "module.network.aws_internet_gateway.igw", # free-tier safe
]


def test_expected_block_resources_flagged(by_resource) -> None:
    for address in BLOCK_RESOURCES:
        assert by_resource[address].severity == "block", f"{address} should BLOCK"


def test_expected_warn_resources_flagged(by_resource) -> None:
    for address in WARN_RESOURCES:
        assert by_resource[address].severity == "warn", f"{address} should WARN"


def test_free_tier_safe_resources_have_no_findings(by_resource) -> None:
    for address in CLEAN_RESOURCES:
        assert address not in by_resource, f"{address} should be clean"


def test_nat_gateway_is_the_primary_network_charge(by_resource) -> None:
    nat = by_resource["module.network.aws_nat_gateway.nat"]
    assert nat.message  # has an explanation
    assert "32.40" in nat.message


def test_instance_type_message_includes_type(by_resource) -> None:
    finding = by_resource["aws_instance.bad_type"]
    assert "t3.large" in finding.message


def test_severity_exit_policy(findings) -> None:
    assert block_count(findings) >= 9
    assert warn_count(findings) >= 4


def test_findings_sorted_blocks_first(findings) -> None:
    seen_warn = False
    for finding in findings:
        if finding.severity == "warn":
            seen_warn = True
            continue
        assert seen_warn is False, "block findings must come before warns"