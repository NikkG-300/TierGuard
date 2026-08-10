"""CLI behaviour tests (exit codes, --json, error handling)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from tierguard.cli import app

from conftest import PLAN_JSON

runner = CliRunner()

# Minimal plan JSON built from the same real terraform structure (used only to
# exercise the clean "no blocks" exit path; all parsing correctness is tested
# against the real plan fixture elsewhere).
SAFE_PLAN = {
    "format_version": "1.2",
    "terraform_version": "1.15.4",
    "resource_changes": [
        {
            "address": "aws_instance.safe",
            "mode": "managed",
            "type": "aws_instance",
            "name": "safe",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "change": {"actions": ["create"], "after": {"instance_type": "t3.micro"}},
        },
        {
            "address": "aws_s3_bucket.bucket",
            "mode": "managed",
            "type": "aws_s3_bucket",
            "name": "bucket",
            "provider_name": "registry.terraform.io/hashicorp/aws",
            "change": {"actions": ["create"], "after": {"bucket": "data"}},
        },
    ],
    "configuration": {
        "root_module": {
            "resources": [
                {
                    "address": "aws_instance.safe",
                    "mode": "managed",
                    "type": "aws_instance",
                    "name": "safe",
                    "provider_config_key": "aws",
                    "expressions": {
                        "instance_type": {"constant_value": "t3.micro"}
                    },
                },
                {
                    "address": "aws_s3_bucket.bucket",
                    "mode": "managed",
                    "type": "aws_s3_bucket",
                    "name": "bucket",
                    "provider_config_key": "aws",
                    "expressions": {"bucket": {"constant_value": "data"}},
                },
            ]
        }
    },
}


def test_check_exits_1_when_blocks_exist() -> None:
    result = runner.invoke(app, ["check", str(PLAN_JSON)])
    assert result.exit_code == 1
    assert "NAT Gateway" in result.output
    assert "BLOCK" in result.output


def test_check_exits_0_when_plan_is_safe(tmp_path) -> None:
    plan_file = tmp_path / "safe.json"
    plan_file.write_text(json.dumps(SAFE_PLAN), encoding="utf-8")
    result = runner.invoke(app, ["check", str(plan_file)])
    assert result.exit_code == 0
    assert "0 block(s)" in result.output
    assert "No blocking findings" in result.output


def test_check_json_output(tmp_path) -> None:
    plan_file = tmp_path / "safe.json"
    plan_file.write_text(json.dumps(SAFE_PLAN), encoding="utf-8")
    result = runner.invoke(app, ["check", str(plan_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [f for f in payload if f["severity"] == "warn"]
    assert not [f for f in payload if f["severity"] == "block"]


def test_check_json_on_unsafe_plan_contains_blocks() -> None:
    result = runner.invoke(app, ["check", str(PLAN_JSON), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any(f["severity"] == "block" for f in payload)
    rule_ids = {f["rule_id"] for f in payload}
    assert "nat-gateway-paid" in rule_ids


def test_check_missing_plan_exits_2() -> None:
    result = runner.invoke(app, ["check", "no/such/plan.json"])
    assert result.exit_code == 2


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # Typer's no_args_is_help prints help (exit 0) or reports a usage error (2)
    # depending on the installed version; both are acceptable for a bare run.
    assert result.exit_code in (0, 2)
    assert "check" in result.output