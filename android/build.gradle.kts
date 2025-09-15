plugins {
    id("com.android.application") version "8.13.0" apply false
    // Downgraded Kotlin to 2.0.20 for AGP 8.6.1 compatibility
    id("org.jetbrains.kotlin.android") version "2.0.20" apply false
}

// Pinned GeckoView latest release (from maven-metadata.xml <release>)
extra["geckoviewVersion"] = "141.0.20250806102122"
