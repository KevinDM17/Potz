@echo off
setlocal
pushd "%~dp0.."
chcp 65001 >nul

set "arena_bin=arena\pokerfight-arena-participantes\bin"
if not exist "%arena_bin%\arena.exe" goto falta_arena
if not exist "%arena_bin%\aleatorio.exe" goto falta_arena
if not exist "%arena_bin%\estadistico.exe" goto falta_arena
where python.exe >nul 2>&1
if errorlevel 1 goto falta_python

python -B -m potz.visor --en-vivo
set "resultado=%errorlevel%"
if "%resultado%"=="0" goto salir
goto fin

:falta_arena
echo Falta compilar la arena. Consulta el README y, desde arena\pokerfight-arena-participantes, ejecuta:
echo   go build -o bin/ ./cmd/arena ./bots/aleatorio ./bots/estadistico
set "resultado=1"
goto fin

:falta_python
echo Windows no encuentra Python en la terminal.
set "resultado=1"

:fin
echo.
pause
:salir
popd
exit /b %resultado%
