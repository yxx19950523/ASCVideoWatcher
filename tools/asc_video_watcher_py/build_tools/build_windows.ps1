$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")
py -m pip install -r requirements.txt
py -m PyInstaller `
  --noconfirm `
  --windowed `
  --name "ASC视频监控助手" `
  --collect-all playwright `
  --add-data "asc_video_watcher;asc_video_watcher" `
  main.py

Write-Host "Windows EXE: dist/ASC视频监控助手/ASC视频监控助手.exe"
