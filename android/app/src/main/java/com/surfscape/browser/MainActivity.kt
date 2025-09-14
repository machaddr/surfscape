package com.surfscape.browser

import android.os.Build
import android.os.Bundle
import android.os.StrictMode
import android.view.KeyEvent
import java.net.URLEncoder
import android.view.inputmethod.EditorInfo
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoSession
import org.mozilla.geckoview.GeckoView
import org.mozilla.geckoview.GeckoSession.ProgressDelegate
import org.mozilla.geckoview.GeckoSession.ContentDelegate
import android.util.Log
import androidx.activity.OnBackPressedCallback
import com.surfscape.browser.BuildConfig

class MainActivity : AppCompatActivity() {
    private lateinit var geckoView: GeckoView
    private lateinit var geckoSession: GeckoSession
    private lateinit var runtime: GeckoRuntime

    private var canGoBackFlag = false
    private var canGoForwardFlag = false

    private val HOME_URL = "https://html.duckduckgo.com"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Enable StrictMode in debug builds to surface potential main-thread violations.
        if (BuildConfig.DEBUG) {
            StrictMode.setThreadPolicy(
                StrictMode.ThreadPolicy.Builder()
                    .detectAll()
                    .penaltyLog()
                    .build()
            )
            StrictMode.setVmPolicy(
                StrictMode.VmPolicy.Builder()
                    .detectLeakedClosableObjects()
                    .penaltyLog()
                    .build()
            )
        }

        geckoView = findViewById(R.id.geckoView)
        val urlBar: EditText = findViewById(R.id.urlBar)
        val btnGo: ImageButton = findViewById(R.id.btnGo)
        val btnBack: ImageButton = findViewById(R.id.btnBack)
        val btnForward: ImageButton = findViewById(R.id.btnForward)
        val btnReload: ImageButton = findViewById(R.id.btnReload)
        val btnHome: ImageButton = findViewById(R.id.btnHome)
        val progressBar: ProgressBar = findViewById(R.id.progressBar)
        val statusBar: TextView = findViewById(R.id.statusBar)

        runtime = (application as SurfscapeApp).runtime
        geckoSession = GeckoSession()
        geckoSession.setNavigationDelegate(object : GeckoSession.NavigationDelegate {
            override fun onCanGoBack(session: GeckoSession, canGoBack: Boolean) {
                canGoBackFlag = canGoBack
                btnBack.isEnabled = canGoBack
            }

            override fun onCanGoForward(session: GeckoSession, canGoForward: Boolean) {
                canGoForwardFlag = canGoForward
                btnForward.isEnabled = canGoForward
            }

            override fun onLocationChange(
                session: GeckoSession,
                url: String?,
                permissions: MutableList<GeckoSession.PermissionDelegate.ContentPermission>,
                hasUserGesture: Boolean
            ) {
                if (url != null) {
                    runOnUiThread {
                        urlBar.setText(url)
                        statusBar.text = url
                    }
                }
            }
        })

        geckoSession.contentDelegate = object : ContentDelegate {
            override fun onTitleChange(session: GeckoSession, title: String?) {
                title?.let {
                    runOnUiThread { this@MainActivity.title = it }
                }
            }

            override fun onCrash(session: GeckoSession) {
                Log.e("Surfscape", "GeckoSession crashed; attempting restart")
                runOnUiThread {
                    try {
                        geckoSession.close()
                    } catch (_: Exception) { }
                    restartGeckoSession()
                }
            }
        }

        geckoSession.progressDelegate = object : ProgressDelegate {
            override fun onProgressChange(session: GeckoSession, progress: Int) {
                progressBar.visibility = if (progress in 1..99) ProgressBar.VISIBLE else ProgressBar.GONE
                progressBar.progress = progress
            }

            override fun onSecurityChange(session: GeckoSession, securityInfo: ProgressDelegate.SecurityInformation) {
                // Could update a lock icon later
            }
        }
    geckoSession.open(runtime)
    geckoView.setSession(geckoSession)

        fun loadUrl(raw: String) {
            val trimmed = raw.trim()
            if (trimmed.isEmpty()) return
            val isLikelyUrl = Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://").containsMatchIn(trimmed) ||
                    (trimmed.contains('.') && !trimmed.contains(' '))
            val target = if (isLikelyUrl) {
                if (Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://").containsMatchIn(trimmed)) trimmed else "https://$trimmed"
            } else {
                val q = URLEncoder.encode(trimmed, Charsets.UTF_8.name())
                // Use DuckDuckGo HTML endpoint for lightweight results
                "https://html.duckduckgo.com/html/?q=$q"
            }
            Log.d("Surfscape", "Loading URL: $target")
            geckoSession.loadUri(target)
        }

        btnGo.setOnClickListener { loadUrl(urlBar.text.toString()) }
        btnBack.isEnabled = false
        btnForward.isEnabled = false
        btnBack.setOnClickListener { if (canGoBackFlag) geckoSession.goBack() }
        btnForward.setOnClickListener { if (canGoForwardFlag) geckoSession.goForward() }
        btnReload.setOnClickListener { geckoSession.reload() }
        btnHome.setOnClickListener { geckoSession.loadUri(HOME_URL) }

        urlBar.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO || (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_UP)) {
                loadUrl(urlBar.text.toString())
                true
            } else false
        }

        // Back press handling via dispatcher (replaces deprecated onBackPressed())
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (this@MainActivity::geckoSession.isInitialized && canGoBackFlag) {
                    geckoSession.goBack()
                } else {
                    // Disable callback temporarily to allow system default
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        // Initial homepage
        loadUrl(HOME_URL)
    }

    private fun restartGeckoSession() {
        val newSession = GeckoSession()
        // Reapply delegates (minimal duplication - could be refactored later)
        newSession.setNavigationDelegate(geckoSession.navigationDelegate)
        newSession.contentDelegate = geckoSession.contentDelegate
        newSession.progressDelegate = geckoSession.progressDelegate
        try {
            newSession.open(runtime)
            geckoView.setSession(newSession)
            geckoSession = newSession
            Log.i("Surfscape", "GeckoSession restarted")
            geckoSession.loadUri(HOME_URL)
        } catch (t: Throwable) {
            Log.e("Surfscape", "Failed to restart GeckoSession", t)
        }
    }

    override fun onDestroy() {
        if (this::geckoSession.isInitialized) {
            geckoSession.close()
        }
        super.onDestroy()
    }
}
