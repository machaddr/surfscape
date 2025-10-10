# Surfscape Android (Chromium WebView)

This Android module delivers the Surfscape mobile experience on top of the system Chromium WebView, mirroring the desktop browser’s productivity-first workflow.

## Features
- Chromium WebView engine with hardened defaults, file uploads, and smart external intent routing
- Surfscape-inspired UI chrome: pinned toolbar actions, bookmark toggle, Surfscape Copilot placeholder, and quick settings
- Lightweight tab strip with infinite tab support and per-tab state restoration
- Smart URL/search field that mirrors the desktop default search providers
- Lean universal APK with resource shrinking and R8 minification for compact installs
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
- WebView behaviour: adjust `configureWebView` inside `MainActivity` to toggle features (dark mode, UA overrides, media playback rules, etc.).
- App ID: change `applicationId` & `namespace` in `app/build.gradle.kts` and manifest package references.
- Toolbar icons: vector assets live under `app/src/main/res/drawable`. Replace or extend as needed.

## Notes
- Android System WebView updates land via the Play Store; keeping it current unlocks automatic engine upgrades.
- `androidx.webkit:webkit` is bundled to access modern WebView APIs (user agent negotiation, metrics, etc.).
