# Hermes autonomous self-improvement controller v3.19

This bundle upgrades the controller without replacing the canonical master prompt at
`/opt/hermes-self-improvement/prompts/self_improvement.md`.

The v3.10 tool-free structured discovery architecture, v3.11 bounded multi-probe
rotation, v3.12 focused assertion evidence, and v3.13 complete function/helper recovery
are retained. v3.14 fixes evidence ranking exposed by the target-Mac
`search_messages` failure: production calls closest to the failing assertion now outrank
earlier setup calls, while the same three-definition context cap remains in force.

On a `KNOWN_RED` baseline the controller still tries at most
`FRESH_PROBE_MAX_ATTEMPTS=3` safe rotating test files within the shared
`FRESH_PROBE_TIMEOUT_SECONDS=45` wall-clock budget. Explicit missing-package failures
and stale failures that now pass can be skipped; ordinary failures remain candidates.


## v3.19: causal control-flow focus inside bounded source excerpts

v3.19 keeps the same three-definition evidence cap and all existing safety gates.
When an assertion term appears in both output/state assignments and an executable
control-flow guard, the guard now ranks first. This makes projection-style failures
show the line that decides whether work runs (for example ``"context" in
result_fields``) instead of spending both focused windows on later
``match["context"] = ...`` assignments. Membership expressions on continuation
lines receive the same bounded preference. No recursive source traversal is added.

## v3.18: patched-helper causal ranking inside the existing evidence cap

A real Mac v3.17 run selected
`tests/tools/test_file_tools.py::TestWriteFileHandler::test_writes_content`. The
failing test patched `_get_file_ops` and asserted that its `write_file` method was
called with `/tmp/out.txt`, but macOS execution passed `/private/tmp/out.txt`. The
controller correctly identified `_get_file_ops` as a candidate symbol, yet the
three bounded production-definition slots were consumed by `write_file_tool` and
unrelated early guard helpers before `_get_file_ops` could be shown. Qwen safely
returned `NO_CHANGE`.

v3.18 does not increase the three-definition cap. When expanding one hop from the
primary production function, a direct callee that is also explicitly referenced by
the failing test (for example through `@patch`) now outranks unrelated direct
callees. Patched helper names are also added as bounded focus terms inside the
primary function so the excerpt includes the exact mocked handoff/call site.

Traversal remains one hop only, production definitions remain capped at three,
`test_helpers` remain capped at two classifier-only records, and test files remain
invalid IMPLEMENT targets.


## v3.17: executable assertion evidence + local test helpers

A real Mac v3.16 run selected
`tests/run_agent/test_switch_model_reasoning_override.py::TestSwitchModelReasoningOverride::test_primary_runtime_includes_reasoning_config`.
The failure showed `agent._primary_runtime` was still a `MagicMock`, but the focused
source excerpt spent its `_primary_runtime` windows on an early docstring/comment and
omitted the later executable snapshot assignment. The failing test also called
`_make_fake_agent()`, whose local definition was outside the test excerpt, so Qwen could
not see that the fixture itself used a `MagicMock`. Qwen safely returned `NO_CHANGE`.

v3.17 keeps the same hard cap of three production definitions and the same roughly 7K
characters per production excerpt, but ranks executable assertion-term occurrences
ahead of comments/docstrings. Direct assignments and dictionary/subscript keys are
preferred, making state-setting lines such as `agent._primary_runtime = {...}` visible
when they exist.

The context packet may also include at most two bounded `test_helpers` definitions from
the selected test file when the failing test directly calls them. These helpers are
classifier-only evidence: they are kept separate from `source_definitions`, are never
valid IMPLEMENT file targets, and the existing test-tamper gate remains unchanged.


## v3.16: dependency warnings are environment evidence

The fresh probe now recognizes an explicit missing-package requirement even when provider code catches the underlying import failure and emits it as a warning before falling back to another transport. The classifier remains narrow: the text must contain a quoted package name, `package is required`, and an actual `pip install` instruction. Such attempts are marked `NON_ACTIONABLE_ENVIRONMENT` and rotation continues within the existing shared probe budget. Generic warnings are not skipped.

## v3.15: one-hop production-callee evidence

After selecting the highest-priority production behavior, the fresh-probe packet may use remaining slots in its existing three-definition cap for functions that behavior directly calls. Same-file/private helpers are preferred. Expansion is one hop only and never recursive.

## v3.14: failure-proximity source ranking

The target-Mac v3.13 live run selected
`tests/test_hermes_state.py::TestFTS5Search::test_search_projection_skips_context_enrichment_queries`.
The test called `search_messages(...)` immediately around the failing assertion, but the
three bounded production-definition slots were consumed first by earlier setup calls
(`create_session`, `append_message`, `_get_read_conn`). Qwen explicitly identified the
missing `search_messages` implementation and returned `NO_CHANGE`.

v3.14 ranks direct call candidates by their closest source-line distance to the failing
assertion. Local helper functions remain excluded, common builtins/string helpers are
filtered, and explicitly patched production helpers are retained after direct behavior
candidates. The controller does **not** increase the three-definition cap or expose any
new tools to Qwen.

This means the behavior under test is much less likely to be crowded out by fixture/setup
code while context size and autonomous scope remain bounded.

## v3.13: complete bounded function bodies + patched-helper evidence

The target-Mac v3.12 live run selected
`tests/tools/test_file_tools.py::TestWriteFileHandler::test_writes_content`, where the
test expected `/tmp/out.txt` but the mocked production call received
`/private/tmp/out.txt`. The packet contained only the first two signature lines of
`write_file_tool()` and omitted the test-patched `_get_file_ops` helper. Qwen therefore
returned `NO_CHANGE` rather than infer where normalization occurred.

The root cause was in the controller fallback parser: when whole-file AST parsing was
unavailable, a multi-line `def` header whose closing `)` aligned with `def` could be
misread as a dedent. v3.13 first locates the complete function header, then begins
dedent detection after it. The bounded excerpt therefore includes the actual body.

Tests also commonly reference production helpers only through `@patch("pkg.mod._helper")`
or `setattr` strings. v3.13 extracts the final identifier from those narrowly-scoped
patch targets and may include that helper as additional production evidence. Source
context remains bounded to at most three tracked non-test definitions and roughly 7K
characters per definition.

## v3.12 retained: focused assertion-to-source context

For the selected failure, `fresh_probe.py` now extracts two kinds of evidence from the
failing test:

- candidate call symbols used to locate matching production definitions;
- bounded assertion-derived `evidence_terms`, such as attribute names or identifier-like
  dictionary/string keys (`_primary_runtime`, `reasoning_config`).

The production packet includes the definition start plus focused windows around those
terms inside the matched definition. This avoids the v3.11 failure mode where a long
function's relevant assignment existed well below the initial source excerpt. Context remains bounded to tracked non-test production definitions and roughly 7K
characters per definition; v3.13 raises the definition cap from two to three only so a
patched helper can accompany the public function under test.

Definition bounds use normal AST information when available and a conservative lexical
indentation fallback when whole-file parsing fails because the checked-out source uses
newer Python syntax than the controller interpreter.

## Selected-only direct classifier handoff

The report still records all bounded probe attempts for auditability. Qwen does not see
that entire history once an actionable candidate has been selected. The controller
derives a selected-only triage payload containing the current target, fresh failure
output, context packet, timing, and rotation metadata. Earlier skipped dependency-only
attempts are intentionally excluded so they cannot bias root-cause classification of
the current candidate.

`NO_ACTIONABLE_FAILURE` remains an exception: its bounded-attempt summary is passed to
Qwen so it can return `NO_CHANGE`, and the independent plan validator still prevents
that evidence from authorizing `IMPLEMENT`.

## Direct structured discovery

The discovery stage is not a Hermes Agent session. The controller sends the selected
fresh-evidence packet directly to the local Ollama `/api/chat` endpoint and requires an
exact JSON-schema response from `qwen3.5:4b-mlx`.

- No Hermes `chat` process is started for discovery.
- No terminal, web, skills, Git, filesystem, or other tools are exposed to Qwen.
- Ollama structured output constrains the response to the eight triage handoff fields.
- Qwen thinking is disabled (`think=false`), temperature is 0, and the endpoint is
  restricted to loopback/local Ollama.
- The direct classifier is wall-clock bounded by `DISCOVERY_RUNTIME_SECONDS`.
- `MAX_TURNS` is reserved for the Gemma implementation stage.

## Evidence-bound IMPLEMENT decisions

A syntactically valid `IMPLEMENT` response is not enough to start Gemma. The
independent triage-plan validator also requires a fresh failing controller probe, at
least one production source definition, proposed source paths grounded in those
definitions, and the exact fresh pytest node/target in `targeted_tests`.

A hallucinated unrelated file or test therefore fails closed before the implementation
agent is created.

## Implementation stage

Only a controller-validated `IMPLEMENT` handoff can enter the experiment worktree,
install the agent-phase guard, and start `gemma4:31b-mlx` through Hermes. Gemma gets
the full configured turn budget and the remaining wall-clock budget. It remains
limited to the selected candidate, targeted tests, and the existing independent
candidate gate.

## Known-red production rule

`KNOWN_RED` research remains allowed only when `AUTO_PROMOTE_MODE=off`. Even a
non-regressing validated candidate can receive only
`VALIDATED_RESEARCH_ONLY_BASELINE_RED`; production promotion remains forbidden until
the unchanged baseline is green.

## Existing safeguards retained

- exact production-baseline Git worktrees;
- automatic promotion defaults OFF;
- wall-clock watchdog plus TERM/INT/HUP child-group cleanup;
- orphan self-improvement Hermes-chat startup gate;
- environment/baseline fail-stop;
- sensitive/dependency/test-tamper/size/syntax gates;
- Hermes `scripts/run_tests.sh` differential validation for known-red candidates;
- production clean/baseline checks, backup, fast-forward-only promotion, post-health,
  and rollback;
- concise temporary `.hermes.md`, anti-recursion rules, and bounded source context;
- local model/context preflight checks (minimum 64K).

Do not enable production promotion during controller validation, and do not blindly
run `hermes update` on the carried local production branch.
