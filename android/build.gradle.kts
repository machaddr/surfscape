plugins {
    id("com.android.application") version "8.6.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.20" apply false
}

// Pinned GeckoView latest release (from maven-metadata.xml <release>)
extra["geckoviewVersion"] = "140.0.20250707120347"
