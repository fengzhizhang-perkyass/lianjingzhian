#!/bin/zsh
set -e
cd -- "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python run_web.py
else
  exec python3 run_web.py
fi
