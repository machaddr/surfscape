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
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            Log.e("Surfscape", "FATAL Uncaught exception in thread ${t.name}", e)
        }
        try {
            val settings = GeckoRuntimeSettings.Builder()
                //.remoteDebuggingEnabled(BuildConfig.DEBUG)
                .aboutConfigEnabled(BuildConfig.DEBUG)
                .build()
            runtime = GeckoRuntime.create(this, settings)
            Log.i("Surfscape", "GeckoRuntime initialized")
        } catch (t: Throwable) {
            Log.e("Surfscape", "Failed to initialize GeckoRuntime", t)
            // Re-throw so app doesn't continue in inconsistent state
            throw t
        }
    }
}
