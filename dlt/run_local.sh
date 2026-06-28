#!/bin/bash
#
# DLT Pipeline Local Runner
#
# This script helps run DLT pipelines locally outside of Docker.
# It loads environment variables from .env and activates the virtual environment.
#
# Usage:
#   ./run_local.sh jira_daily_projects.py
#   ./run_local.sh jira_daily_issues.py
#
# Prerequisites:
#   1. PostgreSQL Docker container must be running (ppm-postgres)
#   2. Virtual environment must be set up: python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if a script was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <script_name.py>"
    echo ""
    echo "Available scripts:"
    ls -1 jira_*.py 2>/dev/null | grep -v "__pycache__" | sed 's/^/  /'
    exit 1
fi

SCRIPT="$1"

# Check if script exists
if [ ! -f "$SCRIPT" ]; then
    echo "Error: Script '$SCRIPT' not found"
    exit 1
fi

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Please run:"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Check if .env exists
if [ ! -f "../.env" ]; then
    echo "Error: .env file not found in parent directory"
    exit 1
fi

echo "=========================================="
echo "DLT Pipeline Local Runner"
echo "=========================================="
echo "Script: $SCRIPT"
echo ""

# Load environment variables from .env
echo "Loading environment variables from .env..."
set -a
source "../.env"
set +a

# Run the script with venv python
echo "Running pipeline..."
echo ""
./venv/bin/python "$SCRIPT"
