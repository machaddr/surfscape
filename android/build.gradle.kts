plugins {
    id("com.android.application") version "8.6.1" apply false
    id("org.jetbrains.kotlin.android") version "2.2.0" apply false
}

// Pinned GeckoView version from maven.mozilla.org (metadata <latest>/<release>)
extra["geckoviewVersion"] = "142.0.20250827004350"
