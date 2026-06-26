## Sandbox Launcher for Large-Scale NextGen Experiments (HPC and Local)

Running large-scale NextGen experiments often involves 100s of gages, multiple hydrologic formulations, and long-running calibration cycles that must restart automatically 
due to HPC wallclock limits. The Sandbox Launcher provides a fully automated workflow for managing these experiments on high-performance computing (HPC) systems.

The launcher supports two execution backends:

- **SLURM (HPC mode)** – for large-scale distributed experiments with automatic requeue support.
- **Local mode** – for development, testing, and small-scale runs without a scheduler.

The launcher:

- Automatically generates per-gage and per-model configuration files
- Executes each gage–model experiment the selected backend (SLURM or local multiprocessing)
- Detects completed calibration iterations and resumes incomplete ones
- Organizes outputs into consistent, model-specific directory structures
- Supports flexible model–gage mapping through a YAML configuration file
- Handles validation runs with no additional user intervention
- Ensures reproducibility and reduces manual HPC job management


With a single command, the Sandbox Launcher orchestrates hundreds of experiments, making large-scale calibration and validation workflows efficient, automated, and repeatable.

## Setup
Before starting, copy the `$SANDBOX_DIR/tools/launcher` directory to your desired working location. The path to this directory (<path_to_launcher>) will be referenced in sandbox_launcher.py (see below).

- **Prepare the model–gage mapping file** \
  Create a YAML configuration file that maps models to gages (i.e., which model(s) runs at which location(s)). You can use the following as a template: [models_gages_map.yaml](https://github.com/ajkhattak/NextGenSandbox/blob/main/tools/launcher/models_gages_map.yaml)
- **Update base configuration files** \
  Modify the base configuration files located in the launcher directory:
   - launcher/basefiles/sandbox_config_base.yaml
   - launcher/basefiles/calib_config_base.yaml
- **Update SLURM scripts** \
  Adapt the SLURM submission scripts to your system:
   - [submit_gage.slurm](https://github.com/ajkhattak/NextGenSandbox/blob/main/tools/launcher/submit_gage.slurm)
   - [submit_launcher.slurm](https://github.com/ajkhattak/NextGenSandbox/blob/main/tools/launcher/submit_launcher.slurm)
- **Update paths inside sandbox_launcher.py** \
  Set the base directory path in `sandbox_launcher.py` to match your local filesystem (to point to your copied launcher directory):
  ```
  base_dir = "<path/to/copied/launcher>"
  ```

## Run
> **Important:** Run these commands from the <path_to_launcher> directory.
### On HPC (SLURM)
Submit the launcher job with:
```
sbatch launcher/submit_launcher.sh
```
### Locally (No SLURM)
Run directly:
```
bash launcher/submit_launcher.sh
```

### Check experiments status
Run:
```
./launcher/check_status.sh
```

> The launcher automatically detects whether it is running under SLURM and selects the appropriate execution backend.
> *NOTE*: The launcher assumes that all required basin geopackages and forcing data have already been downloaded.
