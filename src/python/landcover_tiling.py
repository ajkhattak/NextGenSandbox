#!/usr/bin/env python3

import argparse
import subprocess
import pathlib
from pathlib import Path
import os
import glob
import pandas as pd
import geopandas as gpd
import numpy as np
import json
import re


def main() -> None:
    args = parse_args()
    run(args)


def run(args: dict[str, pathlib.Path]):
    dryrun: bool = args["dryrun"]

    hf          = str(args["hydrofabric"])
    realization = str(args["realization"])
    num_proc    = int(args["partition"])
    task_type   = str(args["task_type"])

    ngen = os.path.join(
        os.environ["SANDBOX_BUILD_DIR"],
        "ngen/cmake_build/ngen"
    )

    
    config_dir =  Path(realization).parent
    
    realization_files = sorted(config_dir.glob("realization_*.json"))

    partition_file = config_dir / f"partitions_{num_proc}.json"

    routing = str(args["routing"])
    if task_type == "validation":
        routing = config_dir / "troute_valid_config.yaml"

    worker_dir = Path.cwd()
    
    base_realization_file =  worker_dir / realization_files[0].name

    if not base_realization_file.exists():
        raise FileNotFoundError(f"Base file not found: {base_realization_file}")
    
    for i, realization_file in enumerate(realization_files):

        output_file = worker_dir / realization_file.name
        
        copy_and_filter_model_params(src_path = base_realization_file.name,
                                     dst_path = realization_file,
                                     output_path = worker_dir / f"realization_{i+1}.json",
                                     keep_tiles = [f'tile_{i+1}']
                                     )
            

    
    for i, realization_file in enumerate(realization_files):
        realization_file_calib =  worker_dir / f"realization_{i+1}.json" #.name
       

        with open(realization_file_calib, "r") as f:
            data = json.load(f)

        for module in data["global"]["formulations"][0]["params"]["modules"]:
            if "model_params" in module["params"]:
                print(module["name"], type(module["params"]["model_params"]))

        cmd = [ngen, hf, "all", hf, "all", realization_file_calib]


        if num_proc > 1:
            cmd = ["mpirun", "-np", str(num_proc)] + cmd + [partition_file]
    

        exec_cmd(cmd, dryrun=dryrun)


                            
    # Apply weights to outputs
    output_dirs = sorted(
        (config_dir.parent / "output").glob("output_cfg_tile-*")
    )

    output_dirs = sorted(
        output_dirs,
        key=lambda p: p.name
    )
    
    weights_df = read_ensemble_weights(config_dir / "ensemble_weights.csv")

    # get divide ID and nexus ID map
    gdf_fp_attr = gpd.read_file(hf, layer="flowpaths")
    divide_to_nexus = dict(zip(gdf_fp_attr["divide_id"], gdf_fp_attr["toid"]))

    apply_ensemble_weights(output_dirs, weights_df, divide_to_nexus)
    

    cmd = [sys.executable, "-m", "nwm_routing", "-V4", "-f", routing]
    exec_cmd(cmd, dryrun=dryrun)


def copy_and_filter_model_params(
    src_path: str,
    dst_path: str,
    output_path: str,
    keep_tiles: list
):
    """
    Copy model_params from src JSON to dst JSON, filter keys by keep_tiles,
    remove "_tile_" from keys, and save result.

    This function loops over all modules in the JSON and updates any module
    that contains model_params with _tile_ keys.
    """
    with open(src_path, "r") as f:
        src = json.load(f)

    with open(dst_path, "r") as f:
        dst = json.load(f)
    
    # Compare the "time" blocks
    if src.get("time") != dst.get("time"):
        dst["time"] = src.get("time")
    
    # Extract model_params from source modules
    for src_module in src["global"]["formulations"][0]["params"]["modules"]:

        if "model_params" not in src_module["params"]:
            continue
        
        src_params = src_module["params"]["model_params"]

        # Skip SLOTH
        if  src_module["params"]["model_type_name"] == "SLOTH":
            continue

        filtered_params = {}

        for k, v in src_params.items():
            if "_tile_" not in k:
                filtered_params[k] = v
                continue

            tile_part = k.split("_tile_")[1]  # e.g., "1" or "2"
            tile_name = f"tile_{tile_part}"

            # Skip if not in keep list
            if tile_name not in keep_tiles:
                continue

            new_key = k.replace(f"_tile_{tile_part}", "")
            
            filtered_params[new_key] = v

        # Update corresponding module in destination JSON
        for dst_module in dst["global"]["formulations"][0]["params"]["modules"]:
            if dst_module['params']["model_type_name"] == src_module['params']["model_type_name"]:
                dst_module["params"]["model_params"] = filtered_params

    # Save updated JSON
    with open(output_path, "w") as f:
        json.dump(dst, f, indent=4)

    #print(f"Updated JSON saved to: {output_path}")

    


def read_ensemble_weights(path: pathlib.Path):

    suffix = path.suffix.lower()
    
    if suffix == ".csv":
        df = pd.read_csv(path)

    elif suffix == ".parquet":
        df = pd.read_parquet(path)

    else:
        raise ValueError("file_format must be one of ['csv', 'json', 'parquet']")

    return df


def apply_ensemble_weights(
        output_dirs: list[Path],
        weights_df: pd.DataFrame,
        divide_to_nexus: dict[str, str]):
    
    weight_cols = [c for c in weights_df.columns if c.startswith("weight_")]

    for _, row in weights_df.iterrows():
        divide_id = row["divide_id"]
        weights = row[weight_cols].values.astype(float)


        if len(weights) != len(output_dirs):
            raise ValueError(
                f"{divide_id}: {len(weights)} weights but "
                f"{len(output_dirs)} directories"
            )

        # weights = weights / weights.sum() # this can be a choice too if weights are not normalized
        if not np.isclose(weights.sum(), 1.0):
            raise ValueError(f"{divide_id}: weights do not sum to 1")

        nexus_id = divide_to_nexus[divide_id]

        
        # use filenames from the first directory as reference
        ref_files = list(output_dirs[0].glob(f"{nexus_id}*.csv"))

        if len(ref_files) != 1:
            raise ValueError(
                f"{divide_id}: expected exactly 1 file for nexus {nexus_id}, "
                f"found {len(ref_files)}"
            )

        ref_file = ref_files[0]

        files = [d / ref_file.name for d in output_dirs]

        # ensure file exists everywhere
        for f in files:
            if not f.exists():
                raise FileNotFoundError(f"Missing {f}")

        out_file = Path.cwd() / ref_file.name
        out_file.parent.mkdir(parents=True, exist_ok=True)
        
        dfs = [pd.read_csv(f,
                           header=None,
                           names=["idx", "ts", "value"]
                           )
               for f in files
               ]

        base = dfs[0][["idx", "ts"]]
        
        # stack values and apply weights
        values = pd.concat([df["value"] for df in dfs], axis=1)
        values.columns = [f"member_{i+1}" for i in range(len(dfs))]
        
        weighted = values.mul(weights, axis=1).sum(axis=1)

        out_df = base.copy()
        out_df["value"] = weighted

        out_df.to_csv(out_file, index=False, header=False)

        
def exec_cmd(args: list[str], dryrun: bool = False):
    import shlex

    if dryrun:
        #print(shlex.join(args))
        return
    subprocess.run(args, check=True)


def parse_args(args: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun",      action="store_true")
    parser.add_argument("--hydrofabric", type=pathlib.Path, required=True,  help="Path to hydrofabric gpkg")
    parser.add_argument("--realization", type=pathlib.Path, required=True,  help="Path to ngen realization file")
    parser.add_argument("--routing",     type=pathlib.Path, required=True,  help="Path to t-route config file")
    parser.add_argument("--partition",   type=int,          required=False, help="Number of processors", default=1)

    parser.add_argument("--task_type",   type=str,          required=False, help="task type", default="calibration")
    # based on this tasktype, create a new function for validation, read calib.yaml, write two updated json files
    # or write to calib.yaml files for each tile and run validation for both -- think more
    parsed = parser.parse_args(args)
    return vars(parsed)


if __name__ == "__main__":
    main()
