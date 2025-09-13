package com.surfscape.browser

import android.os.Bundle
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import androidx.appcompat.app.AppCompatActivity
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoSession
import org.mozilla.geckoview.GeckoView

class MainActivity : AppCompatActivity() {
    private lateinit var geckoView: GeckoView
    private lateinit var geckoSession: GeckoSession
    private lateinit var runtime: GeckoRuntime

    private var canGoBackFlag = false
    private var canGoForwardFlag = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        geckoView = findViewById(R.id.geckoView)
        val urlBar: EditText = findViewById(R.id.urlBar)
        val btnGo: Button = findViewById(R.id.btnGo)
        val btnBack: ImageButton = findViewById(R.id.btnBack)
        val btnForward: ImageButton = findViewById(R.id.btnForward)
        val btnReload: ImageButton = findViewById(R.id.btnReload)

        runtime = (application as SurfscapeApp).runtime
        geckoSession = GeckoSession()
        geckoSession.setNavigationDelegate(object : GeckoSession.NavigationDelegate {
            override fun onCanGoBack(session: GeckoSession, canGoBack: Boolean) {
                canGoBackFlag = canGoBack
                findViewById<ImageButton>(R.id.btnBack).isEnabled = canGoBack
            }

            override fun onCanGoForward(session: GeckoSession, canGoForward: Boolean) {
                canGoForwardFlag = canGoForward
                findViewById<ImageButton>(R.id.btnForward).isEnabled = canGoForward
            }
        })
        geckoSession.open(runtime)
        geckoView.setSession(geckoSession)

        fun loadUrl(raw: String) {
            val fixed = if (!raw.startsWith("http://") && !raw.startsWith("https://")) {
                "https://$raw"
            } else raw
            geckoSession.loadUri(fixed)
        }

        btnGo.setOnClickListener { loadUrl(urlBar.text.toString()) }
        btnBack.isEnabled = false
        btnForward.isEnabled = false
        btnBack.setOnClickListener { if (canGoBackFlag) geckoSession.goBack() }
        btnForward.setOnClickListener { if (canGoForwardFlag) geckoSession.goForward() }
        btnReload.setOnClickListener { geckoSession.reload() }

        urlBar.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO || (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_UP)) {
                loadUrl(urlBar.text.toString())
                true
            } else false
        }

        // Initial homepage
        loadUrl("example.org")
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
