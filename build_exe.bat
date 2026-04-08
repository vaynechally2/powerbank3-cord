@echo off
setlocal

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m pip install pyinstaller

pyinstaller --noconfirm --onefile --windowed --name PageMonitorWin11 main.py

echo.
echo Build complete. EXE is in dist\PageMonitorWin11.exe
pause
