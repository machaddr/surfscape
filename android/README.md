# Surfscape Android (GeckoView)

This Android module provides a minimal GeckoView-based browser shell for Surfscape.

## Features
- GeckoView rendering engine
- Basic navigation: back, forward, reload
- URL bar with auto prepending of https://
- Intent filters to open http(s) links

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
- Homepage: edit the initial call to `loadUrl("example.org")` in `MainActivity.kt`.
- GeckoView version: update `geckoviewVersion` in root `build.gradle.kts` (use a matching channel version).
- App ID: change `applicationId` & `namespace` in `app/build.gradle.kts` and manifest package references.

## Notes
GeckoView Nightly/Beta/Release artifacts differ by version string; keep them aligned across all architectures (this config uses a single AAR which internally bundles required pieces).
