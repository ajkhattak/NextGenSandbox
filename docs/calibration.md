# Calibration Configuration

This guide explains `configs/calib_config.yaml`, model calibration parameter
files under `configs/calibration/`, and calibration output settings.

## `configs/calib_config.yaml`

The top-level calibration config controls how ngen-cal searches parameters,
which model is evaluated, and which plugins are enabled.

```yaml
general:
  strategy:
    type: estimation
    algorithm: dds
  log: true
  start_iteration: 0
  iterations: 40
  random_seed: 444
  workdir: ./

calibration:
  params_dir: calibration

model:
  type: ngen
  binary: <*>
  realization: <*>
  hydrofabric: <*>
  eval_feature: <*>
  strategy: uniform
  params: <*>
  eval_params:
    objective: kling_gupta
    target: min
  plugins:
    - ngen_cal_plugins.save_divide_output_plugin.SaveData
    - ngen_cal_plugins.save_sim_obs_plugin.SaveData
    - ngen_cal_plugins.metrics.ComputeMetrics
```

The sandbox fills `<*>` values when it writes each run's
`ngen-cal_calib_config.yaml`.

## Main Fields

| Field | Meaning |
|---|---|
| `general.strategy.type` | ngen-cal strategy type, usually `estimation`. |
| `general.strategy.algorithm` | Search algorithm, such as `dds` or `pso`. |
| `general.strategy.parameters` | Optional algorithm-specific settings. PSO uses this block; DDS usually does not. |
| `general.log` | Enables ngen-cal logging. |
| `general.start_iteration` | First calibration iteration. |
| `general.iterations` | Number of calibration iterations or generations. |
| `general.random_seed` | Random seed for reproducibility. |
| `general.workdir` | ngen-cal working directory. Usually left as `./`. |
| `calibration.params_dir` | Directory under `configs/` containing model calibration parameter files. |
| `model.type` | Model type passed to ngen-cal, usually `ngen`. |
| `model.binary` | Filled by the sandbox with the ngen executable path. |
| `model.realization` | Filled by the sandbox with the realization file. |
| `model.hydrofabric` | Filled by the sandbox with the basin geopackage. |
| `model.eval_feature` | Filled by the sandbox with the target gage/nexus feature. |
| `model.strategy` | ngen-cal parameter strategy, commonly `uniform`. |
| `model.params` | Filled by the sandbox from model calibration parameter blocks. |
| `model.eval_params.objective` | Objective function name or import path. |
| `model.eval_params.target` | Optimization target, usually `min`. |
| `model.plugins` | ngen-cal plugin classes to load. |
| `model.plugin_settings` | Optional plugin-specific settings written by the sandbox when needed. |

## PSO Parameters

Set `algorithm: pso` to use particle swarm optimization. PSO currently supports
the `uniform` model strategy, where one shared parameter set is calibrated for
the basin.

```yaml
general:
  strategy:
    type: estimation
    algorithm: pso
    parameters:
      particles: 20
      pool: 4
      options:
        c1: 1.5
        c2: 2.0
        w: 0.9
      options_schedule:
        type: linear
        end:
          c1: 0.5
          c2: 2.5
          w: 0.4
      initialization:
        best_path: /path/to/previous/pso_global_best
        nearby_fraction: 0.5
        noise_fraction: 0.1
      particle_reset:
        enabled: true
        patience: 10
        reset_fraction: 1.0
        preserve_global_best: true
```

`particles` is the number of candidate parameter sets evaluated each PSO
generation. Each particle owns an isolated ngen-cal worker directory and runs
one ngen simulation per generation.

`pool` is the maximum number of particle simulations run concurrently. If ngen
itself uses MPI parallelism, approximate CPU demand is `pool * ngen_parallel`.

`options` are the starting PSO coefficients:

- `w`: inertia weight, controlling momentum from the previous velocity.
- `c1`: cognitive coefficient, pulling particles toward their own best known
  position.
- `c2`: social coefficient, pulling particles toward the global best known
  position.

`options_schedule` is optional. With `type: linear`, the listed coefficients
linearly move from their starting values in `options` to the values in `end`
over the PSO iterations:

```text
factor = iteration / total_iterations
value = start - factor * (start - end)
```

The schedule is recorded in `pso_options_log.txt`.

`initialization` is optional. When `best_path` points to a previous DDS worker,
PSO reads `best_params.txt` and `*_parameter_df_state.parquet` and uses that
best parameter set as particle 0. When `best_path` points to a previous
`pso_global_best` directory, PSO can use its saved best parameter state. If
`best_path` is omitted or cannot be read, particle 0 uses the `init` values
from the calibration parameter blocks.

`nearby_fraction` controls how many particles are initialized near the seed.
`noise_fraction` controls the standard deviation of the perturbation as a
fraction of each parameter range. Remaining particles are initialized randomly
within bounds.

`particle_reset` is optional and is disabled when omitted. It can reinitialize
particles whose personal-best cost has not improved for `patience` consecutive
generations:

- `enabled`: enables or disables particle reset.
- `patience`: number of consecutive generations without a personal-best
  improvement before a particle becomes eligible. The default is `10`.
- `reset_fraction`: fraction of the eligible stagnant particles to reset. The
  default `1.0` resets all eligible particles, not the entire swarm. When less
  than `1.0`, particles with the worst personal-best costs are reset first.
- `preserve_global_best`: excludes the current global-best particle from reset.
  The default is `true`.

Reset particles receive a new random position within the parameter bounds,
zero velocity, and a cleared personal-best cost. The swarm's global best is
retained. Each reset is recorded in `pso_particle_reset_log.txt`, including the
generation, particle index, previous personal-best cost, and new position.

PSO writes several progress artifacts in the run directory:

- `pso_progress.json`: current global best and the latest generation's particle
  results.
- `pso_global_best/`: copy of the particle worker that produced the best result.
- `pso_global_best_log.txt`: best-so-far score/cost after each generation.
- `pso_options_log.txt`: scheduled `w`, `c1`, and `c2` values by generation.
- `pso_particle_reset_log.txt`: particles reinitialized after personal-best
  stagnation. This file is created only when a reset occurs.

## Model Calibration Parameter Files

The calibration parameter files live under the directory configured by
`calibration.params_dir` in `configs/calib_config.yaml`.

With the default layout, those files live under:

```text
configs/calibration/
```

Each file contains one or more named parameter blocks. A model instance points
to a block using `calib_params_block`.

```yaml
formulation:
  model_instances:
    CFE:
      - name: cfe-x
        calib_params_block: "cfex_params"
```

That block must exist in one of the files under `configs/calibration/`:

```yaml
cfex_params:
  - name: b
    min: 0.0
    max: 15
    init: 4.05
```

Parameters use a linear calibration scale by default. Keep `min`, `max`, and
`init` in the physical/model units expected by the model. To search a parameter
in base-10 logarithmic space, set `scale: log10`; Sandbox converts those
physical values to log10 space before writing the generated ngen-cal config.
ngen-cal then converts sampled values back to physical space before writing the
ngen realization:

```yaml
cfes_params:
  - name: Cgw
    scale: log10
    min: 1.8e-06
    max: 0.0018
    init: 0.00018
```

For `scale: log10`, `min`, `max`, and `init` must be positive, and `init` must
fall within the physical min/max range.

If a model has no calibratable parameters for a workflow, leave
`calib_params_block` empty in its model instance.

## Calibration Output Retention

Calibration output retention is configured in `sandbox_config.yaml` under
`simulation.outputs`:

```yaml
simulation:
  outputs:
    calibration:
      retention: best  # options: best, all
```

With `retention: best`, divide-level outputs retain only `output_best`, and
plugin outputs such as simulation-observation files keep the first iteration
and the current best iteration.

With `retention: all`, outputs are stored by iteration. This is useful for
diagnostics but can require substantial storage for long or highly distributed
calibrations.
