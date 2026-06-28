#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${LAUNCHER_CONFIG:-$SCRIPT_DIR/launcher_config.yaml}"

python "$SCRIPT_DIR/sandbox_launcher.py" status --config "$CONFIG_FILE"
