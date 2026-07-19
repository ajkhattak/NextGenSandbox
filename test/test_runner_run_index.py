import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

import yaml

from src.python.runner import Runner


class TestRunnerRunIndex(unittest.TestCase):
    def test_write_run_index_records_named_validation_worker(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            worker_dir = output_dir / "202607180310_ngen_a83kd92p_worker"
            worker_dir.mkdir()

            runner = Runner(SimpleNamespace())
            runner.write_run_index(
                output_dir=output_dir,
                gage_id="01109403",
                mode="validation",
                name="water_year_split_wy2011",
                config_file=Path("configs/ngen-cal_valid_config_water_year_split_wy2011.yaml"),
                command="python validation.py -config configs/ngen-cal_valid_config_water_year_split_wy2011.yaml",
                simulation_time={
                    "start_time": "2010-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
                evaluation_time={
                    "start_time": "2011-10-01 00:00:00",
                    "end_time": "2012-09-30 23:00:00",
                },
                worker_dirs={worker_dir},
                returncode=0,
                status="completed",
            )

            index = yaml.safe_load((output_dir / "run_index.yml").read_text())

            self.assertEqual(len(index["runs"]), 1)
            self.assertEqual(index["runs"][0]["gage_id"], "01109403")
            self.assertEqual(index["runs"][0]["task_type"], "validation")
            self.assertEqual(index["runs"][0]["name"], "water_year_split_wy2011")
            self.assertEqual(index["runs"][0]["status"], "completed")
            self.assertEqual(index["runs"][0]["worker_dirs"], [str(worker_dir)])

    def test_safe_filename_removes_path_unfriendly_characters(self):
        self.assertEqual(
            Runner.safe_filename("validation 2011/2012"),
            "validation_2011_2012",
        )


if __name__ == "__main__":
    unittest.main()
