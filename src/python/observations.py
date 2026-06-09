from pathlib import Path

import pandas as pd


class ObservationLoader:
    """Read and normalize local CSV or Parquet observation datasets."""

    SUPPORTED_LAYOUTS = {"point", "distributed"}

    def __init__(self, observations, config_dir):
        self.observations = observations
        self.config_dir = Path(config_dir)
        self.units = {}

    def load(self, gage_ids):
        loaded = {}

        for name, config in self.observations.items():
            self._validate_config(name, config)
            self.units[name] = config["units"]
            loaded[name] = {
                gage_id: self.load_one(name, config, gage_id)
                for gage_id in gage_ids
            }

        return loaded

    def validate(self, gage_ids):
        """Validate observation files without loading their values."""
        validated = {}

        for name, config in self.observations.items():
            self._validate_config(name, config)
            self.units[name] = config["units"]
            validated[name] = {
                gage_id: self.validate_one(name, config, gage_id)
                for gage_id in gage_ids
            }

        return validated

    def validate_one(self, name, config, gage_id):
        """Resolve and validate one observation file for one gage."""
        self._validate_config(name, config)
        path = self.resolve_path(name, config["path"], gage_id)
        columns = self._read_columns(path)
        self._validate_columns(name, config, path, columns)
        return {
            "path": path,
            "layout": config["layout"].lower(),
            "time_column": config["time_column"],
            "value_column": config.get("value_column"),
            "id_column": config.get("id_column"),
            "units": config["units"],
            "simulated": config.get("simulated"),
        }

    def load_one(self, name, config, gage_id):
        """Resolve and load one observation dataset for one gage."""
        self._validate_config(name, config)
        path = self.resolve_path(name, config["path"], gage_id)
        return self.load_path(name, config, path)

    def load_path(self, name, config, path):
        """Load one observation dataset from an absolute file path."""
        self._validate_config(name, config)

        path = Path(path).expanduser()
        if not path.is_absolute():
            raise ValueError(f"Observation file path must be absolute: {path}")
        path = path.resolve()
        self._validate_path(name, path)

        if path.suffix.lower() == ".csv":
            dataframe = pd.read_csv(path)
        else:
            dataframe = pd.read_parquet(path)

        return self._normalize_dataframe(name, config, path, dataframe)

    def _read_columns(self, path):
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, nrows=0).columns.tolist()

        import pyarrow.parquet as pq

        return pq.read_schema(path).names

    def _validate_columns(self, name, config, path, columns):
        required = [config["time_column"]]
        layout = config["layout"].lower()

        if layout == "point":
            required.append(config["value_column"])
        elif config.get("id_column"):
            required.extend([config["id_column"], config["value_column"]])

        missing = [column for column in required if column not in columns]
        if missing:
            raise ValueError(
                f"Observation file {path} is missing columns for {name}: "
                f"{', '.join(missing)}"
            )

        if layout == "distributed" and not config.get("id_column"):
            sub_basin_columns = [
                column for column in columns if column != config["time_column"]
            ]
            if not sub_basin_columns:
                raise ValueError(
                    f"Wide distributed observation file has no sub-basin columns: {path}"
                )

    def _validate_config(self, name, config):
        if not isinstance(config, dict):
            raise TypeError(f"observations.{name} must be a mapping")

        layout = str(config.get("layout", "")).lower()
        if layout not in self.SUPPORTED_LAYOUTS:
            raise ValueError(
                f"observations.{name}.layout must be one of: "
                f"{', '.join(sorted(self.SUPPORTED_LAYOUTS))}"
            )

        if not config.get("path"):
            raise ValueError(f"observations.{name}.path must be provided")

        for field in ("time_column", "units"):
            value = config.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"observations.{name}.{field} must be a non-empty string"
                )

        if name.lower() == "streamflow" and config["units"] not in {
            "m3/s",
            "m3/sec",
        }:
            raise ValueError(
                "observations.streamflow.units must be 'm3/s' or 'm3/sec'"
            )

        if layout == "point":
            value_column = config.get("value_column")
            if not isinstance(value_column, str) or not value_column.strip():
                raise ValueError(
                    f"observations.{name}.value_column must be provided "
                    "for point observations"
                )

        # For wide-format distributed observations, no id_column or value_column is needed:
        # value_time           cat-1  cat-2
        # 2016-01-01 00:00:00  1.2    1.8
        # for long-format distributed observations, id_column:divide_id, value_column:ET is needed
        # value_time           divide_id   ET
        # 2016-01-01 00:00:00  cat-1       1.2
        # 2016-01-01 00:00:00  cat-2       1.8

        if layout == "distributed" and config.get("id_column"):
            value_column = config.get("value_column")
            if not isinstance(value_column, str) or not value_column.strip():
                raise ValueError(
                    f"observations.{name}.value_column must be provided "
                    "for long-format distributed observations"
                )

        simulated = config.get("simulated")
        if simulated is not None:
            if not isinstance(simulated, str) or not simulated.strip():
                raise ValueError(
                    f"observations.{name}.simulated must name a simulation "
                    "output variable"
                )

    def _normalize_dataframe(self, name, config, path, dataframe):
        time_column = config["time_column"]

        if time_column not in dataframe.columns:
            if dataframe.index.name == time_column:
                dataframe = dataframe.reset_index()
            else:
                raise ValueError(
                    f"Observation file {path} does not contain time column "
                    f"'{time_column}'"
                )

        dataframe[time_column] = pd.to_datetime(dataframe[time_column])

        if config["layout"].lower() == "point":
            return self._load_point(name, config, path, dataframe)

        return self._load_distributed(name, config, path, dataframe)

    def resolve_path(self, name, path_template, gage_id):
        """Resolve a configured path template to an absolute observation file."""
        try:
            rendered = str(path_template).format(
                gage_id=gage_id,
                variable=name,
            )
        except KeyError as exc:
            raise ValueError(
                f"Unsupported observations.{name}.path placeholder: {exc.args[0]}"
            ) from exc

        path = Path(rendered).expanduser()
        if not path.is_absolute():
            path = self.config_dir / path
        path = path.resolve()

        self._validate_path(name, path, gage_id)
        return path

    def _validate_path(self, name, path, gage_id=None):
        if path.suffix.lower() not in {".csv", ".parquet", ".pq"}:
            raise ValueError(
                "Observation file must be CSV or Parquet "
                f"(.csv, .parquet, or .pq): {path}"
            )
        if not path.is_file():
            gage_text = f", gage {gage_id}" if gage_id is not None else ""
            raise FileNotFoundError(
                f"Observation file not found for {name}{gage_text}: {path}"
            )

    def _load_point(self, name, config, path, dataframe):
        time_column = config["time_column"]
        value_column = config["value_column"]

        if value_column not in dataframe.columns:
            raise ValueError(
                f"Observation file {path} does not contain value column "
                f"'{value_column}'"
            )
        if dataframe[time_column].duplicated().any():
            raise ValueError(f"Point observation file has duplicate times: {path}")

        series = dataframe.set_index(time_column)[value_column].sort_index()
        series.name = name
        return series

    def _load_distributed(self, name, config, path, dataframe):
        time_column = config["time_column"]
        id_column = config.get("id_column")

        if id_column:
            value_column = config["value_column"]
            missing = [
                column
                for column in (id_column, value_column)
                if column not in dataframe.columns
            ]
            if missing:
                raise ValueError(
                    f"Observation file {path} is missing columns: "
                    f"{', '.join(missing)}"
                )
            if dataframe[[time_column, id_column]].duplicated().any():
                raise ValueError(
                    f"Distributed observation file has duplicate "
                    f"({time_column}, {id_column}) rows: {path}"
                )

            distributed = dataframe.pivot(
                index=time_column,
                columns=id_column,
                values=value_column,
            )
        else:
            if dataframe[time_column].duplicated().any():
                raise ValueError(
                    f"Wide distributed observation file has duplicate times: {path}"
                )
            distributed = dataframe.set_index(time_column)
            if distributed.columns.empty:
                raise ValueError(
                    f"Wide distributed observation file has no sub-basin columns: {path}"
                )

        distributed.sort_index(inplace=True)
        distributed.columns.name = "divide_id"

        return distributed
