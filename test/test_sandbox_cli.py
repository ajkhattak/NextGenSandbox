import io
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import sandbox


class TestSandboxCommandLine(unittest.TestCase):
    def test_missing_config_file_exits_with_command_line_error(self):
        missing_config = "/tmp/nextgensandbox-missing-config.yaml"
        stderr = io.StringIO()

        with patch.object(
            sys,
            "argv",
            ["sandbox", "--conf", "-i", missing_config],
        ), redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            sandbox.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            f"Sandbox config file does not exist: {missing_config}",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
