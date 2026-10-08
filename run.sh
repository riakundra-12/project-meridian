#!/bin/bash

set -e

if [ ! -d ".venv" ]; then
  echo "Virtual environment not found."
  echo "Create it with: python3 -m venv .venv"
  exit 1
fi

source .venv/bin/activate

python -m src.knowledge.build_knowledge

streamlit run app.py