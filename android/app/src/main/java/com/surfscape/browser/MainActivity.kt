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
    private var firstProgressTimestamp: Long = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Check if GeckoRuntime is available before proceeding
        try {
            val app = application as SurfscapeApp
            // Try to access runtime to see if it's initialized
            app.runtime
        } catch (e: UninitializedPropertyAccessException) {
            Log.e("Surfscape", "GeckoRuntime not initialized - cannot start browser", e)
            Toast.makeText(this, "Browser engine not available", Toast.LENGTH_LONG).show()
            finish()
            return
        } catch (e: Exception) {
            Log.e("Surfscape", "Failed to access application runtime", e)
            finish()
            return
        }

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
                    .detectActivityLeaks()
                    .penaltyLog()
                    .build()
            )
        }

        geckoView = findViewById(R.id.geckoView)
        geckoView.viewTreeObserver.addOnGlobalLayoutListener {
            val w = geckoView.width
            val h = geckoView.height
            if (w > 0 && h > 0) {
                Log.d("Surfscape", "GeckoView layout size=${w}x${h} visible=${geckoView.isShown}")
            }
        }
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
                if (url != null && !isFinishing && !isDestroyed) {
                    Log.d("Surfscape", "LocationChange: ${url}")
                    runOnUiThread {
                        if (!isFinishing && !isDestroyed) {
                            urlBar.setText(url)
                            statusBar.text = url
                            // Persist last successful location
                            getSharedPreferences(prefsName, MODE_PRIVATE)
                                .edit().putString(keyLastUrl, url).apply()
                        }
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
                    if (!isFinishing && !isDestroyed) {
                        runOnUiThread {
                            if (!isFinishing && !isDestroyed) {
                                this@MainActivity.title = it
                            }
                        }
                    }
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
                    if (!isFinishing && !isDestroyed) {
                        runOnUiThread {
                            if (!isFinishing && !isDestroyed) {
                                Toast.makeText(this@MainActivity, "Browser crashed repeatedly; restart app.", Toast.LENGTH_LONG).show()
                            }
                        }
                    }
                    return
                }
                if (!isFinishing && !isDestroyed) {
                    runOnUiThread {
                        if (!isFinishing && !isDestroyed) {
                            try {
                                geckoSession.close()
                            } catch (_: Exception) { }
                            restartGeckoSession()
                        }
                    }
                }
            }
        }

        progressDelegate = object : ProgressDelegate {
            override fun onProgressChange(session: GeckoSession, progress: Int) {
                if (progress > 0 && firstProgressTimestamp == 0L) {
                    firstProgressTimestamp = System.currentTimeMillis()
                    Log.d("Surfscape", "First progress >0 at ${firstProgressTimestamp}")
                }
                progressBar.visibility = if (progress in 1..99) ProgressBar.VISIBLE else ProgressBar.GONE
                progressBar.progress = progress
                if (progress in 1..99) {
                    Log.v("Surfscape", "Progress ${progress}%")
                } else if (progress == 100) {
                    val delta = if (firstProgressTimestamp != 0L) System.currentTimeMillis() - firstProgressTimestamp else -1
                    Log.d("Surfscape", "Page load complete (deltaFromFirstProgress=${delta}ms)")
                }
            }

            override fun onSecurityChange(session: GeckoSession, securityInfo: ProgressDelegate.SecurityInformation) {
                // Could update a lock icon later
            }

            override fun onPageStart(session: GeckoSession, url: String) {
                Log.d("Surfscape", "PageStart: ${url}")
            }

            override fun onPageStop(session: GeckoSession, success: Boolean) {
                Log.d("Surfscape", "PageStop success=${success}")
            }

        }
        initializeNewSession()

        fun loadUrl(raw: String) {
            if (!this::geckoSession.isInitialized || !geckoSession.isOpen) {
                Log.w("Surfscape", "loadUrl called before session ready; ignoring: ${raw}")
                return
            }
            if (!this::runtime.isInitialized) {
                Log.w("Surfscape", "loadUrl called before runtime ready; ignoring: ${raw}")
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

        // Back press handling - use new API if available, fallback for older versions
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
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
        }

        // Initial page: restore last URL if present
        val selfTest = System.getenv("SURFSCAPE_SELFTEST") == "1"
        val startUrl = getSharedPreferences(prefsName, MODE_PRIVATE)
            .getString(keyLastUrl, HOME_URL) ?: HOME_URL
        if (selfTest) {
            val testHtml = "<html><body style='font-family:sans-serif'><h3>Surfscape Self-Test</h3><p>If you can read this, GeckoView rendered a local page.</p><p>User Agent should appear below after JS runs.</p><div id='ua'></div><script>document.getElementById('ua').textContent = navigator.userAgent;</script></body></html>"
            val dataUrl = "data:text/html;base64," + android.util.Base64.encodeToString(testHtml.toByteArray(), android.util.Base64.NO_WRAP)
            Log.d("Surfscape", "Self-test mode: loading inline data URL then will navigate to ${startUrl}")
            geckoSession.loadUri(dataUrl)
            // Chain real navigation after short delay
            android.os.Handler(mainLooper).postDelayed({
                if (this::geckoSession.isInitialized && geckoSession.isOpen) {
                    Log.d("Surfscape", "Self-test follow-up: navigating to ${startUrl}")
                    geckoSession.loadUri(startUrl)
                }
            }, 1500)
        } else {
            Log.d("Surfscape", "Initial navigation to ${startUrl}")
            loadUrl(startUrl)
        }
    }

    private fun restartGeckoSession() {
        Log.i("Surfscape", "Restarting GeckoSession")
        try { geckoSession.close() } catch (_: Exception) { }
        try {
            initializeNewSession()
            val restoreUrl = getSharedPreferences(prefsName, MODE_PRIVATE)
                .getString(keyLastUrl, HOME_URL) ?: HOME_URL
            geckoSession.loadUri(restoreUrl)
        } catch (e: Exception) {
            Log.e("Surfscape", "Failed to restart GeckoSession", e)
            runOnUiThread {
                Toast.makeText(this, "Failed to restart browser", Toast.LENGTH_SHORT).show()
            }
        }
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
            Log.d("Surfscape", "GeckoSession opened (active=${session.isOpen})")
            // GeckoView 140: evaluateJS API removed/changed. Skipping direct UA eval.
            // If needed later, use a temporary about:blank load and ContentDelegate to inspect UA via headers
            // or inject a WebExtension. For now just log that the session is open.
            Log.d("Surfscape", "GeckoSession JS eval skipped (API removed).")

            // Stage 1: load about:blank explicitly and set a watchdog.
            try {
                // Small delay to ensure session is fully ready
                android.os.Handler(mainLooper).postDelayed({
                    if (this::geckoSession.isInitialized && geckoSession === session && geckoSession.isOpen) {
                        session.loadUri("about:blank")
                        Log.d("Surfscape", "Loaded about:blank as staging page")
                    }
                }, 100)
            } catch (e: Throwable) {
                Log.w("Surfscape", "Failed to load about:blank staging page", e)
            }
            // Watchdog: if we never get a progress >0 within 5s, log a hard warning.
            android.os.Handler(mainLooper).postDelayed({
                if (this::geckoSession.isInitialized && geckoSession === session) {
                    // If still on about:blank and no delegates fired, we may have a rendering stall.
                    Log.w("Surfscape", "Watchdog: no navigation progress after 5s; possible rendering stall. Consider setting SURFSCAPE_FORCE_SOFTWARE=1")
                }
            }, 5000)
        } catch (t: Throwable) {
            Log.e("Surfscape", "Failed to initialize GeckoSession", t)
            runOnUiThread {
                Toast.makeText(this, "Failed to start browser engine: ${t.javaClass.simpleName}", Toast.LENGTH_LONG).show()
                // Don't finish() immediately - give user a chance to see the error
                android.os.Handler(mainLooper).postDelayed({
                    finish()
                }, 3000)
            }
            // Don't re-throw - let the activity handle the error gracefully
            return
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
        try {
            if (this::geckoSession.isInitialized) {
                geckoSession.close()
            }
        } catch (e: Exception) {
            Log.w("Surfscape", "Error closing GeckoSession", e)
        }
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        Log.d("Surfscape", "Window focus changed: hasFocus=${hasFocus} sessionActive=${if (this::geckoSession.isInitialized) geckoSession.isOpen else false}")
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (this::geckoSession.isInitialized && canGoBackFlag) {
            geckoSession.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
