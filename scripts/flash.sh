#!/bin/bash
# Compile the sketch, flash it over USB and tail the serial output.
# Wraps the arduino-cli workflow from runbook §9.1 (including its workarounds
# for the blocked downloads.arduino.cc — the toolchain setup there is a
# one-time prerequisite, this script only runs the everyday cycle).
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, sketch lives in esp32/

PORT="${1:-/dev/ttyUSB0}"
FQBN=esp32:esp32:esp32
BAUD=9600   # must match Serial.begin() in the sketch

# arduino-cli installs to ~/.local/bin, which not every shell has on PATH.
export PATH="$HOME/.local/bin:$PATH"

# The two usual reasons a flash fails, checked up front with clearer messages
# than the toolchain gives.
if [ ! -f esp32/config.h ]; then
    echo "esp32/config.h missing: copy esp32/config_example.h and fill it in" >&2
    exit 1
fi
if [ ! -r "$PORT" ] || [ ! -w "$PORT" ]; then
    echo "$PORT is not accessible: plug the board in, then either" >&2
    echo "  sudo chmod a+rw $PORT           (until re-plug)" >&2
    echo "  sudo usermod -aG dialout \$USER  (permanent, re-login)" >&2
    exit 1
fi

arduino-cli compile --fqbn "$FQBN" esp32/
arduino-cli upload -p "$PORT" --fqbn "$FQBN" esp32/

# arduino-cli monitor needs a "builtin" tool downloads.arduino.cc won't serve
# us; raw termios does the same job. Ctrl-C to stop.
echo "--- serial monitor on $PORT @ $BAUD (Ctrl-C to exit) ---"
stty -F "$PORT" "$BAUD" raw -echo
exec cat "$PORT"
