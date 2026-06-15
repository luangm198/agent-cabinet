@echo off
chcp 65001 >nul
title Log in to Claude for the AI Team Meeting app
echo.
echo ============================================================
echo   LOG IN WITH YOUR CLAUDE ACCOUNT (no API key needed)
echo   Requires a Claude Code Max subscription (5x or 20x).
echo ============================================================
echo.
echo  A browser will open. Click "Authorize / Approve"
echo  with the Claude account you use.
echo.
echo  When finished, close this window and go back to the app.
echo.
echo ------------------------------------------------------------
echo.
set "CLAUDE_EXE="
for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\*\claude.exe" 2^>nul') do set "CLAUDE_EXE=%%i"
if defined CLAUDE_EXE (
  "%CLAUDE_EXE%" auth login
) else (
  echo Could not find claude.exe automatically. Trying 'claude' on PATH...
  claude auth login
)
echo.
echo ------------------------------------------------------------
echo  Done. Close this window and go back to the app.
echo.
pause
