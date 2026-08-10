"""Tests for parsing/flattening a REAL ``terraform show -json`` plan.

The fixture plan (tests/fixtures/plans/plan.json) is the actual output of a
terraform plan against tests/fixtures/terraform_project — not a hand-written
mock. It exercises root + child module flattening, installed attribute
values, and cross-resource reference detection.
"""

from __future__ import annotations

from tierguard.plan import load_plan

from conftest import PLAN_JSON, resource_of


def test_plan_loads() -> None:
    plan = load_plan(PLAN_JSON)
    assert plan.format_version == "1.2"
    assert plan.terraform_version
    # 25 managed resources created in the fixture plan
    assert len(list(plan.managed_resources())) == 25


def test_root_and_child_modules_flattened() -> None:
    plan = load_plan(PLAN_JSON)
    addresses = {resource.address for resource in plan.resources}

    assert "aws_instance.good" in addresses                    # root module
    assert addresses & {
        "aws_nat_gateway.x",  # sanity: none invented
    } == set()
    assert "module.network.aws_nat_gateway.nat" in addresses   # child module
    assert "module.network.aws_vpc.vpc" in addresses
    assert "module.network.aws_eip.nat_eip" in addresses


def test_module_addresses_are_correct() -> None:
    plan = load_plan(PLAN_JSON)
    nat = resource_of(plan, "module.network.aws_nat_gateway.nat")
    vpc = resource_of(plan, "module.network.aws_vpc.vpc")
    instance = resource_of(plan, "aws_instance.good")

    assert nat.module_address == "module.network"
    assert vpc.module_address == "module.network"
    assert instance.module_address == ""


def test_attribute_values_are_resolved() -> None:
    plan = load_plan(PLAN_JSON)
    bad = resource_of(plan, "aws_instance.bad_type")
    good = resource_of(plan, "aws_instance.good")
    assert bad.attributes["instance_type"] == "t3.large"
    assert good.attributes["instance_type"] == "t3.micro"

    storage = resource_of(plan, "aws_db_instance.big_storage")
    assert storage.attributes["allocated_storage"] == 100

    volume = resource_of(plan, "aws_ebs_volume.io1_volume")
    assert volume.attributes["type"] == "io1"


def test_config_keys_record_written_arguments() -> None:
    plan = load_plan(PLAN_JSON)
    attached = resource_of(plan, "aws_eip.attached")
    unattached = resource_of(plan, "aws_eip.unattached")
    assert "instance" in attached.config_keys
    assert "instance" not in unattached.config_keys


def test_reference_detection_handles_modules() -> None:
    plan = load_plan(PLAN_JSON)
    # EIP inside the module is used by the NAT gateway -> referenced
    nat_eip = resource_of(plan, "module.network.aws_eip.nat_eip")
    assert nat_eip.referenced_by_others is True
    # Root EIP attached via config arg -> config key present, not a stray ref
    attached = resource_of(plan, "aws_eip.attached")
    assert attached.referenced_by_others is False
    # EC2 instance referenced by the EIP
    instance = resource_of(plan, "aws_instance.good")
    assert instance.referenced_by_others is True