"""Integration test: run REAL terraform against the fixture and check it.

This is the strongest guarantee in the test suite: it actually executes
``terraform init`` -> ``terraform plan`` -> ``terraform show -json`` against
marshalled config in tests/fixtures/terraform_project and asserts the tool's
findings are correct against the real Terraform plan JSON structure.

No AWS credentials are required (the fixture provider is configured with the
offline-plan flags). The test is skipped automatically when terraform is not
installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

import pytest

from tierguard.checker import check_plan
from tierguard.plan import parse_plan
from tierguard.rules import load_rules

from conftest import TERRAFORM_PROJECT


@dataclass
class TerraformPlanFixture:
    data: dict
    raw: bytes


def terraform_available() -> bool:
    return shutil.which("terraform") is not None


def _offline_env() -> dict:
    env = dict(os.environ)
    env["AWS_ACCESS_KEY_ID"] = "dummy"
    env["AWS_SECRET_ACCESS_KEY"] = "dummy"
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    return env


@pytest.fixture(scope="module")
def real_terraform_plan() -> TerraformPlanFixture:
    if not terraform_available():
        pytest.skip("terraform is not installed - skipping real-plan integration test")

    env = _offline_env()
    subprocess.run(
        ["terraform", "init", "-input=false"],
        cwd=str(TERRAFORM_PROJECT),
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["terraform", "plan", "-out", "plan.tfplan", "-input=false"],
        cwd=str(TERRAFORM_PROJECT),
        check=True,
        capture_output=True,
        env=env,
    )
    result = subprocess.run(
        ["terraform", "show", "-json", "plan.tfplan"],
        cwd=str(TERRAFORM_PROJECT),
        check=True,
        capture_output=True,
        env=env,
    )
    return TerraformPlanFixture(data=json.loads(result.stdout), raw=result.stdout)


def test_real_plan_parses(real_terraform_plan: TerraformPlanFixture) -> None:
    plan = parse_plan(real_terraform_plan.data)
    assert plan.format_version == "1.2"
    assert len(plan.resources) == 25
    addresses = {r.address for r in plan.resources}
    assert "module.network.aws_nat_gateway.nat" in addresses
    assert "aws_instance.good" in addresses


def test_real_plan_findings_match_fixture_plan(
    real_terraform_plan: TerraformPlanFixture,
) -> None:
    plan = parse_plan(real_terraform_plan.data)
    findings = check_plan(plan, load_rules(path=None))
    by_resource = {f.resource_address: f.severity for f in findings}

    # Blocking mistakes in the fixture
    assert by_resource["module.network.aws_nat_gateway.nat"] == "block"
    assert by_resource["aws_instance.bad_type"] == "block"
    assert by_resource["aws_eip.unattached"] == "block"
    assert by_resource["aws_lb.app_lb"] == "block"

    # Free-tier safe resources stay silent
    for clean in (
        "aws_instance.good",
        "aws_eip.attached",
        "module.network.aws_eip.nat_eip",
        "aws_db_instance.good_db",
        "aws_ebs_volume.good_volume",
    ):
        assert clean not in by_resource


def test_real_plan_has_exactly_one_bad_eip(
    real_terraform_plan: TerraformPlanFixture,
) -> None:
    plan = parse_plan(real_terraform_plan.data)
    findings = check_plan(plan, load_rules(path=None))
    eips = {f.resource_address for f in findings if f.resource_type == "aws_eip"}
    assert eips == {"aws_eip.unattached"}