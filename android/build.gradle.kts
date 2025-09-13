plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}

// GeckoView version alignment (ensure matching major/minor for arm64-v8a, x86_64 etc.)
// Use a stable GeckoView release version (match major Firefox ESR/Release version)
// See: https://maven.mozilla.org/maven2/org/mozilla/geckoview/geckoview/
extra["geckoviewVersion"] = "130.0.1"
