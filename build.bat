@echo off
rem Builds dist\UniRooms.exe (requires Python venv in .venv and Node.js)
cd /d %~dp0
if not exist .venv (
    python -m venv .venv || exit /b 1
    .venv\Scripts\pip install -r requirements.txt || exit /b 1
)
pushd frontend
call npm ci || exit /b 1
call npm run build || exit /b 1
popd
.venv\Scripts\python -m pytest -q || exit /b 1
.venv\Scripts\pyinstaller --noconfirm --clean UniRooms.spec || exit /b 1
echo.
echo Done: dist\UniRooms.exe
