package com.surfscape.browser

import android.os.Bundle
import android.view.KeyEvent
import java.net.URLEncoder
import android.view.inputmethod.EditorInfo
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoSession
import org.mozilla.geckoview.GeckoView
import org.mozilla.geckoview.GeckoSession.ProgressDelegate

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
                url?.let {
                    urlBar.setText(it)
                    statusBar.text = it
                }
            }
        })

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

        // Initial homepage
        loadUrl(HOME_URL)
    }

    override fun onBackPressed() {
        if (this::geckoSession.isInitialized && canGoBackFlag) {
            geckoSession.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        if (this::geckoSession.isInitialized) {
            geckoSession.close()
        }
        super.onDestroy()
    }
}
