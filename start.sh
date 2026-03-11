#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NET="python3 $SCRIPT_DIR/scripts/lib/net.py"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

source "$SCRIPT_DIR/scripts/start/helpers.sh"
source "$SCRIPT_DIR/scripts/start/commands.sh"
source "$SCRIPT_DIR/scripts/start/runtime.sh"

initialize_start_state

trap handle_interrupt INT TERM
trap cleanup EXIT

start_main "$@"
