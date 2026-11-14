@echo off
cd /d "%~dp0.."
python -B -m potz.visor
if errorlevel 1 pause
