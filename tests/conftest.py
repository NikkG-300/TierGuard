"""Shared test fixtures (paths + tiny helpers)."""

from pathlib import Path

from tierguard.plan import Plan, Resource

FIXTURES = Path(__file__).parent / "fixtures"
PLAN_JSON = FIXTURES / "plans" / "plan.json"
TERRAFORM_PROJECT = FIXTURES / "terraform_project"


def make_plan_with_resources(resources: list[Resource]) -> Plan:
    return Plan(
        format_version="1.2",
        terraform_version="1.15.4",
        resources=resources,
        referenced_addresses=set(),
    )


def resource_of(plan: Plan, address: str) -> Resource:
    for resource in plan.resources:
        if resource.address == address:
            return resource
    raise KeyError(f"resource {address!r} not in plan")