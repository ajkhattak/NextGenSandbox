# Supported Formulations

Formulations may omit `T-ROUTE` because the workflow appends it automatically.
All other model components must match a registered formulation.

## CFE

CFE is the Conceptual Functional Equivalent model. NextGenSandbox uses the
`cfe-s` model instance with Schaake runoff partitioning by default. To use
another configured instance, such as `cfe-x` with Xinanjiang runoff
partitioning, configure `formulation.model_instances.CFE` in
`sandbox_config.yaml`.

Supported CFE formulations:

- `NOM, CFE, T-ROUTE`
- `PET, CFE, T-ROUTE`
- `NOM, PET, CFE, T-ROUTE`
- `NOM, CFE, SMP, SFT, T-ROUTE`
- `SNOW17, PET, CFE, T-ROUTE`

## TOPMODEL

- `NOM, TOPMODEL, T-ROUTE`
- `PET, TOPMODEL, T-ROUTE`
- `NOM, PET, TOPMODEL, T-ROUTE`
- `SNOW17, PET, TOPMODEL, T-ROUTE`

## CASAM

CASAM is an LGAR-based, catchment-scale rainfall-runoff model.

- `NOM, CASAM, T-ROUTE`
- `PET, CASAM, T-ROUTE`
- `SNOW17, PET, CASAM, T-ROUTE` *(not tested yet)*
- `NOM, CASAM, SMP, SFT, T-ROUTE` *(not tested yet)*

## SAC-SMA

- `SNOW17, PET, SAC-SMA`

## Machine-Learning Models

- `LSTM`
- `dHBV`

## Model Source Code

The following hydrologic and hydraulic modules are supported by
NextGenSandbox.

| Model or module | Source repository |
|---|---|
| NOM (Noah-OWP-Modular) | [NOAA-OWP/noah-owp-modular](https://github.com/NOAA-OWP/noah-owp-modular) |
| CFE | [NOAA-OWP/cfe](https://github.com/NOAA-OWP/cfe) |
| TOPMODEL | [NOAA-OWP/topmodel](https://github.com/NOAA-OWP/topmodel) |
| Snow-17 | [NOAA-OWP/snow17](https://github.com/NOAA-OWP/snow17) |
| PET (Potential Evapotranspiration) | [NOAA-OWP/evapotranspiration](https://github.com/NOAA-OWP/evapotranspiration) |
| SAC-SMA | [NOAA-OWP/sac-sma](https://github.com/NOAA-OWP/sac-sma) |
| CASAM (LGAR-based rainfall-runoff model) | [NOAA-OWP/LGAR-C](https://github.com/NOAA-OWP/LGAR-C) |
| LSTM (ML-based streamflow) | [NOAA-OWP/lstm](https://github.com/NOAA-OWP/lstm) |
| dHBV (ML-based streamflow) | [mhpi/dhbv2](https://github.com/mhpi/dhbv2) |
| SFT (SoilFreezeThaw) | [NOAA-OWP/soilfreezethaw](https://github.com/NOAA-OWP/soilfreezethaw) |
| SMP (SoilMoistureProfiles) | [NOAA-OWP/soilmoistureprofiles](https://github.com/NOAA-OWP/soilmoistureprofiles) |
| T-ROUTE (routing) | [NOAA-OWP/t-route](https://github.com/NOAA-OWP/t-route) |
