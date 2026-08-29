from pathlib import Path
import unittest

import yaml

from src.python.calibration_config import load_calibration_settings
from src.python.time_windows import (
    normalize_simulation_tasks,
    normalize_simulation_time_config,
)


class TestConfigurationSamples(unittest.TestCase):
    def test_distributed_sandbox_configs_are_valid(self):
        sandbox_dir = Path(__file__).resolve().parents[1]

        for filename in (
            "sandbox_config.yaml",
            "sandbox_config_reference.yaml",
        ):
            with self.subTest(filename=filename):
                path = sandbox_dir / "configs" / filename
                with path.open("r") as file:
                    config = yaml.safe_load(file)

                self.assertIsInstance(config, dict)
                self.assertEqual(
                    set(config),
                    {
                        "general",
                        "subsetting",
                        "forcings",
                        "observations",
                        "calibration",
                        "formulations",
                        "simulation",
                    },
                )

                load_calibration_settings(config, path, sandbox_dir)
                tasks = normalize_simulation_tasks(config["simulation"])
                normalize_simulation_time_config(
                    config["simulation"],
                    tasks,
                    config_dir=path.parent,
                )


if __name__ == "__main__":
    unittest.main()
