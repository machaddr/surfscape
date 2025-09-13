package com.surfscape.browser

import android.app.Application
import org.mozilla.geckoview.GeckoRuntime

class SurfscapeApp : Application() {
    lateinit var runtime: GeckoRuntime
        private set

    override fun onCreate() {
        super.onCreate()
        runtime = GeckoRuntime.create(this)
    }
}
