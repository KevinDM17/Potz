@echo off
cd /d "%~dp0.."
python -B -m potz.probador
if errorlevel 1 pause
