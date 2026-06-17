from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from ngen_cal_plugins.save_divide_output_plugin import SaveData


class TestSaveDivideOutput(unittest.TestCase):
    def test_all_retention_saves_every_iteration(self):
        plugin = SaveData()
        plugin.output_retention = "all"

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            info = SimpleNamespace(workdir=workdir)

            for iteration in range(2):
                (workdir / "cat-1.csv").write_text(f"iteration {iteration}")
                plugin.ngen_cal_model_iteration_finish(
                    iteration=iteration,
                    info=info,
                )

            self.assertEqual(
                (workdir / "output_0" / "cat-1.csv").read_text(),
                "iteration 0",
            )
            self.assertEqual(
                (workdir / "output_1" / "cat-1.csv").read_text(),
                "iteration 1",
            )

    def test_saves_only_outputs_from_best_iteration(self):
        plugin = SaveData()

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            info = SimpleNamespace(workdir=workdir)

            (workdir / "best_params.txt").write_text("0\n0\n1.0\n")
            (workdir / "cat-1.csv").write_text("iteration 0")
            plugin.ngen_cal_model_iteration_finish(iteration=0, info=info)

            (workdir / "best_params.txt").write_text("1\n0\n1.0\n")
            (workdir / "cat-1.csv").write_text("iteration 1")
            plugin.ngen_cal_model_iteration_finish(iteration=1, info=info)

            (workdir / "best_params.txt").write_text("2\n2\n0.5\n")
            (workdir / "cat-1.csv").write_text("iteration 2")
            plugin.ngen_cal_model_iteration_finish(iteration=2, info=info)

            self.assertEqual(
                (workdir / "output_best" / "cat-1.csv").read_text(),
                "iteration 2",
            )
            self.assertFalse((workdir / "cat-1.csv").exists())
            self.assertFalse((workdir / "output_1").exists())
            self.assertFalse((workdir / "output_2").exists())

    def test_preserves_iteration_when_best_params_is_unavailable(self):
        plugin = SaveData()

        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir)
            (workdir / "cat-1.csv").write_text("iteration 0")

            plugin.ngen_cal_model_iteration_finish(
                iteration=0,
                info=SimpleNamespace(workdir=workdir),
            )

            self.assertEqual(
                (workdir / "output_0" / "cat-1.csv").read_text(),
                "iteration 0",
            )


if __name__ == "__main__":
    unittest.main()
