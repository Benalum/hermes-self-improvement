# Security Policy

This project controls an autonomous code-modification workflow. Treat changes to its safety gates as security-sensitive.

## Do not commit secrets

Never commit API keys, access tokens, cookies, private keys, brokerage credentials, personal Hermes configuration, production logs containing private data, or model-provider credentials.

## High-risk components

Changes involving authentication, credentials, SSH, firewalls, launch/system services, installers/updaters, payments, trading, brokers, wallets, or other execution/financial controls require explicit human review. The controller's default policy blocks or escalates these areas rather than autonomously promoting them.

## Production safety

- Keep `AUTO_PROMOTE_MODE=off` during validation.
- Run experiments in isolated Git worktrees.
- Require an exact known production baseline before promotion.
- Preserve candidate manifests and independent gate results.
- Do not weaken test-tamper, dependency-change, sensitive-path, or rollback checks to make a candidate pass.
- Do not expose local model endpoints beyond loopback merely for convenience.

## Trading/financial integrations

Future market-analysis integrations should keep research, backtesting, paper trading, and live execution as separate trust zones. Live order routing, account credentials, broker APIs, leverage/margin controls, and capital allocation must not become implicit self-improvement permissions.

## Reporting a vulnerability

For now, use a GitHub issue only for non-sensitive reports. Do not paste secrets, credentials, private logs, or exploitable production details into a public issue. For sensitive reports, contact the repository owner privately through an appropriate channel.
