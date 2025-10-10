package com.surfscape.browser

import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.StrictMode
import android.util.Log
import android.util.Patterns
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.content.res.AppCompatResources
import androidx.core.content.ContextCompat
import androidx.core.view.children
import androidx.core.view.isVisible
import androidx.core.widget.addTextChangedListener
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.surfscape.browser.databinding.ActivityMainBinding
import com.surfscape.browser.BuildConfig
import org.mozilla.geckoview.GeckoRuntime
import org.mozilla.geckoview.GeckoSession
import org.mozilla.geckoview.GeckoSession.ContentDelegate
import org.mozilla.geckoview.GeckoSession.ProgressDelegate
import java.net.URLEncoder
import java.util.concurrent.atomic.AtomicLong

class MainActivity : AppCompatActivity() {

    private data class SearchEngine(val id: String, val label: String, val queryTemplate: String)

    private data class BrowserTab(
        val id: Long,
        var session: GeckoSession,
        var title: String,
        var lastUrl: String,
        var canGoBack: Boolean = false,
        var canGoForward: Boolean = false,
        val isPrivate: Boolean = false,
        var lastProgress: Int = 0,
        var statusText: String = ""
    )

    private lateinit var binding: ActivityMainBinding
    private lateinit var runtime: GeckoRuntime
    private lateinit var searchEngines: List<SearchEngine>

    private val tabIdSequence = AtomicLong(0)
    private val tabs = mutableListOf<BrowserTab>()
    private var activeTabId: Long? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private var ignoreUrlBarChange = false

    private val prefs by lazy { getSharedPreferences(PREFS_NAME, MODE_PRIVATE) }

    private val activeTab: BrowserTab?
        get() = tabs.firstOrNull { it.id == activeTabId }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enforceStrictModeIfDebug()

        runtime = try {
            (application as SurfscapeApp).runtime
        } catch (t: Throwable) {
            Log.e(TAG, "Unable to obtain GeckoRuntime", t)
            Toast.makeText(this, "Browser engine not available", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        setSupportActionBar(binding.topToolbar)
        supportActionBar?.setDisplayShowTitleEnabled(false)
        binding.topToolbar.title = ""
        binding.tabStrip.isSingleSelection = true

        window.statusBarColor = ContextCompat.getColor(this, R.color.purple_700)

        searchEngines = listOf(
            SearchEngine(
                id = "duckduckgo",
                label = getString(R.string.search_engine_duckduckgo),
                queryTemplate = "https://html.duckduckgo.com/html/?q=%s"
            ),
            SearchEngine(
                id = "startpage",
                label = getString(R.string.search_engine_startpage),
                queryTemplate = "https://www.startpage.com/do/search?q=%s"
            ),
            SearchEngine(
                id = "google",
                label = getString(R.string.search_engine_google),
                queryTemplate = "https://www.google.com/search?q=%s"
            ),
            SearchEngine(
                id = "brave",
                label = getString(R.string.search_engine_brave),
                queryTemplate = "https://search.brave.com/search?q=%s"
            )
        )

        setupUiListeners()
        updateNavigationState()
        updateBookmarkIcon()
        updateStatus(getString(R.string.status_ready))
        restoreOrCreateInitialTab()
    }

    private fun enforceStrictModeIfDebug() {
        if (!BuildConfig.DEBUG) return
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

    private fun setupUiListeners() {
        binding.urlBar.addTextChangedListener {
            if (!ignoreUrlBarChange) {
                updateBookmarkIcon()
            }
        }
        binding.urlBar.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_GO) {
                submitUrlFromBar()
                true
            } else {
                false
            }
        }
        binding.urlBar.setOnKeyListener { _, keyCode, event ->
            if (keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_UP) {
                submitUrlFromBar()
                true
            } else {
                false
            }
        }

        binding.btnBack.setOnClickListener {
            activeTab?.takeIf { it.canGoBack }?.session?.goBack()
        }
        binding.btnForward.setOnClickListener {
            activeTab?.takeIf { it.canGoForward }?.session?.goForward()
        }
        binding.btnReload.setOnClickListener {
            activeTab?.session?.reload()
        }
        binding.btnHome.setOnClickListener {
            loadInActiveTab(homepageUrl())
        }
        binding.btnNewTab.setOnClickListener {
            createTab(initialUrl = homepageUrl(), select = true)
        }
        binding.btnBookmark.setOnClickListener { toggleBookmark() }
        binding.btnAi.setOnClickListener { showAiPlaceholder() }
        binding.btnSettings.setOnClickListener { showSettingsDialog() }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            onBackPressedDispatcher.addCallback(this, object : androidx.activity.OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (activeTab?.canGoBack == true) {
                        activeTab?.session?.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            })
        }
    }

    private fun restoreOrCreateInitialTab() {
        val lastUrl = prefs.getString(KEY_LAST_URL, null)
        val startUrl = lastUrl ?: homepageUrl()
        val selfTest = System.getenv("SURFSCAPE_SELFTEST") == "1"
        val tab = createTab(
            initialUrl = if (selfTest) "about:blank" else startUrl,
            select = true,
            autoLoad = !selfTest
        )
        if (selfTest) {
            val testHtml =
                "<html><body style='font-family:sans-serif'><h3>Surfscape Self-Test</h3>" +
                        "<p>If you can read this, GeckoView rendered a local page.</p>" +
                        "<p>User Agent should appear below after JS runs.</p>" +
                        "<div id='ua'></div><script>document.getElementById('ua').textContent = navigator.userAgent;</script></body></html>"
            val dataUrl = "data:text/html;base64," +
                    android.util.Base64.encodeToString(testHtml.toByteArray(), android.util.Base64.NO_WRAP)
            tab.session.loadUri(dataUrl)
            mainHandler.postDelayed({
                if (!isDestroyed && tabs.any { it.id == tab.id }) {
                    tab.session.loadUri(startUrl)
                }
            }, 1500)
        }
    }

    private fun createTab(
        initialUrl: String?,
        select: Boolean,
        isPrivate: Boolean = false,
        autoLoad: Boolean = true
    ): BrowserTab {
        val session = GeckoSession()
        val tabId = tabIdSequence.incrementAndGet()
        val tab = BrowserTab(
            id = tabId,
            session = session,
            title = getString(R.string.default_tab_title),
            lastUrl = initialUrl ?: homepageUrl(),
            isPrivate = isPrivate
        )
        configureSession(tab)
        session.open(runtime)
        if (autoLoad && initialUrl != null) {
            session.loadUri(initialUrl)
        }
        tabs += tab
        refreshTabStrip()
        if (select) {
            selectTab(tab.id)
        }
        return tab
    }

    private fun configureSession(tab: BrowserTab) {
        tab.session.setNavigationDelegate(object : GeckoSession.NavigationDelegate {
            override fun onCanGoBack(session: GeckoSession, canGoBack: Boolean) {
                tab.canGoBack = canGoBack
                if (tab.id == activeTabId) {
                    updateNavigationState()
                }
            }

            override fun onCanGoForward(session: GeckoSession, canGoForward: Boolean) {
                tab.canGoForward = canGoForward
                if (tab.id == activeTabId) {
                    updateNavigationState()
                }
            }

            override fun onLocationChange(
                session: GeckoSession,
                url: String?,
                permissions: MutableList<GeckoSession.PermissionDelegate.ContentPermission>,
                hasUserGesture: Boolean
            ) {
                if (url.isNullOrBlank()) return
                tab.lastUrl = url
                tab.statusText = hostForStatus(url)
                if (!tab.isPrivate) {
                    prefs.edit().putString(KEY_LAST_URL, url).apply()
                }
                if (tab.id == activeTabId) {
                    withUi {
                        updateUrlBar(url)
                        updateStatus(tab.statusText.ifBlank { getString(R.string.status_ready) })
                        updateBookmarkIcon()
                    }
                }
            }
        })

        tab.session.contentDelegate = object : ContentDelegate {
            override fun onTitleChange(session: GeckoSession, title: String?) {
                val safeTitle = title?.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
                tab.title = safeTitle
                if (tab.id == activeTabId) {
                    withUi {
                        updateWindowTitle(tab)
                        updateTabStripSelection()
                    }
                } else {
                    withUi { updateTabStripSelection() }
                }
            }

            override fun onCrash(session: GeckoSession) {
                Log.e(TAG, "GeckoSession crashed for tab ${tab.id}; recreating")
                withUi {
                    Toast.makeText(this@MainActivity, "Tab crashed, reloading…", Toast.LENGTH_LONG).show()
                }
                handleTabCrash(tab)
            }
        }

        tab.session.progressDelegate = object : ProgressDelegate {
            override fun onProgressChange(session: GeckoSession, progress: Int) {
                tab.lastProgress = progress
                if (tab.id == activeTabId) {
                    withUi {
                        binding.progressBar.isVisible = progress in 1..99
                        binding.progressBar.progress = progress
                    }
                }
            }

            override fun onSecurityChange(session: GeckoSession, securityInfo: ProgressDelegate.SecurityInformation) {
                // placeholder for future security indicators
            }

            override fun onPageStart(session: GeckoSession, url: String) {
                tab.statusText = getString(R.string.status_loading)
                tab.lastProgress = 0
                if (tab.id == activeTabId) {
                    withUi {
                        updateStatus(getString(R.string.status_loading))
                        binding.progressBar.isVisible = true
                        binding.progressBar.progress = 0
                    }
                }
            }

            override fun onPageStop(session: GeckoSession, success: Boolean) {
                if (tab.id == activeTabId) {
                    withUi {
                        binding.progressBar.isVisible = false
                        updateStatus(tab.statusText.ifBlank { getString(R.string.status_ready) })
                    }
                }
            }
        }
    }

    private fun handleTabCrash(tab: BrowserTab) {
        val previousSession = tab.session
        val restoreUrl = tab.lastUrl.takeIf { it.isNotBlank() } ?: homepageUrl()
        try {
            previousSession.close()
        } catch (ignored: Exception) {
            // ignore
        }
        val newSession = GeckoSession()
        tab.session = newSession
        configureSession(tab)
        try {
            newSession.open(runtime)
        } catch (t: Throwable) {
            Log.e(TAG, "Failed to reopen GeckoSession for crashed tab", t)
            withUi {
                Toast.makeText(this, "Failed to reopen tab", Toast.LENGTH_LONG).show()
            }
            return
        }
        if (tab.id == activeTabId) {
            withUi { attachSession(tab) }
        }
        newSession.loadUri(restoreUrl)
    }

    private fun selectTab(tabId: Long) {
        val target = tabs.firstOrNull { it.id == tabId } ?: return
        if (activeTabId == target.id && binding.geckoView.session == target.session) {
            return
        }
        val previous = activeTab
        activeTabId = target.id
        if (previous != null && previous.session != target.session) {
            try {
                previous.session.setActive(false)
            } catch (ignored: Throwable) {
            }
        }
        attachSession(target)
    }

    private fun attachSession(tab: BrowserTab) {
        binding.geckoView.setSession(tab.session)
        try {
            tab.session.setActive(true)
        } catch (t: Throwable) {
            Log.w(TAG, "setActive(true) failed", t)
        }
        updateWindowTitle(tab)
        updateUrlBar(tab.lastUrl)
        updateNavigationState()
        updateBookmarkIcon()
        updateStatus(tab.statusText.ifBlank { getString(R.string.status_ready) })
        binding.progressBar.isVisible = tab.lastProgress in 1..99
        binding.progressBar.progress = tab.lastProgress
        updateTabStripSelection()
    }

    private fun refreshTabStrip() {
        withUi {
            binding.tabStrip.removeAllViews()
            tabs.forEach { tab ->
                val chip = Chip(this).apply {
                    id = View.generateViewId()
                    text = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
                    isCheckable = true
                    isChecked = tab.id == activeTabId
                    isCloseIconVisible = tabs.size > 1
                    closeIcon = AppCompatResources.getDrawable(this@MainActivity, R.drawable.ic_close)
                    setOnClickListener { selectTab(tab.id) }
                    setOnCloseIconClickListener { closeTab(tab.id) }
                }
                binding.tabStrip.addView(chip)
            }
            updateTabStripSelection()
        }
    }

    private fun updateTabStripSelection() {
        val currentId = activeTabId
        binding.tabStrip.children.forEachIndexed { index, view ->
            val chip = view as? Chip ?: return@forEachIndexed
            val tab = tabs.getOrNull(index) ?: return@forEachIndexed
            chip.text = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
            chip.isCloseIconVisible = tabs.size > 1
            chip.isChecked = tab.id == currentId
            if (chip.isChecked) {
                binding.tabScroll.post {
                    binding.tabScroll.smoothScrollTo(chip.left, 0)
                }
            }
        }
    }

    private fun closeTab(tabId: Long) {
        val index = tabs.indexOfFirst { it.id == tabId }
        if (index == -1) return
        val tab = tabs.removeAt(index)
        try {
            tab.session.close()
        } catch (ignored: Exception) {
        }
        if (tabs.isEmpty()) {
            activeTabId = null
            updateWindowTitle(null)
            updateUrlBar("")
            updateNavigationState()
            updateBookmarkIcon()
            updateStatus(getString(R.string.status_ready))
            binding.progressBar.isVisible = false
            createTab(initialUrl = homepageUrl(), select = true)
        } else {
            val newIndex = when {
                index < tabs.size -> index
                else -> tabs.lastIndex
            }
            selectTab(tabs[newIndex].id)
            refreshTabStrip()
        }
    }

    private fun submitUrlFromBar() {
        val raw = binding.urlBar.text?.toString() ?: return
        val target = buildTargetForInput(raw) ?: return
        loadInActiveTab(target)
    }

    private fun loadInActiveTab(target: String) {
        val tab = activeTab ?: return
        Log.d(TAG, "Loading $target in tab ${tab.id}")
        tab.session.loadUri(target)
    }

    private fun buildTargetForInput(raw: String): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        if (SCHEME_REGEX.containsMatchIn(trimmed)) {
            return trimmed
        }
        val looksLikeDomain = Patterns.WEB_URL.matcher(trimmed).find() && !trimmed.contains(' ')
        return if (looksLikeDomain) {
            "https://$trimmed"
        } else {
            val encoded = try {
                URLEncoder.encode(trimmed, Charsets.UTF_8.name())
            } catch (_: Exception) {
                Uri.encode(trimmed)
            }
            String.format(currentSearchEngine().queryTemplate, encoded)
        }
    }

    private fun homepageUrl(): String =
        prefs.getString(KEY_HOMEPAGE, HOME_URL_DEFAULT)?.takeIf { it.isNotBlank() } ?: HOME_URL_DEFAULT

    private fun currentSearchEngine(): SearchEngine {
        val id = prefs.getString(KEY_SEARCH_ENGINE, searchEngines.first().id)
        return searchEngines.firstOrNull { it.id == id } ?: searchEngines.first()
    }

    private fun hostForStatus(url: String): String {
        return try {
            val uri = Uri.parse(url)
            uri.host ?: url
        } catch (_: Exception) {
            url
        }
    }

    private fun updateUrlBar(url: String) {
        ignoreUrlBarChange = true
        binding.urlBar.setText(url)
        binding.urlBar.setSelection(binding.urlBar.text?.length ?: 0)
        ignoreUrlBarChange = false
    }

    private fun updateWindowTitle(tab: BrowserTab?) {
        title = when {
            tab == null -> "Surfscape"
            tab.title.isBlank() -> "Surfscape"
            else -> "Surfscape - ${tab.title}"
        }
    }

    private fun updateNavigationState() {
        val tab = activeTab
        binding.btnBack.isEnabled = tab?.canGoBack == true
        binding.btnForward.isEnabled = tab?.canGoForward == true
        binding.btnReload.isEnabled = tab != null
        binding.btnHome.isEnabled = tab != null
        binding.btnBookmark.isEnabled = tab != null && tab.lastUrl.isNotBlank()
    }

    private fun updateBookmarkIcon() {
        val tab = activeTab
        val drawable = if (tab != null && tab.lastUrl.isNotBlank() && isBookmarked(tab.lastUrl)) {
            R.drawable.ic_star_filled
        } else {
            R.drawable.ic_star_border
        }
        binding.btnBookmark.setImageDrawable(AppCompatResources.getDrawable(this, drawable))
    }

    private fun isBookmarked(url: String): Boolean {
        val saved = prefs.getStringSet(KEY_BOOKMARKS, emptySet()) ?: emptySet()
        return saved.contains(url)
    }

    private fun toggleBookmark() {
        val tab = activeTab ?: return
        val url = tab.lastUrl
        if (url.isBlank()) return
        val current = prefs.getStringSet(KEY_BOOKMARKS, emptySet()) ?: emptySet()
        val updated = current.toMutableSet()
        val added: Boolean
        if (updated.contains(url)) {
            updated.remove(url)
            added = false
        } else {
            updated.add(url)
            added = true
        }
        prefs.edit().putStringSet(KEY_BOOKMARKS, updated).apply()
        updateBookmarkIcon()
        val msg = if (added) R.string.bookmark_added else R.string.bookmark_removed
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private fun showAiPlaceholder() {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.ai_placeholder_title)
            .setMessage(R.string.ai_placeholder_message)
            .setPositiveButton(R.string.dialog_dismiss, null)
            .show()
    }

    private fun showSettingsDialog() {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_settings, null)
        val homepageInput =
            view.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.homepageInput)
        val searchInput = view.findViewById<MaterialAutoCompleteTextView>(R.id.searchEngineInput)
        homepageInput.setText(homepageUrl())
        val adapter = ArrayAdapter(
            this,
            android.R.layout.simple_list_item_1,
            searchEngines.map { it.label }
        )
        searchInput.setAdapter(adapter)
        searchInput.setText(currentSearchEngine().label, false)

        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.settings_title)
            .setView(view)
            .setPositiveButton(R.string.settings_save) { _, _ ->
                val homepageValue = homepageInput.text?.toString()?.trim().orEmpty()
                val normalizedHome = when {
                    homepageValue.isBlank() -> HOME_URL_DEFAULT
                    SCHEME_REGEX.containsMatchIn(homepageValue) -> homepageValue
                    else -> "https://$homepageValue"
                }
                val selectedLabel = searchInput.text?.toString() ?: ""
                val chosenEngine = searchEngines.firstOrNull { it.label == selectedLabel } ?: currentSearchEngine()
                prefs.edit()
                    .putString(KEY_HOMEPAGE, normalizedHome)
                    .putString(KEY_SEARCH_ENGINE, chosenEngine.id)
                    .apply()
                Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.settings_cancel, null)
            .show()
    }

    private fun updateStatus(text: String) {
        binding.statusBar.text = text
    }

    private fun withUi(block: () -> Unit) {
        if (isDestroyed || isFinishing) return
        if (Looper.myLooper() == Looper.getMainLooper()) {
            block()
        } else {
            mainHandler.post {
                if (!isDestroyed && !isFinishing) {
                    block()
                }
            }
        }
    }

    override fun onPause() {
        super.onPause()
        activeTab?.session?.let {
            try {
                it.setActive(false)
            } catch (t: Throwable) {
                Log.w(TAG, "setActive(false) failed", t)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        activeTab?.session?.let {
            try {
                it.setActive(true)
            } catch (t: Throwable) {
                Log.w(TAG, "setActive(true) failed", t)
            }
        }
    }

    override fun onDestroy() {
        tabs.forEach {
            try {
                it.session.close()
            } catch (_: Exception) {
            }
        }
        tabs.clear()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (activeTab?.canGoBack == true) {
            activeTab?.session?.goBack()
        } else {
            super.onBackPressed()
        }
    }

    companion object {
        private const val TAG = "Surfscape"
        private const val PREFS_NAME = "surfscape_mobile"
        private const val KEY_LAST_URL = "last_url"
        private const val KEY_BOOKMARKS = "bookmarks"
        private const val KEY_HOMEPAGE = "homepage_url"
        private const val KEY_SEARCH_ENGINE = "search_engine"
        private const val HOME_URL_DEFAULT = "https://html.duckduckgo.com/html"
        private val SCHEME_REGEX = Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://")
    }
}
