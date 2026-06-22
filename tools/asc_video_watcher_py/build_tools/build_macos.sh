#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
python3 -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "ASC视频监控助手" \
  --collect-all playwright \
  --add-data "asc_video_watcher:asc_video_watcher" \
  main.py

echo "macOS APP: dist/ASC视频监控助手.app"
