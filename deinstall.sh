#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${REPO_DIR}/scripts/longairrwhitelist_version.sh"

#================================================================#
#
#        Script:  deinstall.sh
#         Usage:  bash deinstall.sh [OPTIONS]
#
#   DESCRIPTION:  Remove the LongAIRR_whitelist conda environment,
#                 installed wrapper/scripts, and PATH settings.
#
#        AUTHOR:  Jonas Schuck, jschuckdev@gmail.com
#    BUG-REPORT:  https://github.com/AGImkeller/LongAIRR_whitelist/issues
#
#================================================================#

VERSION="${LONGAIRR_WHITELIST_VERSION}"

ENV_NAME="longairr_whitelist"
INSTALL_DIR="${HOME}/.local/bin/longairrwhitelist"

REMOVE_ENV="TRUE"
REMOVE_BIN="TRUE"
VERBOSE="TRUE"

show_help() {
    cat <<EOF_HELP
Usage:
  bash deinstall.sh [OPTIONS]

Description:
  Remove LongAIRR_whitelist from the current user account.

Options:
  --env TRUE|FALSE
      Remove the conda environment (default: TRUE)
  --bin TRUE|FALSE
      Remove installed command wrappers and PATH block (default: TRUE)
  --env-name NAME
      Conda environment name (default: ${ENV_NAME})
  --install-dir PATH
      Installed wrapper directory (default: ${INSTALL_DIR})
  --verbose TRUE|FALSE
      Print progress messages (default: TRUE)
  -h, --help
      Show this help message and exit
  -v, --version
      Show version information and exit

Examples:
  bash deinstall.sh
  bash deinstall.sh --env FALSE --bin TRUE
  bash deinstall.sh --env-name longairr_whitelist_test
EOF_HELP
}

show_version() {
    echo "LongAIRR_whitelist deinstaller ${VERSION}"
}

log() {
    if [[ "${VERBOSE}" == "TRUE" ]]; then
        echo "$@"
    fi
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

env_exists() {
    local env_name="$1"
    conda env list | awk '{print $1}' | grep -qx "${env_name}"
}


#---------------------------------main functions--------------------------------

remove_env() {
    if ! command -v conda >/dev/null 2>&1; then
        echo "[WARN] conda not found on PATH. Cannot remove conda environment: ${ENV_NAME}" >&2
        return 0
    fi

    if env_exists "${ENV_NAME}"; then
        log "[INFO] Removing conda environment: ${ENV_NAME}"
        conda env remove -n "${ENV_NAME}" -y
    else
        log "[INFO] Conda environment not found: ${ENV_NAME}"
    fi
}

remove_installed_files() {
    if [[ -d "${INSTALL_DIR}" ]]; then
        log "[INFO] Removing installed wrapper/scripts: ${INSTALL_DIR}"
        rm -rf "${INSTALL_DIR}"
    else
        log "[INFO] Installed wrapper directory not found: ${INSTALL_DIR}"
    fi

    if [[ -f "${HOME}/.bashrc" ]] && grep -q "# >>> LongAIRR_whitelist PATH >>>" "${HOME}/.bashrc"; then
        log "[INFO] Removing LongAIRR_whitelist PATH block from ~/.bashrc"
        sed -i '/# >>> LongAIRR_whitelist PATH >>>/,/# <<< LongAIRR_whitelist PATH <<</d' "${HOME}/.bashrc"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            REMOVE_ENV="$(to_upper_bool "$2")"
            shift 2
            ;;
        --bin)
            REMOVE_BIN="$(to_upper_bool "$2")"
            shift 2
            ;;
        --env-name)
            ENV_NAME="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
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

INSTALL_DIR="$(realpath -m "${INSTALL_DIR}")"

if [[ "${VERBOSE}" == "TRUE" ]]; then
    echo ""
    echo "[INFO] LongAIRR_whitelist deinstaller ${VERSION}"
    echo "[INFO] Remove env:       ${REMOVE_ENV}"
    echo "[INFO] Env name:         ${ENV_NAME}"
    echo "[INFO] Remove wrapper:   ${REMOVE_BIN}"
    echo "[INFO] Install dir:      ${INSTALL_DIR}"
    echo ""
fi

if [[ "${REMOVE_ENV}" == "TRUE" ]]; then
    remove_env
else
    log "[INFO] Skipping conda environment removal because --env FALSE was used."
fi

if [[ "${REMOVE_BIN}" == "TRUE" ]]; then
    remove_installed_files
else
    log "[INFO] Skipping wrapper/PATH removal because --bin FALSE was used."
fi

cat <<EOF_DONE

========================================================================
|              LongAIRR_whitelist deinstall complete                   |
|                                                                      |
|  Reload your shell configuration:                                    |
|      source ~/.bashrc                                                |
========================================================================
EOF_DONE
