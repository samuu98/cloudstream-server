#!/usr/bin/env bash
set -euo pipefail
if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  echo 'Serve un host Linux x86_64 con /dev/kvm accessibile. Vedere README.md.' >&2
  exit 1
fi
mkdir -p "$ANDROID_AVD_HOME"
if [[ ! -f "$ANDROID_AVD_HOME/cloudstream.ini" ]]; then
  echo no | avdmanager create avd --force --name cloudstream --package 'system-images;android-30;google_apis;x86_64' --device pixel_2
fi
adb start-server
# A container restart can leave stale emulator PID/lock files in the persistent
# AVD. This volume belongs exclusively to this one Android service.
python3 - <<'PY'
import os, pathlib, shutil
avd=pathlib.Path(os.environ['ANDROID_AVD_HOME'])/'cloudstream.avd'
for lock in avd.glob('*.lock'):
    if lock.is_dir(): shutil.rmtree(lock)
    else: lock.unlink()
PY
emulator -avd cloudstream -no-window -no-audio -no-boot-anim -no-snapshot -no-metrics -gpu swiftshader_indirect -accel on -memory "$ANDROID_RAM_MB" -cores 2 -partition-size 2048 > /data/emulator.log 2>&1 &
emulator_pid=$!
cleanup() { adb emu kill >/dev/null 2>&1 || true; kill "$emulator_pid" 2>/dev/null || true; wait "$emulator_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 0' TERM INT
deadline=$((SECONDS+300))
until [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; do
  if ! kill -0 "$emulator_pid" 2>/dev/null || ((SECONDS>deadline)); then tail -100 /data/emulator.log; exit 1; fi
  sleep 2
done
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
adb shell settings put system screen_off_timeout 2147483647
adb shell input keyevent 82
adb install -r /opt/cloudstream-server.apk
adb forward tcp:18181 tcp:18181
# Android API is never exposed; the authenticated gateway joins the same network namespace.
while kill -0 "$emulator_pid" 2>/dev/null; do
  if ! curl -fsS --max-time 3 http://127.0.0.1:18181/health >/dev/null; then
    adb shell am start -n com.lagradost.cloudstream3.prerelease/com.lagradost.cloudstream3.ui.account.AccountSelectActivity || true
  fi
  sleep 10 & wait $! || true
done
exit 1
