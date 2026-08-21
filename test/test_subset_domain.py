import shutil
import subprocess
import unittest
from pathlib import Path


class TestSubsetDomain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rscript = shutil.which("Rscript")
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.config_r = cls.repo_root / "src" / "R" / "config.R"
        cls.nwis_r = cls.repo_root / "src" / "R" / "nwis.R"

    def run_r(self, expression: str, *paths: Path, check: bool = True):
        if self.rscript is None:
            self.skipTest("Rscript is not available")

        return subprocess.run(
            [
                self.rscript,
                "-e",
                expression,
                *(str(path) for path in paths),
            ],
            check=check,
            capture_output=True,
            text=True,
        )

    def test_domain_normalization_supports_expected_domains_and_aliases(self):
        result = self.run_r(
            (
                "args <- commandArgs(TRUE); source(args[[1]]); "
                "values <- c('CONUS', 'HI', 'ak', 'PR', 'vi', 'prvi'); "
                "cat(paste(vapply(values, normalize_gage_domain, character(1)), "
                "collapse = ','))"
            ),
            self.config_r,
        )

        self.assertEqual(result.stdout, "conus,hi,ak,prvi,prvi,prvi")

    def test_configured_domain_skips_usgs_lookup(self):
        result = self.run_r(
            (
                "args <- commandArgs(TRUE); source(args[[1]]); calls <- 0; "
                "get_gage_state_code <- function(gage_id) { "
                "calls <<- calls + 1; stop('lookup should not run') }; "
                "domain <- resolve_gage_domain('01308000', 'conus'); "
                "cat(domain, calls, sep = ',')"
            ),
            self.nwis_r,
        )

        self.assertEqual(result.stdout, "conus,0")

    def test_missing_domain_retains_state_lookup_fallback(self):
        result = self.run_r(
            (
                "args <- commandArgs(TRUE); source(args[[1]]); "
                "stateCd <- data.frame(STATE = c('15', '02', '72'), "
                "STUSAB = c('HI', 'AK', 'PR')); "
                "get_gage_state_code <- function(gage_id) '15'; "
                "cat(resolve_gage_domain('12345678'))"
            ),
            self.nwis_r,
        )

        self.assertEqual(result.stdout, "hi")

    def test_hydrofabric_211_is_rejected(self):
        result = self.run_r(
            (
                "args <- commandArgs(TRUE); source(args[[1]]); "
                "normalize_hydrofabric_version('2.1.1')"
            ),
            self.config_r,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("supports Hydrofabric 2.2 only", result.stderr)


if __name__ == "__main__":
    unittest.main()
