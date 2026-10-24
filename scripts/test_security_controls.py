"""Static security-release contracts. Standard library only; no application secrets or network."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityControls(unittest.TestCase):
    def test_reporting_and_dependency_config_are_tracked(self):
        self.assertIn("Reporting", (ROOT / "SECURITY.md").read_text())
        config = (ROOT / ".github/dependabot.yml").read_text()
        for ecosystem in ("npm", "pip", "github-actions", "docker"):
            self.assertIn(f"package-ecosystem: {ecosystem}", config)

    def test_workflow_preserves_required_checks_and_read_only_token(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for name in ("Backend", "Frontend"):
            self.assertIn(f"name: {name}", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("${{ secrets.", workflow)

    def test_audits_are_blocking_and_do_not_ignore_findings(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertNotRegex(workflow, r"(?m)^\s*continue-on-error:\s*true")
        self.assertNotIn("--ignore-vuln", workflow)
        self.assertNotIn("|| true", workflow)
        self.assertIn("npm audit --audit-level=high", workflow)
        self.assertIn("pip-audit==2.10.1", workflow)
        self.assertIn("--no-deps --disable-pip --strict", workflow)
        self.assertIn("python -m pip check", workflow)

    def test_frontend_tests_run_without_hiding_build_warnings(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("npm test -- --watchAll=false --runInBand", workflow)
        self.assertNotRegex(workflow, r"CI:\s*['\"]?false")

    def test_dependency_audit_scope_is_fully_pinned(self):
        requirements = (ROOT / "backend/requirements.txt").read_text().splitlines()
        for line in requirements:
            line = line.strip()
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+$")

    def test_register_distinguishes_proposal_from_main(self):
        register = (ROOT / "docs/security/SECURITY_CONTROL_REGISTER.md").read_text()
        self.assertIn("02bcc857", register)
        self.assertIn("NOT deployed", register)
        self.assertIn("Failed / blocked", register)
        self.assertIn("required approvals = 0", register)


if __name__ == "__main__":
    unittest.main()
