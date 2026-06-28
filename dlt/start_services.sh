#!/bin/bash
# Start DLT services: Streamlit dashboard and DLT workspace

echo "Starting DLT services..."

# Create logs directory
mkdir -p /app/logs

# Start Streamlit dashboard on port 8501 (background)
echo "Starting Streamlit dashboard on port 8501..."
streamlit run /app/dashboard.py --server.port=8501 --server.address=0.0.0.0 &

# Start DLT workspace on port 2718 (background)
echo "Starting DLT workspace on port 2718..."
cd /var/dlt/pipelines && dlt workspace --host 0.0.0.0 --port 2718 &

echo "Services started!"
echo "  - Streamlit Dashboard: http://localhost:8501"
echo "  - DLT Workspace: http://localhost:2718"
echo ""

# Keep container running
tail -f /dev/null
