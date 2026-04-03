#!/bin/bash
# Helper: run a command with sudo in WSL2 using the .env credential
# Usage: bash scripts/wsl_sudo.sh "apt-get update"
#
# Reads WSL_SUDO_PASS from .env file in the project root.
# Falls back to interactive password prompt if .env is missing.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
    WSL_SUDO_PASS=$(grep '^WSL_SUDO_PASS=' "$ENV_FILE" | cut -d'=' -f2-)
fi

if [ -z "$WSL_SUDO_PASS" ]; then
    echo "ERROR: WSL_SUDO_PASS not set in .env" >&2
    echo "Fill in your password in: $ENV_FILE" >&2
    exit 1
fi

echo "$WSL_SUDO_PASS" | sudo -S bash -c "$*" 2>/dev/null
