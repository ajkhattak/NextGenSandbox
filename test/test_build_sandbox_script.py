from pathlib import Path
import unittest


class TestBuildSandboxScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (
            Path(__file__).resolve().parents[1]
            / "utils"
            / "build_sandbox.sh"
        ).read_text()

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
