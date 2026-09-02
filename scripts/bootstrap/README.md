# Bootstrap Internals

These scripts and environment definitions implement the repository-level
`bootstrap.sh` commands. They are internal entry points and are not intended to
be run directly.

- `build_sandbox.sh` builds the Sandbox and forcing Python environments.
- `build_venv_subset.sh` builds the R subsetting environment.
- `build_models.sh` builds ngen, model libraries, and t-route.
- `sandbox_env.sh` configures and persists the repository environment paths.
- `venv/` contains the environment definitions and validation reference.

Use `./bootstrap.sh --help` from the repository root for supported setup
commands.
