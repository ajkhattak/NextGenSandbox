## Validation

Validate each step before proceeding to the next one. If a step is not configured correctly, subsequent build steps will likely fail.

### Step 1.3 Validation

Run:

```bash
./bootstrap.sh --env --verbose
```

#### First-Time Setup

If this is the first time configuring the sandbox environment, you should see output similar to:

```text
=========================================
Configuration:
  ENV      : ON
  SANDBOX  : OFF
  SUBSET   : OFF
  NGEN     : OFF
  MODELS   : OFF
  TROUTE   : OFF
=========================================

Adding sandbox environment to:
    $HOME/.zshrc

Shell configuration updated successfully.

IMPORTANT:
The sandbox environment will be loaded automatically for future terminal sessions.

To use the environment in the current terminal, either:

  source $HOME/.zshrc

or open a new terminal window.

Sandbox environment successfully configured, but not loaded yet

  source $HOME/.zshrc
```

Afterward, reload your shell or open a new terminal before proceeding:

```bash
source ~/.zshrc
```

#### Subsequent Runs

After the environment has already been configured and loaded, you should see output similar to:

```text
=========================================
Configuration:
  ENV      : ON
  SANDBOX  : OFF
  SUBSET   : OFF
  NGEN     : OFF
  MODELS   : OFF
  TROUTE   : OFF
=========================================

Sandbox environment already loaded.

SANDBOX_DIR        : <path_to_sandbox_repo>/NextGenSandbox
SANDBOX_BUILD_DIR  : <path_to_sandbox_repo>/NextGenSandbox/build
SANDBOX_DATA_DIR   : <path_to_sandbox_repo>/NextGenSandbox/data
SANDBOX_CONDARC    : <path_to_sandbox_repo>/NextGenSandbox/build/condarc
NGEN_DIR           : <path_to_sandbox_repo>/NextGenSandbox/build/ngen
SANDBOX_ENV        : <path_to_sandbox_repo>/NextGenSandbox/build/venv/sandbox
FORCING_ENV        : <path_to_sandbox_repo>/NextGenSandbox/build/venv/forcing
```

Verify that all environment variables are defined and point to the expected directories before continuing to the next step.

### Bootstrap Check

Run:

```bash
./bootstrap.sh --check
```

This command is safe to run at any time. It does not install packages or create
directories. It reports:

- Sandbox path variables and whether the directories exist
- shell startup registration for `scripts/bootstrap/sandbox_env.sh`
- system tools such as `git`, Python, conda/mamba, and Rscript
- Sandbox, forcing, and subset environments
- key Python imports such as `ngen.cal`, `ngen.config`, and `nwm_routing`
- key R packages used by the subset workflow
- ngen executable and git submodule status

Use missing or warning lines as the next setup step to fix. For example, a
missing Sandbox Python environment means `./bootstrap.sh --sandbox` has not
completed, while a missing subset R environment means `./bootstrap.sh --subset`
has not completed.

Recommended times to run it:

- after `./bootstrap.sh --env --verbose`, especially in a new terminal
- after `./bootstrap.sh --sandbox`
- after `./bootstrap.sh --subset`
- after `./bootstrap.sh --ngen --models --troute`
- whenever a Sandbox command fails and the cause is unclear

Experienced users can run it once at the end of setup, but running it between
major steps makes installation problems easier to localize.


### Step 1.4 Validation

Activate the Sandbox Python environment:

```bash
conda activate $SANDBOX_ENV
```

Verify that the `sandbox` command points to the Sandbox virtual environment

```
which sandbox
```

Expected output:

```text
<path_to_sandbox_repo>/NextGenSandbox/build/venv/sandbox/bin/sandbox
```

If `which sandbox` points to a different location (for example, `/usr/local/bin/sandbox`) or returns no result, the Sandbox environment is not activated correctly. Verify that Step 1.3 completed successfully and that the correct environment is active before proceeding.
