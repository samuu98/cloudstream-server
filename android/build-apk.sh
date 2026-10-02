#!/usr/bin/env bash
set -euo pipefail
apk_url=https://raw.githubusercontent.com/recloudstream/cloudstream-archive/master/d77c856.apk
apk_sha=f1e08da61668c372548cbca5076f46aa9f3d2b5ffff5f890381df4de8fd93b88
curl -fL --retry 3 "$apk_url" -o /tmp/upstream.apk
echo "$apk_sha  /tmp/upstream.apk" | sha256sum -c -
curl -fL --retry 3 https://github.com/iBotPeaches/Apktool/releases/download/v2.11.1/apktool_2.11.1.jar -o /tmp/apktool.jar
python3 /src/android/apk_container.py extract
java -Xmx768m -jar /tmp/apktool.jar d -r -f /tmp/main.apk -o /tmp/app
python3 /src/android/patch_apk.py /tmp/app
mkdir -p /tmp/classes /tmp/bridge
javac -source 8 -target 8 -cp "$ANDROID_HOME/platforms/android-30/android.jar" -d /tmp/classes /src/android/ServerBridge.java
jar cf /tmp/bridge.jar -C /tmp/classes .
"$ANDROID_HOME/build-tools/35.0.0/d8" --min-api 26 --lib "$ANDROID_HOME/platforms/android-30/android.jar" --output /tmp/bridge /tmp/bridge.jar
java -Xmx768m -jar /tmp/apktool.jar b /tmp/app -o /tmp/main-patched.apk
python3 /src/android/apk_container.py assemble
test -f /src/android/server.keystore || { echo 'Eseguire bash setup.sh per creare la chiave di firma persistente'; exit 1; }
mkdir -p /out
"$ANDROID_HOME/build-tools/35.0.0/zipalign" -f -p 4 /tmp/server-unsigned.apk /tmp/aligned.apk
"$ANDROID_HOME/build-tools/35.0.0/apksigner" sign --ks /src/android/server.keystore --ks-pass pass:changeit --out /out/cloudstream-server.apk /tmp/aligned.apk
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify /out/cloudstream-server.apk
