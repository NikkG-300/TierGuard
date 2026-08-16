"""Rendering of check results: human-readable (rich) and machine JSON."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tierguard.checker import Finding, block_count, warn_count

SEVERITY_STYLE = {"block": "bold red", "warn": "bold yellow"}
SEVERITY_ICON = {"block": "BLOCK", "warn": "WARN"}


def findings_json(findings: list[Finding]) -> str:
    payload: list[dict[str, Any]] = []
    for finding in findings:
        payload.append(
            {
                "severity": finding.severity,
                "rule_id": finding.rule_id,
                "rule_title": finding.rule_title,
                "resource": finding.resource_address,
                "resource_type": finding.resource_type,
                "message": finding.message,
                "fix": finding.fix,
                "docs_url": finding.docs_url,
            }
        )
    return json.dumps(payload, indent=2)


def render_pretty(findings: list[Finding]) -> str:
    """Render findings to an ANSI string suitable for a terminal."""
    console = Console(record=True, highlight=False)

    blocks = block_count(findings)
    warns = warn_count(findings)

    if not findings:
        console.print(
            Panel(
                Text(
                    "All clear - no blocked resources in this plan.",
                    style="bold green",
                ),
                title="TierGuard",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                Text(
                    f"{blocks} block(s) and {warns} warning(s) in this plan",
                    style="bold" if blocks else "bold yellow",
                ),
                title="TierGuard",
                border_style="red" if blocks else "yellow",
            )
        )
        console.print()

        table = Table(show_header=False, border_style="dim", pad_edge=False, box=None)
        for finding in findings:
            label = Text(SEVERITY_ICON[finding.severity], style=SEVERITY_STYLE[finding.severity])
            table.add_row(
                label,
                Text(finding.resource_address),
                Text(finding.rule_title, style=SEVERITY_STYLE[finding.severity]),
            )

            message = Text(f"   {finding.message}", style=SEVERITY_STYLE[finding.severity])
            table.add_row("", message)
            if finding.fix:
                table.add_row("", Text(f"   {finding.fix}", style="dim"))
            table.add_row("", "")

        console.print(table)

    if findings:
        footer = Text()
        if blocks:
            footer.append(
                f"Exiting with code 1 - fix the {blocks} blocking finding(s) before terraform apply.",
                style="bold red",
            )
        else:
            footer.append(
                "No blocking findings - your plan is safe to apply (keep an eye on the warnings).",
                style="bold yellow",
            )
        console.print()
        console.print(footer)

    return console.export_text()