# freetier-guard

**Check a Terraform plan for AWS Free Tier safety — before you run `terraform apply`.**

`freetier-guard` reads the JSON output of `terraform show -json` and tells you,
resource by resource, whether your plan will stay in the AWS Free Tier or
quietly start charging you money.

```console
$ terraform plan -out plan.tfplan
$ terraform show -json plan.tfplan > plan.json
$ freetier-guard check plan.json        # exits 1 if any blocking finding
```

It is free, requires **zero AWS setup** (no billing account, no API keys —
just the plan file), and works locally, in CI, and in GitHub Actions.

---

## The problem it solves

AWS Free Tier is **not one big "everything is free" cap**. It's a patchwork:
some things are *always free*, some are free for 12 months, some are free
*only up to a limit*, and some things **are never free** — no matter how
"free" the surrounding subnet looks.

Beginners get surprise bills from common mistakes like:

| Mistake | What it costs |
| --- | --- |
| NAT Gateway attached to a "free" subnet | **~$32.40/month** even when idle |
| An EC2 instance that isn't `t2.micro` / `t3.micro` | per-hour instance charges from second one |
| Unattached Elastic IP | **billed hourly** until you release it |
| RDS above `db.t3.micro` or over 20 GB storage | per-hour + per-GB database charges |
| Any load balancer | **~$16+/month**, never covered |
| EBS volume over 30 GB | billed per GB-month |

Existing tools like Infracost estimate *total costs* for teams. `freetier-guard`
is the opposite: a single-purpose, zero-setup "yes / no, is this Free Tier
safe" answer aimed at students and bootcampers.

It is **preventive** — it catches problems at plan time (before anything is
created). AWS Budgets is **reactive** — it only alerts *after* money has
already been spent.

---

## Install

Requires **Python 3.9+**.

```console
$ pip install freetier-guard
```

Or run from a checkout (recommended while developing):

```console
$ git clone https://github.com/<you>/freetier-guard
$ cd freetier-guard
$ python -m venv .venv
$ .venv\Scripts\activate        # on Windows;  `source .venv/bin/activate` on macOS/Linux
$ pip install -e .
```

---

## Usage

```console
$ freetier-guard check <plan.json> [--rules rules.yaml] [--json]
```

### Step-by-step

1. Make sure you have Terraform installed (`terraform version`).
2. In your Terraform project, generate a plan **without applying it**:
   ```console
   $ terraform plan -out plan.tfplan
   $ terraform show -json plan.tfplan > plan.json
   ```
   You do **not** need AWS credentials or a billing account for this. (If your
   plan uses data sources, Terraform may still want credentials — the example
   fixture avoids them.)
3. Run the guard:
   ```console
   $ freetier-guard check plan.json
   ```

### What the output means

- **BLOCK** — this resource *will* cost money. The CLI exits with code **1**.
- **WARN** — situational / commonly misused. The CLI exits with code **0**.

```console
$ freetier-guard check plan.json
┌ freetier-guard ────────────────────────────────┐
│ 3 block(s) and 2 warning(s) in this plan        │
└─────────────────────────────────────────────────┘

BLOCK   module.network.aws_nat_gateway.nat    NAT Gateway is never free
   A NAT Gateway is ALWAYS billed (~$32.40/mo) regardless of traffic.
   Remove the NAT Gateway. For learning, keep instances on a PUBLIC subnet ...

BLOCK   aws_instance.bad_type                  EC2 instance type outside the free tier
   Instance type 't3.large' is billed per-hour — only t2.micro / t3.micro are free.
   Change instance_type to "t3.micro" (or t2.micro) while learning.
...

Exiting with code 1 - fix the 3 blocking finding(s) before terraform apply.
```

Use `--json` for machine-readable output ready to feed into CI:

```console
$ freetier-guard check plan.json --json
[
  {
    "severity": "block",
    "rule_id": "nat-gateway-paid",
    "resource": "module.network.aws_nat_gateway.nat",
    "message": "...",
    "fix": "..."
  }
]
```

### Before / after (a real example)

**Before** — your plan contains a NAT Gateway you thought was free:

```hcl
resource "aws_vpc" "main"  { cidr_block = "10.0.0.0/16" }
resource "aws_subnet" "public" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"
}
resource "aws_eip" "nat" {}
resource "aws_nat_gateway" "nat" {
  subnet_id     = aws_subnet.public.id
  allocation_id = aws_eip.nat.id
}
```

```console
$ terraform plan -out plan.tfplan && terraform show -json plan.tfplan > plan.json
$ freetier-guard check plan.json
BLOCK   aws_nat_gateway.nat    NAT Gateway is never free
   A NAT Gateway is ALWAYS billed (~$32.40/month) even with zero traffic.
Exiting with code 1 - fix the 1 blocking finding(s) before terraform apply.
```

**After** — you remove the NAT Gateway, put instances on the public subnet,
and the guard goes green:

```console
$ freetier-guard check plan.json
All clear - every resource fits the AWS Free Tier.
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No blocking findings (be careful with warnings) |
| `1` | At least one BLOCK finding — fix it before applying |
| `2` | Rules file or plan file could not be parsed |

---

## How the rules work

All rules live in
[`freetier_guard/data/free-tier-rules.yaml`](src/freetier_guard/data/free-tier-rules.yaml).
They are **data, not code** — when AWS changes what's covered, you edit the
YAML file, not the Python. Every rule has a `severity` (`block` / `warn`), a
list of `resource_types` to match, optional `when` conditions on attribute
values, a beginner-friendly `message`, and a `fix`.

Rules can be overridden with your own file:

```console
$ freetier-guard check plan.json --rules my-company-rules.yaml
```

Current rules cover: NAT Gateway, EC2 instance types, RDS class + storage +
Multi-AZ, unattached Elastic IPs, load balancers, EBS size + provisioned IOPS,
Secrets Manager, ElastiCache, ECS/Fargate, AWS Backup, Lambda memory, DynamoDB
capacity, CloudWatch alarms, and S3 storage. Covered limits were checked
against the [AWS Free Tier page](https://aws.amazon.com/free/) (Aug 2026) —
note AWS restructured Free Tier in 2025 around credits, but the Always-Free
limits still apply and the "never free" resource types haven't changed.

---

## GitHub Actions (PR check)

Add a workflow so every pull request fails before anyone runs `terraform apply`.
A minimal example that runs on the `terraform_project` fixture:

```yaml
# .github/workflows/freetier-guard.yml
name: freetier-guard

on:
  pull_request:

jobs:
  check-free-tier:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.8.0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install freetier-guard
        run: pip install freetier-guard

      - name: Generate plan JSON
        working-directory: infra
        run: |
          terraform init -input=false
          terraform plan -out plan.tfplan -input=false
          terraform show -json plan.tfplan > plan.json

      - name: Check Free Tier safety
        working-directory: infra
        run: freetier-guard check plan.json
```

The job's exit code follows the plan's blocking findings automatically, so the
PR turns red when someone adds a NAT Gateway by accident.

> Wallet tip: if your infra needs real credentials to plan (data sources,
> remote state), run this against a plan generated with read-only credentials,
> or skip it and rely on the local check — the tool's value is *before apply*.

---

## Development

```console
$ pip install -e ".[dev]"        # or: pip install -e . pytest
$ pytest                          # runs the real Terraform plan test
```

The test suite does **not** use hand-written mock JSON. It runs a real
`terraform init` + `terraform plan` + `terraform show -json` against the
fixture in `tests/fixtures/terraform_project` (a mix of free-tier-safe and
unsafe resources, including a child module) and asserts on the actual plan.
If Terraform isn't installed, those tests are skipped.

## Project layout

```
freetier_guard/
  cli.py                 # Typer CLI (exit codes, --json)
  plan.py                # parse + flatten terraform show -json (root + child modules)
  rules.py               # load / validate / match rules (the YAML engine)
  checker.py             # plan × rules = findings (block / warn)
  report.py              # pretty (rich) and --json rendering
  data/free-tier-rules.yaml   # the rules — edit THIS, not code
```

## License

[MIT](LICENSE)