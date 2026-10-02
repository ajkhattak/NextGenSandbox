# Bootstrap Internals

These scripts and environment definitions implement the repository-level
`bootstrap.sh` commands. They are internal entry points and are not intended to
be run directly.

- `build_sandbox.sh` builds the Sandbox and forcing Python environments.
- `build_venv_subset.sh` builds the R subsetting environment.
- `build_models.sh` builds ngen and model libraries in the build directory,
  and builds t-route directly in `extern/t-route` into the active environment.
- `sandbox_env.sh` is the internal, non-persistent path initializer sourced
  by `configs/sandbox_profile.sh`.
- `venv/` contains the environment definitions and validation reference.

Users should copy and source `configs/sandbox_profile.sh`; the internal
scripts never modify shell startup files.

Use `./bootstrap.sh --help` from the repository root for supported setup
commands.
