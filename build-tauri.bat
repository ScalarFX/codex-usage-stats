@echo off
setlocal
set "RUSTUP_HOME=D:\Apps\Rust\rustup"
set "CARGO_HOME=D:\Apps\Rust\cargo"
set "PATH=D:\Apps\Rust\cargo\bin;%PATH%"

if exist "D:\Apps\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
  call "D:\Apps\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)

cd /d "%~dp0"
npm run tauri:build
