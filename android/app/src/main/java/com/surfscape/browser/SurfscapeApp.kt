package com.surfscape.browser

import android.app.Application
import android.util.Log
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoRuntimeSettings
import com.surfscape.browser.BuildConfig

class SurfscapeApp : Application() {
    lateinit var runtime: GeckoRuntime
        private set

    override fun onCreate() {
        super.onCreate()
        // Prepare runtime settings (can be expanded with prefs later)
        val settings = GeckoRuntimeSettings.Builder()
            //.remoteDebuggingEnabled(BuildConfig.DEBUG) // Uncomment if needed
            .aboutConfigEnabled(BuildConfig.DEBUG)
            .build()
        runtime = GeckoRuntime.create(this, settings)
        Log.i("Surfscape", "GeckoRuntime initialized")
    }
}
