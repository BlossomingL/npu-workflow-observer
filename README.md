# NPU Workflow Observer MVP

Local-first observer for turning day-to-day NPU operator development into structured traces that can later be compiled into reusable workflows/agents.

## What this MVP captures

- Shell commands, exit codes, duration, cwd and command role (`build/test/benchmark/profile/remote`).
- Git repository, branch, commit, dirty state and optional diff.
- VSCode file-save events + Git diff.
- Explicit human `decision.created` events (the critical "why did I change this?" signal).
- Domain events such as `npu.test.*`, `npu.accuracy.*`, `npu.benchmark.*`.
- Automatic sessionization of events into a development task.
- Workflow mining into `workflow.generated.yaml`.

The daemon binds to `127.0.0.1` only. No cloud upload is implemented.

## Install

```bash
cd npu-workflow-observer
python -m venv .venv
source .venv/bin/activate
pip install -e . --no-build-isolation
```

## 1. Start the observer

```bash
npu-observer daemon
```

Default database:

```text
~/.npu-observer/observer.db
```

You can override it:

```bash
export NPU_OBSERVER_HOME=/path/to/private/storage
npu-observer daemon
```

## 2. Record commands

### Safest first step: explicit wrapper

```bash
npu-observer exec -- cmake --build build -j32
npu-observer exec -- ./run_test.sh --shape 2,32,4096,128
npu-observer exec -- nsys profile ./benchmark
```

The wrapper records start/end, return code, duration and Git context.

### Optional automatic Bash hook

```bash
source /path/to/npu-workflow-observer/scripts/bash_hook.sh
```

After validating it locally, add that line to `~/.bashrc`.

The hook records command metadata; it does **not** record raw keystrokes, clipboard or screenshots.

## 3. Record Git state

```bash
npu-observer git-snapshot
```

By default this includes the current working-tree diff. To record metadata only:

```bash
npu-observer git-snapshot --no-diff
```

## 4. Record an expert decision

This is intentionally first-class because action traces alone cannot teach an agent *why* an optimization was selected.

```bash
npu-observer decision \
  -m "increase tile_n from 128 to 256" \
  --reason "MTE-bound and Cube utilization is low" \
  --evidence "profile=run_20260917_01"
```

## 5. Emit NPU domain events

Adapters around your existing test/benchmark tools should emit semantic events, for example:

```bash
npu-observer event npu.test.started --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","shape":{"B":2,"N":32,"S":4096,"D":128},"dtype":"bf16","layout":"TND"}'

npu-observer event npu.accuracy.completed --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","cosine":0.99998,"max_abs":0.0021,"pass":true}'

npu-observer event npu.benchmark.completed --source adapter \
  --attributes '{"operator":"flash_attention_score_grad","latency_us":182.4,"mfu":0.831}'
```

See `examples/test_flow.sh`.

## 6. Build sessions

```bash
npu-observer sessionize --gap 45
```

Current MVP groups by repository/branch and splits sessions after 45 minutes of inactivity.

## 7. Mine a workflow

```bash
npu-observer mine \
  --min-support 0.5 \
  --name fa_grad_test \
  -o workflow.generated.yaml
```

Example output:

```yaml
name: fa_grad_test
version: 1
generated_from_sessions: 8
steps:
  - source_file_saved:
      tool: TODO
      observed: true
  - build:
      tool: TODO
      observed: true
  - npu_test_completed:
      tool: TODO
      observed: true
  - npu_benchmark_completed:
      tool: TODO
      observed: true
```

The first version deliberately leaves `tool: TODO`: workflow discovery and autonomous execution should remain separate until the observed sequence is reviewed and evaluated.

## VSCode extension

The extension records:

- `source.file.saved` with Git diff;
- `NPU Observer: Record Decision` from the Command Palette.

Build it with:

```bash
cd vscode-extension
npm install
npm run compile
```

Then launch it with VSCode Extension Development Host or package it as a VSIX using `@vscode/vsce`.

## Event model

Each record is roughly:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-09-17T16:00:00+08:00",
  "name": "npu.benchmark.completed",
  "kind": "event",
  "source": "adapter",
  "cwd": "/repo/ops-transformer",
  "attributes": {
    "operator": "flash_attention_score_grad",
    "shape": {"B": 2, "N": 32, "S": 4096, "D": 128},
    "latency_us": 182.4,
    "mfu": 0.831,
    "git": {"branch": "perf_d128", "commit": "..."}
  }
}
```

## Privacy defaults

The CLI redacts common token/password/API-key forms from commands and Git diffs. Recommended production hardening:

- keep the database on an encrypted local disk;
- add repository/path allowlists;
- store large logs/profiles in a content-addressed artifact store instead of the DB;
- never capture `~/.ssh`, credentials, clipboard or raw keystrokes;
- make source capture configurable (`metadata`, `git_diff`, `none`);
- require approval before generated workflows can modify source or execute on devices.

## Architecture

```text
Shell / Git / VSCode / Test adapters
             |
             v
      localhost JSONL
             |
             v
        observer daemon
             |
             v
          SQLite
             |
      +------+-------+
      |              |
 sessionizer     workflow miner
      |              |
      +-------> workflow.yaml
```

SQLite is used in this zero-friction MVP because it is in Python's standard library. The storage interface is intentionally small so it can be swapped to DuckDB later for larger analytical workloads.

## Next implementation milestones

1. Artifact store for stdout/stderr/profile files with SHA-256 URIs.
2. Native adapters for your build, board-runner, accuracy and profiler commands.
3. Shape parser for B/N/S/D/TND inputs and automatic association with subsequent runs.
4. Workflow branching (`accuracy_fail -> precision_debug`, `perf_regression -> profile`).
5. Shadow-mode predictor and eval metrics before autonomous execution.
6. Compiler from reviewed workflow YAML to an Agent Skill + tool wrappers + eval cases.
