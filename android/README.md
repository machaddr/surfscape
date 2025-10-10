# Surfscape Android (GeckoView)

This Android module provides the Surfscape mobile browser shell powered by GeckoView, mirroring the desktop app’s multi-tab workflow and navigation chrome.

## Features
- GeckoView rendering engine with crash recovery
- Surfscape-inspired UI chrome: pinned toolbar actions, bookmark toggle, Surfscape Copilot placeholder, and quick settings
- Lightweight tab strip with infinite tab support and per-tab state restoration
- Smart URL/search field that mirrors the desktop default search providers
- Adaptive APK splits per ABI, resource shrinking, and R8 minification for significantly smaller artifacts
- Intent filters to open HTTP(S) links from other Android apps

## Build Locally
```bash
cd android
./gradlew assembleDebug
# APK output: app/build/outputs/apk/debug/app-debug.apk
```
Open the project in Android Studio (recommended) to run on a device/emulator.

## GitHub Actions
Workflow: `.github/workflows/android-apk.yml` builds debug and release (unsigned) APKs and uploads artifacts. If signing secrets are present it signs the release APK.

### Optional Signing Secrets
Set these in repository settings for automatic signing:
- `ANDROID_KEYSTORE_BASE64`: Base64 of your keystore file (e.g. `base64 -w0 my-release-key.jks`)
- `ANDROID_KEYSTORE_PASSWORD`: Keystore password
- `ANDROID_KEY_ALIAS`: Alias name
- `ANDROID_KEY_PASSWORD`: Key password (often same as keystore password)

## Customizing
- Homepage & default search engine: tweak defaults in `MainActivity` (see `HOME_URL_DEFAULT` and `searchEngines`) or expose additional options via the settings dialog.
- GeckoView version: update `geckoviewVersion` in the root `build.gradle.kts` to match your desired Gecko channel.
- App ID: change `applicationId` & `namespace` in `app/build.gradle.kts` and manifest package references.
- Toolbar icons: vector assets live under `app/src/main/res/drawable`. Replace or extend as needed.

## Notes
GeckoView Nightly/Beta/Release artifacts differ by version string; keep them aligned across all architectures (this config uses a single AAR with Gradle ABI splits to emit per-architecture APKs).
