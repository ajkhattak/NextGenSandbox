# Test NextGenSandbox Changes

These tests are intended for contributors and developers. A user installing
NextGenSandbox only needs the installation check and workflow smoke test in
[install.md](./install.md).

Activate the Sandbox Python environment before running the test suites:

```bash
conda activate "$SANDBOX_ENV"
```

or:

```bash
source "$SANDBOX_ENV/bin/activate"
```

Run the NextGenSandbox tests:

```bash
python -m pytest test
```

Run the local ngen-cal plugin tests:

```bash
python -m pytest plugins/ngen_cal_plugins/tests
```

Run the upstream ngen-cal tests when its submodule is initialized:

```bash
python -m pytest extern/ngen-cal/python/ngen_cal/tests
```

The standard Sandbox build installs the `test` dependency extra, including
`pytest` and `pytest-mock`.
