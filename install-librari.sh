#!/usr/bin/env bash
# Install the vendored librari CLI (tools/librari) with uv. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv tool install --force "$HERE/tools/librari"
librari --version
