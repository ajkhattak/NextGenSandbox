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

## Preview Documentation Locally

Documentation contributors can preview the published site without changing the
Sandbox environments:

```bash
python -m venv .venv-docs
source .venv-docs/bin/activate
python -m pip install -r docs/requirements.txt
mkdocs serve
```

Open `http://127.0.0.1:8000` in a browser. MkDocs rebuilds the preview when a
documentation file changes. Run the same strict build used by GitHub Actions
before submitting documentation changes:

```bash
mkdocs build
```

The generated `site/` directory is ignored by Git.
