@echo off
echo ===============================================
echo    Rally to Jira Reverse Sync GUI
echo ===============================================
echo.
echo Starting GUI application...
echo.

cd /d "%~dp0"

python rally_jira_reverse_sync_gui.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error: Application failed to start
    echo.
    echo Possible solutions:
    echo 1. Install Python requirements: pip install -r requirements.txt
    echo 2. Check Python installation
    echo 3. Check the log files for more details
    echo.
    pause
)

echo.
echo Application closed.
pause