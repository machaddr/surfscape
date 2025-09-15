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
import org.mozilla.geckoview.GeckoResult
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

    private val prefsName = "surfscape"
    private val keyLastUrl = "last_url"
    private val keyCrashCount = "crash_count"
    private val keyLastCrashTs = "last_crash_ts"
    private val crashBackoffWindowMs = 5_000L
    private val crashBackoffMax = 3

    // Delegates retained so we can reassign them to a new session cleanly
    private lateinit var navigationDelegate: GeckoSession.NavigationDelegate
    private lateinit var contentDelegate: ContentDelegate
    private lateinit var progressDelegate: ProgressDelegate

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
        navigationDelegate = object : GeckoSession.NavigationDelegate {
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
                    Log.d("Surfscape", "LocationChange: ${'$'}url")
                    runOnUiThread {
                        urlBar.setText(url)
                        statusBar.text = url
                        // Persist last successful location
                        getSharedPreferences(prefsName, MODE_PRIVATE)
                            .edit().putString(keyLastUrl, url).apply()
                    }
                }
            }
            // NOTE: onLoadRequest override removed because the current GeckoView
            // version (140.x) changed its signature/types. Default behavior (allow)
            // is acceptable for now; reintroduce later if filtering needed.
        }

        contentDelegate = object : ContentDelegate {
            override fun onTitleChange(session: GeckoSession, title: String?) {
                title?.let {
                    runOnUiThread { this@MainActivity.title = it }
                }
            }

            override fun onCrash(session: GeckoSession) {
                Log.e("Surfscape", "GeckoSession crashed; attempting restart")
                val prefs = getSharedPreferences(prefsName, MODE_PRIVATE)
                val now = System.currentTimeMillis()
                val lastTs = prefs.getLong(keyLastCrashTs, 0L)
                val count = prefs.getInt(keyCrashCount, 0)
                val newCount = if (now - lastTs < crashBackoffWindowMs) count + 1 else 1
                prefs.edit().putLong(keyLastCrashTs, now).putInt(keyCrashCount, newCount).apply()
                if (newCount > crashBackoffMax) {
                    Log.e("Surfscape", "Crash loop detected (>$crashBackoffMax in window); not restarting automatically.")
                    runOnUiThread {
                        Toast.makeText(this@MainActivity, "Browser crashed repeatedly; restart app.", Toast.LENGTH_LONG).show()
                    }
                    return
                }
                runOnUiThread {
                    try {
                        geckoSession.close()
                    } catch (_: Exception) { }
                    restartGeckoSession()
                }
            }
        }

        progressDelegate = object : ProgressDelegate {
            override fun onProgressChange(session: GeckoSession, progress: Int) {
                progressBar.visibility = if (progress in 1..99) ProgressBar.VISIBLE else ProgressBar.GONE
                progressBar.progress = progress
                if (progress in 1..99) {
                    Log.v("Surfscape", "Progress ${'$'}progress%")
                } else if (progress == 100) {
                    Log.d("Surfscape", "Page load complete")
                }
            }

            override fun onSecurityChange(session: GeckoSession, securityInfo: ProgressDelegate.SecurityInformation) {
                // Could update a lock icon later
            }

            override fun onPageStart(session: GeckoSession, url: String) {
                Log.d("Surfscape", "PageStart: ${'$'}url")
            }

            override fun onPageStop(session: GeckoSession, success: Boolean) {
                Log.d("Surfscape", "PageStop success=${'$'}success")
            }

        }
        initializeNewSession()

        fun loadUrl(raw: String) {
            if (!this::geckoSession.isInitialized || !geckoSession.isOpen) {
                Log.w("Surfscape", "loadUrl called before session ready; ignoring: ${'$'}raw")
                return
            }
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

        // Initial page: restore last URL if present
        val startUrl = getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(keyLastUrl, HOME_URL) ?: HOME_URL
        Log.d("Surfscape", "Initial navigation to ${'$'}startUrl")
        loadUrl(startUrl)
    }

    private fun restartGeckoSession() {
        Log.i("Surfscape", "Restarting GeckoSession")
        try { geckoSession.close() } catch (_: Exception) { }
        initializeNewSession()
        val restoreUrl = getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(keyLastUrl, HOME_URL) ?: HOME_URL
        geckoSession.loadUri(restoreUrl)
    }

    private fun initializeNewSession() {
        Log.d("Surfscape", "Initializing new GeckoSession ...")
        try {
            val session = GeckoSession()
            session.setNavigationDelegate(navigationDelegate)
            session.contentDelegate = contentDelegate
            session.progressDelegate = progressDelegate
            session.open(runtime)
            geckoView.setSession(session)
            geckoSession = session
            Log.d("Surfscape", "GeckoSession opened (active=${'$'}{session.isOpen}) runtimeMultiprocess=${'$'}{runtime.settings.useMultiprocess()} ")
        } catch (t: Throwable) {
            Log.e("Surfscape", "Failed to initialize GeckoSession", t)
            runOnUiThread {
                Toast.makeText(this, "Failed to start browser engine: ${'$'}{t.javaClass.simpleName}", Toast.LENGTH_LONG).show()
            }
            throw t
        }
    }

    override fun onPause() {
        if (this::geckoSession.isInitialized) {
            try { geckoSession.setActive(false) } catch (t: Throwable) { Log.w("Surfscape", "setActive(false) failed", t) }
        }
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        if (this::geckoSession.isInitialized) {
            try { geckoSession.setActive(true) } catch (t: Throwable) { Log.w("Surfscape", "setActive(true) failed", t) }
        }
    }

    override fun onLowMemory() {
        super.onLowMemory()
        Log.w("Surfscape", "System low memory signaled")
    }

    override fun onDestroy() {
        if (this::geckoSession.isInitialized) {
            geckoSession.close()
        }
        super.onDestroy()
    }
}
