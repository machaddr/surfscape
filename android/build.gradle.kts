plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}

// GeckoView version alignment (ensure matching major/minor for arm64-v8a, x86_64 etc.)
extra["geckoviewVersion"] = "126.0.20240611092435" // Example (corresponds to Firefox 126 nightly build id). Adjust to stable if desired.
