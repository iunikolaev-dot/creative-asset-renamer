@echo off
cd /d "%~dp0"
if not exist "venv" (
  echo First run detected. Setting up...
  python -m venv venv
  call venv\Scripts\activate
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate
)
streamlit run app.py --server.headless true --browser.gatherUsageStats false
