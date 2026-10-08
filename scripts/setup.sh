#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
export npm_config_cache="${npm_config_cache:-/workspace/.npm-cache}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.uv-cache}"
export electron_config_cache="${electron_config_cache:-/workspace/.electron-cache}"
export NODE_USE_ENV_PROXY=1
if [[ ! -x .venv/bin/python ]]; then
  uv venv .venv --python python3
fi
uv pip sync backend/requirements.lock --python .venv/bin/python --require-hashes
npm ci --no-audit --no-fund
node node_modules/electron/install.js
npm run build
npm test
