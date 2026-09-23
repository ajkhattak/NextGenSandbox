from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


class TestBuildSandboxScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.bootstrap = (cls.repo_root / "bootstrap.sh").read_text()
        cls.script = (
            cls.repo_root / "scripts" / "bootstrap" / "build_sandbox.sh"
        ).read_text()
        cls.model_script = (
            cls.repo_root / "scripts" / "bootstrap" / "build_models.sh"
        ).read_text()
        cls.subset_script = (
            cls.repo_root / "scripts" / "bootstrap" / "build_venv_subset.sh"
        ).read_text()
        cls.subset_environment = (
            cls.repo_root / "scripts" / "bootstrap" / "venv" / "venv_subset.yaml"
        ).read_text()
        cls.subset_linux_lock = (
            cls.repo_root
            / "scripts"
            / "bootstrap"
            / "venv"
            / "venv_subset.linux-64.lock"
        ).read_text()
        cls.profile = (cls.repo_root / "configs" / "sandbox_profile.sh").read_text()

    def test_bootstrap_uses_internal_script_directory(self):
        self.assertIn("./scripts/bootstrap/build_sandbox.sh", self.bootstrap)
        self.assertIn("./scripts/bootstrap/build_venv_subset.sh", self.bootstrap)
        self.assertIn("./scripts/bootstrap/build_models.sh", self.bootstrap)
        self.assertNotIn("--env", self.bootstrap)
        self.assertIn(
            "cp configs/sandbox_profile.sh sandbox_profile.sh",
            self.bootstrap,
        )
        self.assertNotIn("./utils/build_sandbox.sh", self.bootstrap)
        self.assertNotIn("./utils/sandbox_env.sh", self.bootstrap)

    def test_removed_environment_option_is_rejected(self):
        result = subprocess.run(
            [str(self.repo_root / "bootstrap.sh"), "--env"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Unknown option: --env", result.stdout)

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

    def test_build_parallelism_uses_profile_setting(self):
        self.assertIn(
            'export SANDBOX_BUILD_JOBS="${SANDBOX_BUILD_JOBS:-2}"',
            self.profile,
        )
        self.assertIn('BUILD_JOBS=${SANDBOX_BUILD_JOBS:-2}', self.model_script)
        self.assertEqual(
            self.model_script.count('--parallel "$BUILD_JOBS"'),
            2,
        )

    def test_profile_exposes_sandbox_shared_libraries_on_linux(self):
        self.assertIn(
            'export LD_LIBRARY_PATH="$SANDBOX_ENV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"',
            self.profile,
        )
        self.assertIn(
            'export LIBRARY_PATH="$SANDBOX_ENV/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"',
            self.profile,
        )

    def test_subset_uses_binary_rann_dependency(self):
        self.assertIn("  - r-rann", self.subset_environment)
        self.assertIn("requireNamespace(\"RANN\"", self.subset_script)
        self.assertIn("-c conda-forge r-rann", self.subset_script)
        self.assertIn("# platform: linux-64", self.subset_linux_lock)
        self.assertIn("/r-rann-", self.subset_linux_lock)

    def test_subset_validates_platform_specific_lockfile(self):
        self.assertIn(
            'if ! lockfile_matches_platform "$LOCKFILE"',
            self.subset_script,
        )
        self.assertIn("GENERATE_LOCKFILE=true", self.subset_script)

    def test_installs_with_target_environment_python(self):
        self.assertIn(
            '"$SANDBOX_PYTHON" -m pip install -e \'.[test]\'',
            self.script,
        )
        self.assertIn(
            '"$FORCING_ENV/bin/python" -m pip install',
            self.script,
        )

    def test_rejects_rebuilding_active_virtual_environment(self):
        self.assertIn(
            'same_directory "$ACTIVE_PYTHON_ENV" "$SANDBOX_ENV"',
            self.script,
        )
        self.assertIn(
            "Deactivate it before rebuilding it:",
            self.script,
        )

    def test_finds_module_conda_through_conda_exe(self):
        self.assertIn('if [ -n "${CONDA_EXE:-}" ]', self.script)
        self.assertIn(
            'eval "$("$CONDA_EXE_PATH" shell.bash hook)"',
            self.script,
        )
        self.assertIn('CONDA_AVAILABLE=ON', self.script)
        self.assertIn(
            'status_ok "conda: $CONDA_EXE (from CONDA_EXE)"',
            self.bootstrap,
        )

    def test_ignores_unrelated_build_environment_variable(self):
        self.assertNotIn("BUILD_SANDBOX=${BUILD:-ON}", self.script)
        self.assertIn(
            "BUILD_SANDBOX=${BUILD_SANDBOX:-ON}",
            self.script,
        )

    def test_internal_environment_load_does_not_edit_shell_startup(self):
        environment_script = (
            self.repo_root / "scripts" / "bootstrap" / "sandbox_env.sh"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(root / "home"),
                    "SHELL": "/bin/bash",
                    "SANDBOX_BUILD_DIR": str(root / "build"),
                    "SANDBOX_DATA_DIR": str(root / "data"),
                    "SANDBOX_CONDARC": str(root / "build" / "condarc"),
                }
            )
            (root / "home").mkdir()

            subprocess.run(
                [
                    "bash",
                    "-c",
                    f'set -u; source "{environment_script}"',
                ],
                check=True,
                env=env,
            )

            self.assertFalse((root / "home" / ".bashrc").exists())

    def test_profile_loads_from_repository_root_in_bash_and_zsh(self):
        profile_template = (
            self.repo_root / "configs" / "sandbox_profile.sh"
        )
        environment_script = (
            self.repo_root / "scripts" / "bootstrap" / "sandbox_env.sh"
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "NextGenSandbox"
            (root / "scripts" / "bootstrap").mkdir(parents=True)
            root = root.resolve()
            shutil.copy2(profile_template, root / "sandbox_profile.sh")
            shutil.copy2(
                environment_script,
                root / "scripts" / "bootstrap" / "sandbox_env.sh",
            )
            wrapper_dir = root / "wrappers"
            wrapper_dir.mkdir()
            for name in ("mpicc", "mpicxx", "mpifort"):
                wrapper = wrapper_dir / name
                wrapper.write_text("#!/usr/bin/env sh\nexit 0\n")
                wrapper.chmod(0o755)

            for shell in ("bash", "zsh"):
                executable = shutil.which(shell)
                if executable is None:
                    continue
                with self.subTest(shell=shell):
                    env = os.environ.copy()
                    for name in (
                        "SANDBOX_REPO",
                        "SANDBOX_DIR",
                        "SANDBOX_BUILD_DIR",
                        "SANDBOX_DATA_DIR",
                        "SANDBOX_CONDARC",
                        "SANDBOX_PROFILE",
                    ):
                        env.pop(name, None)
                    env["PATH"] = f"{wrapper_dir}{os.pathsep}{env['PATH']}"
                    env["CC"] = "/unrelated/cc"
                    env["CXX"] = "/unrelated/cxx"
                    env["FC"] = "/unrelated/fc"

                    subprocess.run(
                        [
                            executable,
                            "-c",
                            (
                                'source "$1" >/dev/null; '
                                'test "$SANDBOX_DIR" = "$2"; '
                                'test "$SANDBOX_PROFILE" = "$1"; '
                                'test ! -e "$SANDBOX_BUILD_DIR"; '
                                'test ! -e "$SANDBOX_DATA_DIR"; '
                                'test "$CC" = "$3/mpicc"; '
                                'test "$CXX" = "$3/mpicxx"; '
                                'test "$FC" = "$3/mpifort"; '
                                'test "$F90" = "$FC"'
                            ),
                            "_",
                            str(root / "sandbox_profile.sh"),
                            str(root),
                            str(wrapper_dir),
                        ],
                        check=True,
                        env=env,
                    )


if __name__ == "__main__":
    unittest.main()
