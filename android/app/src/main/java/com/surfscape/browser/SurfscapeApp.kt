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
            val disableMultiprocess = System.getenv("SURFSCAPE_DISABLE_MULTIPROCESS") == "1"
            val builder = GeckoRuntimeSettings.Builder()
                .aboutConfigEnabled(BuildConfig.DEBUG)
                .arguments(arrayOf())
            // Newer GeckoView builds may no longer expose direct multiprocess toggle; if needed,
            // could rely on runtime arguments or prefs. For now we just log the intent.
            if (disableMultiprocess) {
                Log.w("Surfscape", "Requested single-process mode (env SURFSCAPE_DISABLE_MULTIPROCESS=1) but explicit API not available; continuing.")
            }
            val settings = builder.build()
            Log.i("Surfscape", "Creating GeckoRuntime (multiprocess=${'$'}{!disableMultiprocess}) ...")
            val start = System.currentTimeMillis()
            runtime = GeckoRuntime.create(this, settings)
            val dur = System.currentTimeMillis() - start
            Log.i("Surfscape", "GeckoRuntime initialized in ${'$'}dur ms")
        } catch (t: Throwable) {
            Log.e("Surfscape", "Failed to initialize GeckoRuntime", t)
            throw t
        }
    }
}
