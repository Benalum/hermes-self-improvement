import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "self-improvement" / "run_daily_improvement.sh"
CONTEXT = ROOT / "self-improvement" / "hermes-worktree-context.md"
INSTALLER = ROOT / "scripts" / "install_self_improvement_macos.sh"


class SelfImprovementRunnerTests(unittest.TestCase):
    def test_context_is_concise(self):
        text = CONTEXT.read_text()
        self.assertLess(len(text), 20_000)
        self.assertIn("AGENTS.md", text)
        self.assertIn("NO PRODUCTION CHANGE TODAY", text)
        self.assertIn("Do not commit this `.hermes.md`", text)

    def test_runner_uses_exact_baseline_worktree(self):
        text = RUNNER.read_text()
        self.assertIn('BASELINE_COMMIT="$(git -C "$HERMES_ROOT" rev-parse HEAD)"', text)
        self.assertRegex(text, r'git -C "\$HERMES_ROOT" worktree add')
        self.assertIn('"$BASELINE_COMMIT"', text)

    def test_runner_injects_and_removes_ephemeral_context(self):
        text = RUNNER.read_text()
        self.assertIn('EPHEMERAL_CONTEXT="$WORKTREE/.hermes.md"', text)
        self.assertIn('cp "$CONTEXT_TEMPLATE" "$EPHEMERAL_CONTEXT"', text)
        remove_pos = text.index('rm -f "$EPHEMERAL_CONTEXT"')
        status_pos = text.index('git -C "$WORKTREE" status --short')
        self.assertLess(remove_pos, status_pos)

    def test_runner_uses_proven_cli_shape(self):
        text = RUNNER.read_text()
        self.assertIn('"$HERMES_PY" -m hermes_cli.main chat', text)
        self.assertIn('--toolsets web,terminal,skills', text)
        self.assertIn('TRIAGE_INFER_TOOL', text)
        self.assertIn('direct local Ollama /api/chat; JSON schema; no tools', text)
        self.assertNotIn('TRIAGE_ARGS=(chat', text)
        self.assertIn('-q "$IMPLEMENTATION_TASK"', text)

    def test_runner_does_not_auto_merge_or_update(self):
        text = RUNNER.read_text()
        forbidden = [
            "git merge",
            "git rebase",
            "git push",
            "hermes update\n",
            "update --install",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, text)

    def test_installer_preserves_master_prompt(self):
        text = INSTALLER.read_text()
        self.assertIn("intentionally does not replace your master prompt", text)
        self.assertIn("backups", text.lower())


if __name__ == "__main__":
    unittest.main()
