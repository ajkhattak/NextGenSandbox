from pathlib import Path
import unittest


class TestBuildSandboxScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.bootstrap = (cls.repo_root / "bootstrap.sh").read_text()
        cls.script = (
            cls.repo_root / "scripts" / "bootstrap" / "build_sandbox.sh"
        ).read_text()

    def test_bootstrap_uses_internal_script_directory(self):
        self.assertIn("./scripts/bootstrap/build_sandbox.sh", self.bootstrap)
        self.assertIn("./scripts/bootstrap/build_venv_subset.sh", self.bootstrap)
        self.assertIn("./scripts/bootstrap/build_models.sh", self.bootstrap)
        self.assertIn("./scripts/bootstrap/sandbox_env.sh", self.bootstrap)
        self.assertNotIn("./utils/build_sandbox.sh", self.bootstrap)
        self.assertNotIn("./utils/sandbox_env.sh", self.bootstrap)

    def test_environment_definitions_use_internal_script_directory(self):
        self.assertIn(
            "$SANDBOX_DIR/scripts/bootstrap/venv/venv_sandbox.yaml",
            self.script,
        )
        self.assertIn(
            "$SANDBOX_DIR/scripts/bootstrap/venv/venv_forcing.yaml",
            self.script,
        )

    def test_does_not_require_uv(self):
        self.assertNotIn("uv pip install", self.script)
        self.assertNotIn("pip install uv", self.script)

    def test_installs_with_target_environment_python(self):
        self.assertIn(
            '"$SANDBOX_PYTHON" -m pip install -e \'.[test]\'',
            self.script,
        )
        self.assertIn(
            '"$FORCING_ENV/bin/python" -m pip install',
            self.script,
        )


if __name__ == "__main__":
    unittest.main()
