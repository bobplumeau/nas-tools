#!/usr/bin/env bash
# Installs or refreshes nas_t on Linux/macOS: pulls the latest code, (re)creates the venv
# if needed, reinstalls, runs the tests, and links `nas_t` into ~/.local/bin.
#   ./setup.sh             # install / update
#   ./setup.sh --no-pull   # reinstall local changes without git pull
#   ./setup.sh --clean     # rebuild the venv from scratch
set -euo pipefail
cd "$(dirname "$0")"

pull=1 clean=0 tests=1
for arg in "$@"; do
    case "$arg" in
        --no-pull) pull=0 ;;
        --clean) clean=1 ;;
        --skip-tests) tests=0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ "$pull" = 1 ] && [ -d .git ]; then
    echo "== git pull"
    git pull --ff-only
fi
[ "$clean" = 1 ] && rm -rf venv
if [ ! -x venv/bin/python ]; then
    echo "== creating venv"
    python3 -m venv venv
fi

echo "== installing"
venv/bin/python -m pip install --quiet --upgrade pip
venv/bin/python -m pip install --quiet -e ".[dev]"

if [ "$tests" = 1 ]; then
    echo "== tests"
    venv/bin/python -m pytest tests -q
fi

mkdir -p ~/.local/bin
ln -sf "$PWD/venv/bin/nas_t" ~/.local/bin/nas_t

cfg=~/.config/nas_t/devices.yaml
if [ ! -f "$cfg" ] && [ ! -f ~/.config/nas-t/devices.yaml ] && [ ! -f devices.yaml ]; then
    mkdir -p "$(dirname "$cfg")"
    cp devices.example.yaml "$cfg"
    echo "Created $cfg - edit it with your NAS address and user"
fi
command -v sshpass >/dev/null || echo "Note: install sshpass for password auth (sudo apt install sshpass)"
echo "== done: nas_t ready"
