#!/bin/zsh
set -e
cd -- "${0:A:h}"
exec /opt/anaconda3/envs/web3aml/bin/python run_web.py
