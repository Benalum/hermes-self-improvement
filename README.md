# Hermes Self-Improvement Controller

Safety-gated autonomous self-improvement for Hermes Agent.

This repository contains a controller that evaluates a fixed Hermes baseline in an isolated Git worktree, gathers fresh evidence, uses a small local model for structured triage, optionally hands a bounded implementation task to a larger local model, and runs an independent candidate gate before any production change is even considered.

## Current status

Current controller line: **v3.19**.

The project is still in validation. The default promotion policy is intentionally:

```text
AUTO_PROMOTE_MODE=off
```

A successful research/implementation run does **not** imply that production will be modified.

## Core design

```text
scheduler
  -> exact-baseline isolated worktree
  -> controller-owned baseline validation
  -> bounded fresh candidate probe
  -> direct local structured triage (no tools)
  -> evidence-bound implementation plan
  -> Hermes implementation model, only when justified
  -> candidate manifest
  -> independent candidate gate
  -> syntax/tests/benchmark/security checks
  -> production verification / rollback controls
```

Key properties:

- exact Git baseline tracking
- isolated experiment worktrees
- hard wall-clock and turn budgets
- no tool access for the discovery/triage model
- bounded fresh-failure evidence
- test-tamper and dependency-change gates
- sensitive-component blocks
- production cleanliness/baseline checks
- fast-forward-only promotion path
- post-promotion health checks and rollback
- automatic promotion disabled by default

## Local models

The controller is designed around local Ollama-compatible models. The current validated split is:

- discovery/triage: `qwen3.5:4b-mlx`
- implementation/review: `gemma4:31b-mlx`

The direct discovery stage calls local Ollama structured inference and does not expose terminal, filesystem, Git, web, skills, or other Hermes tools.

## Tests

Run the controller acceptance suite with:

```bash
bash ./scripts/run_synthetic_tests.sh
```

The v3.19 release contains **104 controller regression tests** covering promotion policy, rollback, watchdogs, baseline handling, known-red behavior, structured triage, bounded probe rotation, evidence extraction, context ranking, and implementation gating.

The large v3.19 regression module is stored as ten line-boundary transport fragments because the connector used to seed this public repository could not upload the original local file directly. `tests/test_controller_v2.py` verifies the exact original byte length and SHA-256 before executing the concatenated source, so a missing or altered fragment fails closed.

## macOS installation

The installer targets an existing Hermes Agent installation and intentionally does **not** replace the canonical master prompt.

```bash
bash ./scripts/install_self_improvement_macos.sh
/opt/hermes-self-improvement/scripts/preflight_macos.sh
```

Do not enable automatic promotion until the controller has been validated on the target system and the baseline/update strategy is understood.

## Repository layout

```text
scripts/                 controller tools, gates, installer, and preflight
self-improvement/        runtime controller, policy defaults, architecture/history
tests/                   synthetic/regression test suite
.github/workflows/       public CI
```

## Public-repository safety

Do not commit:

- credentials, API keys, tokens, cookies, or private keys
- personal Hermes config files
- production reports containing sensitive data
- local worktrees, backups, caches, or model files
- brokerage credentials or trading-account data

See `SECURITY.md` and `.gitignore`.

## Future analytics integration

After the self-improvement controller is stable, it may be used to improve **market-analysis and research tooling** such as scanners, backtests, signal-quality analysis, regime detection, news interpretation, and trade-candidate ranking.

That downstream integration should remain separated from execution. Changes touching trading, brokers, wallets, payments, credentials, or order-routing are treated as sensitive/high-risk components and require explicit human review/authorization. The self-improvement controller should not silently grant itself the ability to place live trades.

The intended progression is:

```text
self-improvement controller stability
  -> market-data / analytics integration
  -> backtesting and paper-trading validation
  -> risk controls and auditability
  -> only then, separately reviewed execution integration
```

## Relationship to Hermes Agent

This repository is a controller around a Hermes Agent checkout; it is not the Hermes Agent source repository itself. Keep Hermes upstream migration work separate from controller validation so controller regressions are not confused with upstream changes.

## License

No license has been selected yet. Until one is added, normal copyright rules apply.
