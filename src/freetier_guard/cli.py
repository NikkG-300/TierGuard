"""freetier-guard command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from freetier_guard import __version__
from freetier_guard.checker import block_count, check_plan
from freetier_guard.plan import load_plan
from freetier_guard.report import findings_json, render_pretty
from freetier_guard.rules import load_rules

app = typer.Typer(
    name="freetier-guard",
    help="Check a Terraform plan for AWS Free Tier safety BEFORE you apply.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"freetier-guard {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit.", callback=_version_callback
    ),
) -> None:
    """freetier-guard: catch surprise AWS bills before they happen."""


@app.command(
    help=(
        "Check a Terraform plan (from 'terraform show -json') against the AWS "
        "Free Tier rules. Exits 1 when any 'block' finding exists, 0 otherwise."
    )
)
def check(
    plan_json: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the terraform show -json output file.",
    ),
    rules: Optional[Path] = typer.Option(
        None,
        "--rules",
        "-r",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to a custom rules YAML file (defaults to the packaged rules).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print findings as JSON instead of the pretty table (handy for CI).",
    ),
) -> None:
    try:
        plan = load_plan(plan_json)
        ruleset = load_rules(rules)
        findings = check_plan(plan, ruleset)
    except (FileNotFoundError, ValueError, OSError) as exc:
        typer.echo(f"freetier-guard: error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if json_output:
        typer.echo(findings_json(findings))
    else:
        typer.echo(render_pretty(findings))

    raise typer.Exit(code=1 if block_count(findings) else 0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()