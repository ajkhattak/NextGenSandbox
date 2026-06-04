#!/usr/bin/env bash

# Prevent multiple initializations
if [ -n "$SANDBOX_ENV_LOADED" ]; then
    ALREADY_LOADED=ON
else
    export SANDBOX_ENV_LOADED=1
    ALREADY_LOADED=OFF
fi


ENV_VERBOSE=${VERBOSE:-OFF}


for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"

    case "$key" in
        VERBOSE) ENV_VERBOSE="$value" ;;
        *) echo "Warning: unrecognized argument '$arg'" ;;
    esac
done

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo ""
    echo "ERROR: Please source this script:"
    echo ""
    echo "    source $(basename "$0")"
    echo ""
    exit 1
fi

######## PATH DETECTION #########

if [ -n "${BASH_SOURCE[0]:-}" ]; then
    SOURCE="${BASH_SOURCE[0]}"
else
    SOURCE="$0"
fi

# Path detection

SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SOURCE")"

SANDBOX_DIR="$(dirname "$SCRIPT_DIR")"

SANDBOX_BUILD_DIR="${SANDBOX_BUILD_DIR:-$SANDBOX_DIR/build}"
SANDBOX_DATA="${SANDBOX_DATA:-$SANDBOX_DIR/data}"
SANDBOX_CONDARC="${SANDBOX_CONDARC:-$SANDBOX_BUILD_DIR/condarc}"

NGEN_DIR="$SANDBOX_BUILD_DIR/ngen"

SANDBOX_ENV="$SANDBOX_BUILD_DIR/venv/sandbox"
FORCING_ENV="$SANDBOX_BUILD_DIR/venv/forcing"


########## Export environment #########
export SANDBOX_DIR
export SANDBOX_BUILD_DIR
export SANDBOX_DATA
export SANDBOX_CONDARC
export NGEN_DIR
export SANDBOX_ENV
export FORCING_ENV

export CONDARC="$SANDBOX_CONDARC"

mkdir -p "$SANDBOX_BUILD_DIR"
mkdir -p "$SANDBOX_DATA"
touch "$SANDBOX_CONDARC"

######### Detect target shell config #####
if [[ "$SHELL" == *zsh ]]; then

    TARGET_FILE="$HOME/.zshrc"

elif [[ "$SHELL" == *bash ]]; then

    if [ -f "$HOME/.bash_profile" ]; then
        TARGET_FILE="$HOME/.bash_profile"
    else
        TARGET_FILE="$HOME/.bashrc"
    fi

else
    echo ""
    echo "ERROR: Unsupported shell: $SHELL"
    echo ""
    return 1
fi


############ Persist configuration ##############
SOURCE_LINE="[ -f \"$SCRIPT_PATH\" ] && source \"$SCRIPT_PATH\""


if ! grep -Fxq "$SOURCE_LINE" "$TARGET_FILE" 2>/dev/null; then

    echo ""
    echo "Adding sandbox environment to:"
    echo "    $TARGET_FILE"
    echo ""

    echo "$SOURCE_LINE" >> "$TARGET_FILE"

    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to update $TARGET_FILE"
        return 1
    fi

    echo "Shell configuration updated successfully."
    echo ""

    echo "IMPORTANT:"
    echo "The sandbox environment will be loaded automatically for future terminal sessions."
    echo ""
    echo "To use the environment in the current terminal, either:"
    echo ""
    echo "  source $TARGET_FILE"
    echo ""
    echo "or open a new terminal window."
    echo ""

fi

###### Validate persistence ########
if ! grep -Fxq "$SOURCE_LINE" "$TARGET_FILE" 2>/dev/null; then
    echo "ERROR: Failed to validate persistent environment setup."
    return 1
fi


# Validate environment
for var in \
    SANDBOX_DIR \
    SANDBOX_BUILD_DIR \
    SANDBOX_DATA \
    SANDBOX_CONDARC \
    NGEN_DIR \
    SANDBOX_ENV \
    FORCING_ENV
do
    eval "value=\${$var}"

    if [ -z "$value" ]; then
        echo "ERROR: Missing environment variable: $var"
        return 1
    fi
    
done

if [ "$ENV_VERBOSE" = "ON" ]; then
    if [ "$ALREADY_LOADED" = "ON" ]; then
        echo "Sandbox environment already loaded."
	echo "SANDBOX_DIR        : $SANDBOX_DIR"
	echo "SANDBOX_BUILD_DIR  : $SANDBOX_BUILD_DIR"
	echo "SANDBOX_DATA       : $SANDBOX_DATA"
	echo "SANDBOX_CONDARC    : $SANDBOX_CONDARC"
	echo "NGEN_DIR           : $NGEN_DIR"
	echo "SANDBOX_ENV        : $SANDBOX_ENV"
	echo "FORCING_ENV        : $FORCING_ENV"
	echo ""
    else
	echo "Sandbox environment successfully configured, but not loaded yet"
	echo "  source $TARGET_FILE"
    fi

fi
