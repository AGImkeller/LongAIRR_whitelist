#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="${REPO_DIR}/scripts/longairrwhitelist_version.sh"
source "${VERSION_FILE}"

#================================================================#
#
#        Script:  install.sh
#         Usage:  bash install.sh [OPTIONS]
#
#   DESCRIPTION:  Install LongAIRR_whitelist.
#
#                 The installer can create the conda environment and/or
#                 install the command-line wrapper into ~/.local/bin.
#
#                 Installed commands:
#                   longairrwhitelist
#                   longairrwlist
#
#        AUTHOR:  Jonas Schuck, jschuckdev@gmail.com
#    BUG-REPORT:  https://github.com/AGImkeller/LongAIRR_whitelist/issues
#
#================================================================#

VERSION="${LONGAIRR_WHITELIST_VERSION}"

#====================Helper and Input functions====================#


INSTALL_DIR="${HOME}/.local/bin/longairrwhitelist"
ENV_NAME="longairr_whitelist"
ENV_FILE="${REPO_DIR}/environment_ont.yml"

INSTALL_ENV="TRUE"
INSTALL_BIN="TRUE"
FORCE="FALSE"
VERBOSE="TRUE"

show_help() {
    cat <<EOF_HELP
Usage:
  bash install.sh [OPTIONS]

Description:
  Install LongAIRR_whitelist.

  By default this creates the conda environment '${ENV_NAME}' and installs
  the command wrapper to:

    ${INSTALL_DIR}

Options:
  --repo-dir PATH
      Repository root containing the package files
      [default: directory containing this install.sh]
  --env TRUE|FALSE
      Create the conda environment [default: TRUE]
  --bin TRUE|FALSE
      Install the command wrapper [default: TRUE]
  --env-name NAME
      Conda environment name [default: ${ENV_NAME}]
  --env-file PATH
      Conda YAML file [default: <repo-dir>/environment_ont.yml]
  --install-dir PATH
      Installation directory for wrapper/internal scripts
      [default: ${INSTALL_DIR}]
  --force TRUE|FALSE
      If TRUE, recreate the conda environment and overwrite installed scripts
      [default: FALSE]
  --verbose TRUE|FALSE
      Print installation information [default: TRUE]
  -h, --help
      Show this help message and exit
  -v, --version
      Show version information and exit

Examples:
  bash install.sh

  bash install.sh --force TRUE

  bash install.sh --env FALSE --bin TRUE --force TRUE
EOF_HELP
}

show_version() {
    echo "LongAIRR_whitelist installer ${VERSION}"
}

to_upper_bool() {
    local value
    value="$(echo "$1" | tr '[:lower:]' '[:upper:]')"
    if [[ "${value}" != "TRUE" && "${value}" != "FALSE" ]]; then
        echo "[ERROR] Expected TRUE or FALSE, got: $1" >&2
        exit 1
    fi
    echo "${value}"
}

conda_frontend() {
    if command -v mamba >/dev/null 2>&1; then
        echo "mamba"
    else
        echo "conda"
    fi
}

env_exists() {
    local env_name="$1"
    conda env list | awk '{print $1}' | grep -qx "${env_name}"
}

create_env() {
    local frontend
    frontend="$(conda_frontend)"

    if [[ ! -f "${ENV_FILE}" ]]; then
        echo "[ERROR] Environment file not found: ${ENV_FILE}" >&2
        exit 1
    fi

    if env_exists "${ENV_NAME}"; then
        if [[ "${FORCE}" == "TRUE" ]]; then
            echo "[INFO] Removing existing conda environment: ${ENV_NAME}"
            conda env remove -n "${ENV_NAME}" -y
        else
            echo "[INFO] Conda environment '${ENV_NAME}' already exists. Skipping creation."
            echo "       To recreate it, rerun with --force TRUE."
            return 0
        fi
    fi

    echo "[INFO] Creating conda environment '${ENV_NAME}' from ${ENV_FILE}"
    "${frontend}" env create -f "${ENV_FILE}"
}

install_wrapper() {
    local scripts_dir="${REPO_DIR}/scripts"
    local main_script="${scripts_dir}/longairrwhitelist"

    if [[ ! -d "${scripts_dir}" ]]; then
        echo "[ERROR] Scripts directory not found: ${scripts_dir}" >&2
        exit 1
    fi

    if [[ ! -f "${main_script}" ]]; then
        echo "[ERROR] Main wrapper not found: ${main_script}" >&2
        exit 1
    fi

    if [[ -d "${INSTALL_DIR}" && "${FORCE}" == "TRUE" ]]; then
        echo "[INFO] Removing existing install directory: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    fi

    mkdir -p "${INSTALL_DIR}/scripts"
    cp -R "${scripts_dir}/." "${INSTALL_DIR}/scripts/"

    chmod +x "${INSTALL_DIR}/scripts/longairrwhitelist"
    chmod +x "${INSTALL_DIR}/scripts/"*.py 2>/dev/null || true

    ln -sf "${INSTALL_DIR}/scripts/longairrwhitelist" "${INSTALL_DIR}/longairrwhitelist"
    ln -sf "${INSTALL_DIR}/scripts/longairrwhitelist" "${INSTALL_DIR}/longairrwlist"

    echo "[INFO] Installed wrapper to: ${INSTALL_DIR}"
    echo "[INFO] Installed commands: longairrwhitelist, longairrwlist"
}

write_bashrc_block() {
    if [[ ! -f "${HOME}/.bashrc" ]]; then
        touch "${HOME}/.bashrc"
    fi

    sed -i '/# >>> LongAIRR_whitelist PATH >>>/,/# <<< LongAIRR_whitelist PATH <<</d' "${HOME}/.bashrc"

    {
        echo ""
        echo "# >>> LongAIRR_whitelist PATH >>>"
        echo "export PATH=\"\$PATH:${INSTALL_DIR}\""
        echo "# <<< LongAIRR_whitelist PATH <<<"
    } >> "${HOME}/.bashrc"

    echo "[INFO] PATH block added to ~/.bashrc"
}

# parameters and main

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-dir)
            REPO_DIR="$(cd "$2" && pwd)"
            VERSION_FILE="${REPO_DIR}/scripts/longairrwhitelist_version.sh"
            ENV_FILE="${REPO_DIR}/environment_ont.yml"
            shift 2
            ;;
        --env)
            INSTALL_ENV="$(to_upper_bool "$2")"
            shift 2
            ;;
        --bin)
            INSTALL_BIN="$(to_upper_bool "$2")"
            shift 2
            ;;
        --env-name)
            ENV_NAME="$2"
            shift 2
            ;;
        --env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --force)
            FORCE="$(to_upper_bool "$2")"
            shift 2
            ;;
        --verbose)
            VERBOSE="$(to_upper_bool "$2")"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -v|--version)
            show_version
            exit 0
            ;;
        *)
            echo "[ERROR] Unexpected argument: $1" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

REPO_DIR="$(cd "${REPO_DIR}" && pwd)"
ENV_FILE="$(realpath -m "${ENV_FILE}")"
INSTALL_DIR="$(realpath -m "${INSTALL_DIR}")"

# Re-source after possible --repo-dir change.
VERSION_FILE="${REPO_DIR}/scripts/longairrwhitelist_version.sh"
if [[ -f "${VERSION_FILE}" ]]; then
    source "${VERSION_FILE}"
    VERSION="${LONGAIRR_WHITELIST_VERSION}"
fi

if [[ "${VERBOSE}" == "TRUE" ]]; then
    echo ""
    echo "[INFO] LongAIRR_whitelist installer ${VERSION}"
    echo "[INFO] Repository:      ${REPO_DIR}"
    echo "[INFO] Environment:     ${ENV_NAME}"
    echo "[INFO] Environment YAML:${ENV_FILE}"
    echo "[INFO] Install env:     ${INSTALL_ENV}"
    echo "[INFO] Install wrapper: ${INSTALL_BIN}"
    echo "[INFO] Install dir:     ${INSTALL_DIR}"
    echo ""
fi

if [[ "${INSTALL_ENV}" == "TRUE" ]]; then
    if ! command -v conda >/dev/null 2>&1; then
        echo "[ERROR] conda is not available. Install Miniforge/Mambaforge or activate conda first." >&2
        exit 1
    fi
    create_env
else
    echo "[INFO] Skipping conda environment creation because --env FALSE was used."
fi

if [[ "${INSTALL_BIN}" == "TRUE" ]]; then
    install_wrapper
    write_bashrc_block
else
    echo "[INFO] Skipping wrapper installation because --bin FALSE was used."
fi

cat <<EOF_DONE

========================================================================
|                LongAIRR_whitelist setup complete                     |
|                                                                      |
|  Reload your shell configuration:                                    |
|      source ~/.bashrc                                                |
|                                                                      |
|  Activate the environment:                                           |
|      conda activate ${ENV_NAME}                                      |
|                                                                      |
|  Check installation:                                                 |
|      longairrwhitelist check                                         |
|                                                                      |
|  Short alias:                                                        |
|      longairrwlist check                                             |
========================================================================
EOF_DONE
