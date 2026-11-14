@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto erro
)
".venv\Scripts\python.exe" -c "import PySide6.QtCharts, openpyxl" 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto erro
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto erro
exit /b 0

:erro
echo Nao foi possivel abrir o Profits. Confira a mensagem acima.
pause
exit /b 1
