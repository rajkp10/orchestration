# Event-Driven Infrastructure Orchestrator

A lifecycle **event** (`db.postgres.provision`, `db.postgres.patch`, `db.postgres.decommission`) starts a **Temporal workflow**. The workflow validates the request, runs **Terraform** to make the change, verifies the real resource, and reports the result.

Terraform uses the Docker provider, so "a database" here is a real PostgreSQL container on your machine. No cloud account or credentials are needed.

The design, the trade-offs and the answers to the assignment's design questions are in [docs/DESIGN.md](docs/DESIGN.md). This file only covers how to run the system.

**Demo video:** [provision → patch → decommission](docs/demo/demonstration-provision-patch-decommission.mp4)

## Contents

1. [What you need installed](#1-what-you-need-installed)
2. [One-time setup](#2-one-time-setup)
3. [Start the system](#3-start-the-system)
4. [Demo: provision → patch → decommission](#4-demo-provision--patch--decommission)
5. [More scenarios: duplicates and failures](#5-more-scenarios-duplicates-and-failures)
6. [Command and event reference](#6-command-and-event-reference)
7. [Run the tests](#7-run-the-tests)
8. [Shut down and reset](#8-shut-down-and-reset)
9. [Troubleshooting](#9-troubleshooting)
10. [Assumptions](#10-assumptions)
11. [Repository layout](#11-repository-layout)

## 1. What you need installed

| Tool                              | Version                         | Why                                | Check it with        |
| --------------------------------- | ------------------------------- | ---------------------------------- | -------------------- |
| Python                            | 3.11 or newer                   | The worker and the trigger         | `python --version`   |
| Terraform CLI                     | 1.6 or newer                    | Makes the infrastructure change    | `terraform version`  |
| Docker Desktop (or Docker Engine) | any recent version, **running** | Hosts the Postgres containers      | `docker info`        |
| Temporal CLI                      | any recent version              | Runs the local Temporal dev server | `temporal --version` |
| Git                               | any                             | To clone the repository            | `git --version`      |

Install links: [Python](https://www.python.org/downloads/), [Terraform](https://developer.hashicorp.com/terraform/install), [Docker Desktop](https://www.docker.com/products/docker-desktop/), [Temporal CLI](https://docs.temporal.io/cli#install) (on macOS: `brew install temporal`).

All five must work in your terminal before you continue. `docker info` must show a "Server" section; if it shows an error, start Docker Desktop first.

You also need:

- **An internet connection for the first run.** `pip` downloads the Python packages, Terraform downloads two providers (`kreuzwerker/docker`, `hashicorp/random`), and Docker pulls the `postgres:16.3` and `postgres:16.4` images (about 150 MB each).
- **Ports 7233 and 8233 free.** The Temporal dev server uses them. Postgres containers get a free port chosen by Docker.
- **Three terminal windows**, all opened in the repository root.

This was built and tested on Windows 11 with Python 3.11.0, Terraform 1.16.4, Docker 26.0.0 and Temporal CLI 1.9.1. It also runs on macOS and Linux; the only command that differs is the one that activates the virtual environment.

## 2. One-time setup

Run these commands.

**1. Get the code.**

```bash
git clone <repository-url>
```

```bash
cd orchestration
```

**2. Create a virtual environment.**

```bash
python -m venv .venv
```

**3. Activate it.** Use the line for your shell. Your prompt then starts with `(.venv)`.

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS, Linux or Git Bash:

```bash
source .venv/bin/activate
```

(In Git Bash on Windows the path is `.venv/Scripts/activate`. If PowerShell refuses to run the script, run `Set-ExecutionPolicy -Scope Process RemoteSigned` once in that window.)

**4. Install the project and its development tools.**

```bash
pip install -e ".[dev]"
```

Expected: the last line is `Successfully installed ... orchestrator-0.1.0 ... temporalio-... psycopg-...`.

There is no separate `terraform init` step. The worker runs `terraform init` itself before each Terraform operation, so the providers are downloaded on the first event.

## 3. Start the system

Two long-running processes are needed: the Temporal server and the worker. Each gets its own terminal and stays open.

### Terminal 1: Temporal server

```bash
temporal server start-dev
```

Expected output:

```
Temporal CLI 1.9.1 (Server 1.32.0, UI 2.54.1)

Temporal Server:      localhost:7233
Temporal Persistence: in-memory
Temporal UI:          http://localhost:8233
Temporal Metrics:     http://localhost:56351/metrics
```

Leave it running. Open <http://localhost:8233> in a browser to watch workflows in the Temporal UI.

### Terminal 2: the worker

Activate the virtual environment (step 3 of setup), then:

```bash
python -m orchestrator.worker
```

Expected output:

```
2026-10-03 18:23:59,720 INFO worker listening on task queue 'lifecycle' at localhost:7233
```

Leave it running. This is where one log line appears for every finished request.

### Terminal 3: the trigger

Activate the virtual environment here too. Every command in the next sections is typed in this terminal.

## 4. Demo: provision → patch → decommission

The steps below are shown being run in the [demo video](docs/demo/demonstration-provision-patch-decommission.mp4).

Each step sends one event file from `events/`. The trigger starts a workflow, waits for it, prints the final result as JSON and exits with code `0` on success.

### Step 1: provision

**Input:** [events/provision.json](events/provision.json)

```json
{
  "request_id": "req-orders-provision-001",
  "type": "db.postgres.provision",
  "resource_id": "orders",
  "params": {
    "version": "16.3",
    "env": "dev"
  }
}
```

**Command:**

```bash
python -m orchestrator.trigger send events/provision.json
```

**Output** (about 10 seconds; the very first run takes a minute or two longer while providers and the image download):

```
started db.postgres.provision for orders (request req-orders-provision-001)
{
  "request_id": "req-orders-provision-001",
  "event_type": "db.postgres.provision",
  "resource_id": "orders",
  "status": "COMPLETED",
  "detail": "provision applied and verified",
  "changed": true,
  "outputs": {
    "container_name": "pg-orders",
    "env": "dev",
    "host_port": 32791,
    "postgres_version": "16.3",
    "resource_id": "orders"
  }
}
```

`host_port` is chosen by Docker and will differ on your machine. The database password is never printed: it stays in Terraform state.

**Check it yourself.** The container is running and healthy:

```bash
docker ps --filter name=pg-orders
```

```
NAMES       IMAGE          STATUS                   PORTS
pg-orders   07a4ee949b9e   Up 7 seconds (healthy)   0.0.0.0:32791->5432/tcp
```

Put a row in the database, so you can see that the patch keeps the data:

```bash
docker exec pg-orders psql -U postgres -c "CREATE TABLE demo (id int); INSERT INTO demo VALUES (1);"
```

```
CREATE TABLE
INSERT 0 1
```

### Step 2: patch

**Input:** [events/patch.json](events/patch.json) asks for version `16.4`.

```json
{
  "request_id": "req-orders-patch-001",
  "type": "db.postgres.patch",
  "resource_id": "orders",
  "params": {
    "version": "16.4"
  }
}
```

**Command:**

```bash
python -m orchestrator.trigger send events/patch.json
```

**Output** (about 10 seconds):

```
started db.postgres.patch for orders (request req-orders-patch-001)
{
  "request_id": "req-orders-patch-001",
  "event_type": "db.postgres.patch",
  "resource_id": "orders",
  "status": "COMPLETED",
  "detail": "patch applied and verified",
  "changed": true,
  "outputs": {
    "container_name": "pg-orders",
    "env": "dev",
    "host_port": 32791,
    "postgres_version": "16.4",
    "resource_id": "orders"
  }
}
```

The container was replaced with a 16.4 one. The `host_port` is the same as before, and the data volume was kept.

**Check it yourself.** Postgres reports the new version, and the row from step 1 is still there:

```bash
docker exec pg-orders psql -U postgres -c "SELECT version();" -c "SELECT * FROM demo;"
```

```
                                                       version
---------------------------------------------------------------------------------------------------------------------
 PostgreSQL 16.4 (Debian 16.4-1.pgdg120+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14) 12.2.0, 64-bit
(1 row)

 id
----
  1
(1 row)
```

### Step 3: decommission

**Input:** [events/decommission.json](events/decommission.json)

```json
{
  "request_id": "req-orders-decommission-001",
  "type": "db.postgres.decommission",
  "resource_id": "orders"
}
```

**Command:**

```bash
python -m orchestrator.trigger send events/decommission.json
```

**Output** (about 8 seconds):

```
started db.postgres.decommission for orders (request req-orders-decommission-001)
{
  "request_id": "req-orders-decommission-001",
  "event_type": "db.postgres.decommission",
  "resource_id": "orders",
  "status": "COMPLETED",
  "detail": "decommission applied and verified",
  "changed": true,
  "outputs": {}
}
```

**Check it yourself.** The container and its data volume are gone, so both lists are empty:

```bash
docker ps -a --filter name=pg-orders
```

```bash
docker volume ls --filter name=pg-orders
```

### What the cycle leaves behind

**In the worker terminal**, one line per request (the trailing Temporal context is shortened here):

```
INFO db.postgres.provision COMPLETED for orders: provision applied and verified (...)
INFO db.postgres.patch COMPLETED for orders: patch applied and verified (...)
INFO db.postgres.decommission COMPLETED for orders: decommission applied and verified (...)
```

**In `results/`**, one file per request, with the same JSON the trigger printed:

```
results/req-orders-provision-001.json
results/req-orders-patch-001.json
results/req-orders-decommission-001.json
```

**In the Temporal UI** (<http://localhost:8233>), three `LifecycleWorkflow` runs with status _Completed_. Open one to see its four activities in order: `validate_request`, `run_terraform`, `verify_resource`, `report_result`. The same list from the command line:

```bash
temporal workflow list
```

## 5. More scenarios: duplicates and failures

These are optional. They show the behaviour described in the design document. Each one states the point in the cycle where it should be run.

### The same event delivered twice

Run after step 1. Send the provision event again, unchanged:

```bash
python -m orchestrator.trigger send events/provision.json
```

```
duplicate: request req-orders-provision-001 was already submitted; nothing started. See: python -m orchestrator.trigger status req-orders-provision-001
```

Exit code `1`. No workflow was started, because the `request_id` is the workflow id and Temporal refuses an id it has already seen.

### The same request under a new request id

Run after step 1. `--request-id` overrides the id in the file:

```bash
python -m orchestrator.trigger send events/provision.json --request-id req-orders-provision-002
```

```
started db.postgres.provision for orders (request req-orders-provision-002)
{
  "request_id": "req-orders-provision-002",
  "event_type": "db.postgres.provision",
  "resource_id": "orders",
  "status": "COMPLETED",
  "detail": "provision needed no changes; current state verified",
  "changed": false,
  "outputs": { ... }
}
```

A workflow runs this time, but Terraform's plan is empty, so nothing is created twice. Note `"changed": false`. A repeated decommission behaves the same way (`decommission needed no changes; current state verified`).

### A request that is rejected (fails fast, no retry)

Run after step 2, while the database is at 16.4. [events/patch-downgrade.json](events/patch-downgrade.json) asks for `16.2`:

```bash
python -m orchestrator.trigger send events/patch-downgrade.json
```

```
started db.postgres.patch for orders (request req-orders-patch-downgrade-001)
FAILED: validate failed: patch cannot downgrade (16.4 -> 16.2)
```

Exit code `1`, within a couple of seconds. Nothing was changed. `results/req-orders-patch-downgrade-001.json` has `"status": "FAILED"`, and the Temporal UI shows the workflow as _Failed_.

### A partial failure: Terraform succeeds, verification fails

Run after step 2. [events/patch-verify-fails.json](events/patch-verify-fails.json) is a normal patch to `16.4` with one extra parameter, `"simulate_verify_failure": true`, which makes the verify step fail on purpose.

```bash
python -m orchestrator.trigger send events/patch-verify-fails.json
```

This takes **about 75 seconds**: the verify step is retried 8 times with growing waits before the workflow gives up. While it waits, look at the current step from a fourth terminal:

```bash
python -m orchestrator.trigger status req-orders-patch-verify-fails-001
```

```json
{
  "status": "RUNNING",
  "step": "verify",
  "detail": ""
}
```

Final output of the `send` command:

```
started db.postgres.patch for orders (request req-orders-patch-verify-fails-001)
VERIFICATION_FAILED: patch needed no changes but verification failed: simulated verification failure (simulate_verify_failure). The resource was left in place; resend the event with a new request id to verify again.
```

Exit code `1`. The status is `VERIFICATION_FAILED`, not `FAILED`, and the container is left running. If you run this event _instead of_ step 2 (while the database is still at 16.3), the patch is really applied first and the message starts with `patch was applied but verification failed`.

On both failure scenarios the worker terminal also prints a `WARNING Completing activity as failed` line with a Python traceback for each failed attempt. That is expected: it is the Temporal SDK logging the failed activity.

## 6. Command and event reference

### Commands

| Command                                                              | What it does                                                                                                          |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `temporal server start-dev`                                          | Starts the local Temporal server (port 7233) and UI (port 8233). History is kept in memory and is lost when it stops. |
| `python -m orchestrator.worker`                                      | Starts the worker that runs the workflow and its activities.                                                          |
| `python -m orchestrator.trigger send <event_file>`                   | Sends an event, waits for the workflow, prints the result.                                                            |
| `python -m orchestrator.trigger send <event_file> --request-id <id>` | Same, with the `request_id` in the file replaced.                                                                     |
| `python -m orchestrator.trigger status <request_id>`                 | Prints the status, current step and detail of a request.                                                              |

Exit codes of the trigger: `0` the workflow completed, `1` it failed or was a duplicate, `2` the event file is not a valid event.

### Event format

| Field            | Required                | Meaning                                                                                                            |
| ---------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `request_id`     | yes                     | Unique id of this request. Letters, digits, `.`, `_` and `-`. It becomes the workflow id and the result file name. |
| `type`           | yes                     | `<platform>.<action>`, for example `db.postgres.provision`. Actions: `provision`, `patch`, `decommission`.         |
| `resource_id`    | yes                     | Name of the instance. 1 to 40 lowercase letters, digits and hyphens. The container is called `pg-<resource_id>`.   |
| `params.version` | for provision and patch | Postgres version as `MAJOR.MINOR`, for example `16.3`. It must be a tag of the official `postgres` image.          |
| `params.env`     | no                      | A label recorded on the container. Defaults to `dev`.                                                              |

To manage a second database, copy an event file and change `resource_id` and `request_id`.

### Final statuses

| Status                | Meaning                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------- |
| `COMPLETED`           | The change was made (or was already in place) and the check passed.                       |
| `FAILED`              | Validation or Terraform failed.                                                           |
| `VERIFICATION_FAILED` | Terraform succeeded but the check afterwards did not pass. The resource is left in place. |

### Settings

| Environment variable | Default          | Meaning                                                    |
| -------------------- | ---------------- | ---------------------------------------------------------- |
| `TEMPORAL_ADDRESS`   | `localhost:7233` | Where the worker and the trigger find the Temporal server. |

## 7. Run the tests

With the virtual environment active:

```bash
pytest
```

Expected: `68 passed`. The tests do not need the Temporal server or the worker from section 3; workflow tests start Temporal's own test server (downloaded once, on the first run). `tests/workflows/test_pluggability.py` runs the real `terraform` CLI against a fake module, so Terraform must be installed.

Lint:

```bash
ruff check .
```

Expected: `All checks passed!`

## 8. Shut down and reset

1. Decommission anything you provisioned (step 3 of the demo).
2. Press `Ctrl+C` in the worker terminal, then in the Temporal terminal.

**To run the demo again**, restart both processes. The Temporal dev server keeps its history in memory, so after a restart the same `request_id`s can be used again. Without a restart, a repeated event file is reported as a duplicate; pass a new id with `--request-id`.

If a container was left behind (for example the worker was stopped mid-run), send the decommission event again with a new `--request-id`. As a last resort, remove it directly:

```bash
docker rm -f pg-orders
```

```bash
docker volume rm pg-orders-data
```

## 9. Troubleshooting

| Symptom                                                                                                                 | Cause and fix                                                                                                   |
| ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Trigger or worker stops with a connection error to `localhost:7233`                                                     | The Temporal server is not running. Start terminal 1.                                                           |
| `send` prints `started ...` and then nothing                                                                            | The worker is not running. Start terminal 2; the workflow continues by itself.                                  |
| `validate failed: [WinError 2] The system cannot find the file specified` (or `No such file or directory: 'terraform'`) | `terraform` is not on the `PATH` of the terminal that runs the worker. Fix the `PATH`, then restart the worker. |
| `terraform ... failed` mentioning the Docker daemon or `docker_engine`                                                  | Docker is not running. Start Docker Desktop and send the event again with a new `--request-id`.                 |
| `duplicate: request ... was already submitted`                                                                          | That `request_id` was already used since the Temporal server started. Use `--request-id <new id>`.              |
| `validate failed: orders already exists at version ...`                                                                 | A provision was sent for an instance that exists at another version. Send a patch, or decommission first.       |
| `validate failed: orders does not exist, so it cannot be patched`                                                       | Provision it first.                                                                                             |
| `ModuleNotFoundError: No module named 'orchestrator'`                                                                   | The virtual environment is not active in that terminal, or `pip install -e ".[dev]"` was not run.               |
| The first provision is slow                                                                                             | Terraform is downloading providers and Docker is pulling the Postgres image. Later runs take seconds.           |

## 10. Assumptions

- **Docker is the Terraform provider, not the `local` file provider.** A real container means the verify step connects to a real Postgres and can really fail. The cost is that Docker must be running.
- **Everything runs on one machine**: the Temporal dev server, one worker, Terraform and Docker. Terraform state is kept on local disk under `terraform/modules/postgres/terraform.tfstate.d/` and is not committed.
- **The worker runs `terraform init` itself**, so the reviewer starts the worker and sends events; no manual Terraform step is needed.
- **The event source sends a stable `request_id`.** A redelivered event carries the same id; a new request carries a new one.
- **A patch is a minor version bump within the same major version** (16.3 to 16.4). Downgrades and major upgrades are rejected. The container is replaced, so there is a short downtime.
- **A failed change is never rolled back automatically.** It is reported, and a person decides.
- **No secrets are in the repository.** Terraform generates the database password, and it lives only in the local Terraform state. It never enters Temporal history, the result files or the logs.
- **"Notification" is a log line and a file** in `results/`.
- **Human approval is designed but not built.** See section 6 of the design document.

The full list, with reasons, is in [docs/DESIGN.md](docs/DESIGN.md#2-assumptions-made).

## 11. Repository layout

```
events/                      Sample events, one JSON file per scenario
orchestrator/
  trigger.py                 CLI that sends an event and reads status
  worker.py                  Runs the worker
  workflow.py                LifecycleWorkflow: step order, retries, timeouts
  activities.py              validate, terraform, verify, report
  events.py, models.py       Event parsing and the data passed around
  platforms/                 Platform adapters (postgres.py) and the registry
  terraform/                 Terraform CLI runner and error classifier
terraform/modules/postgres/  The Terraform module (Docker container + volume)
tests/                       Unit tests and workflow tests
docs/DESIGN.md               Design document
results/                     Created at run time, one file per request (not committed)
```
