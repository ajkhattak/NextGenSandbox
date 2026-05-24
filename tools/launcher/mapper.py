import yaml
import pandas as pd

gages_infile = "example_basins_file.csv" #--------------------------- input .csv file containing gage IDs


# Read gage IDs
df = pd.read_csv(gages_infile, dtype={"gage_ids": str})
gages = df["gage_ids"].tolist()


# Define available formulations
formulations = {
    "pet_cfe_s": "PET, CFE-S, T-route",
    "pet_cfe_x": "PET, CFE-X, T-route",
    "pet_topmodel": "PET, TopModel, T-route",
    "nom_cfe_s": "NOM, CFE-S, T-route",
    "nom_cfe_x": "NOM, CFE-X, T-route",
}



# Default formulation assignment
default_formulations = ["pet_cfe_s"]


# Initialize basins mapping using default formulations
mapping = {
    str(gage): default_formulations.copy()
    for gage in gages
}

# ------------------------------------------------------------
# Optional overrides - Examples
# ------------------------------------------------------------

mapping["02299950"] = [
    "pet_cfe_s",
    "pet_cfe_x"
]

mapping["01491000"] = [
    "nom_cfe_s"
]

# ------------------------------------------------------------
# Optional rule-based overrides - Examples
# ------------------------------------------------------------
for gage in gages:

    if gage.startswith("08"):
        mapping[str(gage)] = ["pet_topmodel"]
        

# Build final YAML structure - the file that launcher reads
cfg = {
    "formulations": formulations,
    "mapping": mapping
}

# Write YAML
with open("models_gages_map.yaml", "w") as f:
    yaml.dump(cfg, f, sort_keys=False,default_style='"')

print("Generated models gages mapping file")
