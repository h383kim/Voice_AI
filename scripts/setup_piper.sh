#!/usr/bin/env bash
# Download a Piper voice model for the piper-tts pip package.
# piper-tts (installed in the venv) provides the engine; it only needs a voice
# model: an .onnx file and its matching .onnx.json config.
#
# Default voice: en_US-lessac-medium. Edit VOICE_* below to use another voice.
# Browse voices: https://huggingface.co/rhasspy/piper-voices
set -euo pipefail

cd "$(dirname "$0")/.."

DEST="models/piper"
mkdir -p "$DEST"

VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
ONNX="en_US-lessac-medium.onnx"
JSON="en_US-lessac-medium.onnx.json"

echo "Downloading Piper voice model into $DEST ..."
curl -L --fail -o "$DEST/$ONNX" "$VOICE_BASE/$ONNX?download=true"
curl -L --fail -o "$DEST/$JSON" "$VOICE_BASE/$JSON?download=true"

echo "Done. Voice model at $DEST/$ONNX"
echo "Test synthesis (requires the venv with piper-tts active):"
echo "  echo 'Hello from Piper' | python -m piper -m $DEST/$ONNX -f /tmp/piper_test.wav"
