plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}

// GeckoView version selection: allow CI/user override via GECKOVIEW_VERSION env, fallback sequence.
val fallbackGeckoVersions = listOf(
    "132.0", // try latest release (update periodically)
    "131.0",
    "130.0",
    "129.0"
)
val envOverride = System.getenv("GECKOVIEW_VERSION")?.trim().orEmpty()
// Prefer explicit override; otherwise first fallback (actual existence is checked in workflow fetch step).
extra["geckoviewVersion"] = (if (envOverride.isNotBlank()) envOverride else fallbackGeckoVersions.first())
