#!/usr/bin/env bash
# 一键出片：配音 → 音效时间表 → 混音 → 逐帧渲染（带字幕 / 无字幕）→ 合成 MP4
# 用法: VIDEO_DIR=videos/<名称> MODELS=<语音模型目录> [ENGINE=gemini|kokoro] tools/build.sh
#      已有 build/voice.wav 时可设 SKIP_TTS=1 跳过配音
set -euo pipefail
TOOLS="$(cd "$(dirname "$0")" && pwd)"
export VIDEO_DIR="$(cd "${VIDEO_DIR:?请设置 VIDEO_DIR，如 videos/fenshu}" && pwd)"
cd "$VIDEO_DIR"
TITLE="$(python3 -c "import json;print(json.load(open('script/narration.json',encoding='utf-8'))['title'])")"
[ "${SKIP_TTS:-0}" = 1 ] || python3 "$TOOLS/tts.py" --engine "${ENGINE:-gemini}" --models "${MODELS:?请设置 MODELS 为语音模型目录}"
node "$TOOLS/render.mjs" --stills 0 >/dev/null          # 只为导出 build/cues.json
python3 "$TOOLS/mix.py"
node "$TOOLS/render.mjs" --sub 1 --out build/v_sub.mp4 &
node "$TOOLS/render.mjs" --sub 0 --out build/v_nosub.mp4 &
wait
mux() {  # 兼容 PowerPoint / WPS / 希沃：H.264 High@4.1、yuv420p、AAC 48kHz、faststart
  ffmpeg -y -loglevel error -i "$1" -i build/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k \
    -movflags +faststart -metadata title="$TITLE" -shortest "$2"
}
mux build/v_sub.mp4 "output/${TITLE}（带字幕）.mp4"
mux build/v_nosub.mp4 "output/${TITLE}（无字幕）.mp4"
ls -la output
