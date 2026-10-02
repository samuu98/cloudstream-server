#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  umask 077
  printf 'AUTH_REQUIRED=false\nBIND_ADDRESS=127.0.0.1\nPORT=8000\nANDROID_RAM_MB=1536\n' > .env
fi
if [[ ! -f android/server.keystore ]]; then
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/android:/keys" eclipse-temurin:17-jdk-jammy keytool -genkeypair -keystore /keys/server.keystore -storepass changeit -keypass changeit -alias server -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=CloudStream Server Development'
fi
echo 'Configurazione pronta in .env. Avviare: docker compose up -d --build'
