import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestSubsetFailureIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rscript = shutil.which("Rscript")
        cls.failures_r = (
            Path(__file__).resolve().parents[1] / "src" / "R" / "failures.R"
        )

    def run_r(self, expression: str, *args: Path) -> subprocess.CompletedProcess:
        if self.rscript is None:
            self.skipTest("Rscript is not available")

        return subprocess.run(
            [
                self.rscript,
                "-e",
                expression,
                str(self.failures_r),
                *(str(arg) for arg in args),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_cleanup_removes_only_selected_gage_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            first = input_dir / "failed_gages" / "01109403"
            second = input_dir / "failed_gages" / "02299950"
            first.mkdir(parents=True)
            second.mkdir()

            self.run_r(
                (
                    "args <- commandArgs(TRUE); source(args[[1]]); "
                    "clear_subset_failures(args[[2]], '01109403')"
                ),
                input_dir,
            )

            self.assertFalse(first.exists())
            self.assertTrue(second.exists())

    def test_failure_listing_includes_only_selected_gages(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            for gage_id in ("01109403", "02299950", "03366500"):
                (input_dir / "failed_gages" / gage_id).mkdir(
                    parents=True,
                    exist_ok=True,
                )

            result = self.run_r(
                (
                    "args <- commandArgs(TRUE); source(args[[1]]); "
                    "dirs <- subset_failure_dirs("
                    "args[[2]], c('01109403', '03366500')); "
                    "cat(paste(basename(dirs), collapse = ','))"
                ),
                input_dir,
            )

            self.assertEqual(result.stdout, "01109403,03366500")

    def test_unrelated_failure_does_not_fail_current_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            (input_dir / "failed_gages" / "02299950").mkdir(parents=True)

            result = self.run_r(
                (
                    "args <- commandArgs(TRUE); source(args[[1]]); "
                    "report_failed_gages(args[[2]], '01109403')"
                ),
                input_dir,
            )

            self.assertIn("All Gages Passed!!!", result.stdout)


if __name__ == "__main__":
    unittest.main()
