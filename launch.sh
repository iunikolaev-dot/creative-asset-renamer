#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d "venv" ]; then
  echo "First run detected. Setting up..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
else
  source venv/bin/activate
fi
streamlit run app.py --server.headless true --browser.gatherUsageStats false
