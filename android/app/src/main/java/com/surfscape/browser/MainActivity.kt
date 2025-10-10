package com.surfscape.browser

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.util.Patterns
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.content.res.AppCompatResources
import androidx.core.view.children
import androidx.core.view.isVisible
import androidx.core.widget.addTextChangedListener
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.surfscape.browser.databinding.ActivityMainBinding
import java.net.URLEncoder
import java.util.ArrayList
import java.util.LinkedHashSet
import java.util.concurrent.atomic.AtomicLong

class MainActivity : AppCompatActivity() {

    private data class SearchEngine(val id: String, val label: String, val queryTemplate: String)

    private data class BrowserTab(
        val id: Long,
        val webView: WebView,
        var title: String = "",
        var url: String = "",
        var isLoading: Boolean = false,
        var canGoBack: Boolean = false,
        var canGoForward: Boolean = false
    )

    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences(PREFS_NAME, MODE_PRIVATE) }
    private val tabIdGenerator = AtomicLong(0)
    private val tabs = mutableListOf<BrowserTab>()
    private var activeTabId: Long? = null
    private var ignoreUrlCallbacks = false
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null

    private lateinit var searchEngines: List<SearchEngine>

    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = fileChooserCallback
            val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            callback?.onReceiveValue(uris)
            fileChooserCallback = null
        }

    private val activeTab: BrowserTab?
        get() = tabs.firstOrNull { it.id == activeTabId }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.topToolbar)
        supportActionBar?.setDisplayShowTitleEnabled(false)
        binding.topToolbar.title = ""

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        CookieManager.getInstance().setAcceptCookie(true)

        searchEngines = buildSearchEngines()
        setupUiListeners()

        if (savedInstanceState != null) {
            restoreFromState(savedInstanceState)
        } else {
            restoreLastSession()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putStringArrayList(KEY_STATE_URLS, ArrayList(tabs.map { it.url }))
        val activeIndex = tabs.indexOfFirst { it.id == activeTabId }.takeIf { it >= 0 } ?: 0
        outState.putInt(KEY_STATE_ACTIVE_INDEX, activeIndex)
    }

    override fun onPause() {
        super.onPause()
        activeTab?.webView?.onPause()
    }

    override fun onResume() {
        super.onResume()
        activeTab?.webView?.onResume()
    }

    override fun onStop() {
        super.onStop()
        persistSession()
    }

    override fun onDestroy() {
        tabs.forEach { tab ->
            (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
            tab.webView.stopLoading()
            tab.webView.destroy()
        }
        tabs.clear()
        super.onDestroy()
    }

    override fun onBackPressed() {
        val tab = activeTab
        if (tab?.webView?.canGoBack() == true) {
            tab.webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    private fun setupUiListeners() {
        binding.urlBar.addTextChangedListener {
            if (!ignoreUrlCallbacks) {
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

        binding.btnBack.setOnClickListener { activeTab?.webView?.goBack() }
        binding.btnForward.setOnClickListener { activeTab?.webView?.goForward() }
        binding.btnHome.setOnClickListener { loadInActiveTab(homepageUrl()) }
        binding.btnReload.setOnClickListener {
            val tab = activeTab ?: return@setOnClickListener
            if (tab.isLoading) {
                tab.webView.stopLoading()
            } else {
                tab.webView.reload()
            }
        }
        binding.btnNewTab.setOnClickListener {
            val tab = createTab(homepageUrl(), select = true)
            tab.webView.requestFocus()
        }
        binding.btnBookmark.setOnClickListener { toggleBookmark() }
        binding.btnAi.setOnClickListener { showAiPlaceholder() }
        binding.btnSettings.setOnClickListener { showSettingsDialog() }
    }

    private fun buildSearchEngines(): List<SearchEngine> = listOf(
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

    private fun restoreFromState(state: Bundle) {
        val urls = state.getStringArrayList(KEY_STATE_URLS)
        val activeIndex = state.getInt(KEY_STATE_ACTIVE_INDEX, 0)
        if (urls.isNullOrEmpty()) {
            createTab(homepageUrl(), select = true)
            return
        }
        urls.forEachIndexed { index, url ->
            val tab = createTab(url ?: homepageUrl(), select = index == activeIndex)
            if (index == activeIndex) {
                selectTab(tab.id)
            }
        }
    }

    private fun restoreLastSession() {
        val stored = prefs.getStringSet(KEY_LAST_SESSION, null)?.toList()
        if (!stored.isNullOrEmpty()) {
            stored.forEachIndexed { index, url ->
                createTab(url, select = index == 0)
            }
        } else {
            val startUrl = prefs.getString(KEY_LAST_URL, homepageUrl()) ?: homepageUrl()
            createTab(startUrl, select = true)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createTab(initialUrl: String, select: Boolean, autoLoad: Boolean = true): BrowserTab {
        val webView = WebView(this)
        val tab = BrowserTab(id = tabIdGenerator.incrementAndGet(), webView = webView)
        configureWebView(tab)

        tabs += tab
        refreshTabStrip()

        if (select) {
            selectTab(tab.id)
        }

        if (autoLoad && initialUrl.isNotBlank()) {
            tab.webView.loadUrl(initialUrl)
        } else {
            tab.url = initialUrl
        }
        persistSession()
        return tab
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(tab: BrowserTab) {
        val webView = tab.webView
        webView.layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        )
        webView.isFocusableInTouchMode = true

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            builtInZoomControls = true
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
            mediaPlaybackRequiresUserGesture = false
            textZoom = 100
            userAgentString = "${userAgentString} SurfscapeMobile/${BuildConfig.VERSION_NAME}"
        }

        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(webView.settings, true)
        }

        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                tab.isLoading = newProgress in 0..99
                if (tab.id == activeTabId) {
                    binding.progressBar.isVisible = newProgress in 1..99
                    binding.progressBar.progress = newProgress
                    updateReloadButton(tab.isLoading)
                }
            }

            override fun onReceivedTitle(view: WebView?, title: String?) {
                tab.title = title?.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
                if (tab.id == activeTabId) {
                    updateWindowTitle(tab)
                    updateTabChipSelection()
                } else {
                    updateTabChipSelection()
                }
            }

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback
                val intent = try {
                    fileChooserParams?.createIntent() ?: return false
                } catch (e: Exception) {
                    fileChooserCallback = null
                    return false
                }
                return try {
                    fileChooserLauncher.launch(intent)
                    true
                } catch (_: ActivityNotFoundException) {
                    fileChooserCallback = null
                    Toast.makeText(this@MainActivity, getString(R.string.no_app_found), Toast.LENGTH_SHORT).show()
                    false
                }
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val uri = request?.url ?: return false
                return handleExternalUri(uri)
            }

            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                return handleExternalUrl(url)
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                val safeUrl = url ?: return
                tab.url = safeUrl
                tab.isLoading = true
                tab.canGoBack = tab.webView.canGoBack()
                tab.canGoForward = tab.webView.canGoForward()
                if (tab.id == activeTabId) {
                    updateUrlBar(safeUrl)
                    updateStatus(getHostForStatus(safeUrl))
                    updateNavigationState()
                    updateReloadButton(true)
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                val safeUrl = url ?: return
                tab.url = safeUrl
                tab.isLoading = false
                tab.canGoBack = tab.webView.canGoBack()
                tab.canGoForward = tab.webView.canGoForward()
                if (tab.id == activeTabId) {
                    updateUrlBar(tab.url)
                    updateStatus(getHostForStatus(tab.url))
                    updateNavigationState()
                    updateReloadButton(false)
                    updateBookmarkIcon()
                }
                prefs.edit().putString(KEY_LAST_URL, tab.url).apply()
                persistSession()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (tab.id == activeTabId) {
                    updateStatus(getString(R.string.status_error))
                }
                Toast.makeText(
                    this@MainActivity,
                    getString(R.string.status_error),
                    Toast.LENGTH_SHORT
                ).show()
            }
        }

        webView.setDownloadListener { url, _, _, _, _ ->
            if (handleExternalUrl(url)) {
                Toast.makeText(this, getString(R.string.opening_external), Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun selectTab(tabId: Long) {
        val tab = tabs.firstOrNull { it.id == tabId } ?: return
        if (tab.id == activeTabId) return

        activeTab?.webView?.onPause()
        activeTabId = tab.id

        binding.webContainer.removeAllViews()
        (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
        binding.webContainer.addView(tab.webView)
        tab.webView.onResume()
        tab.webView.requestFocus()

        updateWindowTitle(tab)
        updateUrlBar(tab.url)
        updateReloadButton(tab.isLoading)
        updateNavigationState()
        updateStatus(getHostForStatus(tab.url))
        updateBookmarkIcon()
        updateTabChipSelection()
    }

    private fun refreshTabStrip() {
        binding.tabStrip.removeAllViews()
        tabs.forEach { tab ->
            val chip = createTabChip(tab)
            binding.tabStrip.addView(chip)
        }
        updateTabChipSelection()
    }

    private fun createTabChip(tab: BrowserTab): Chip {
        val chip = Chip(this, null, com.google.android.material.R.attr.chipStyle)
        chip.id = View.generateViewId()
        chip.text = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
        chip.isCheckable = true
        chip.isChecked = tab.id == activeTabId
        chip.isCloseIconVisible = tabs.size > 1
        chip.closeIcon = AppCompatResources.getDrawable(this, R.drawable.ic_close)
        chip.setOnClickListener { selectTab(tab.id) }
        chip.setOnCloseIconClickListener { closeTab(tab.id) }
        chip.tag = tab.id
        return chip
    }

    private fun updateTabChipSelection() {
        val current = activeTabId
        binding.tabStrip.children.forEachIndexed { index, view ->
            val chip = view as? Chip ?: return@forEachIndexed
            val tab = tabs.getOrNull(index) ?: return@forEachIndexed
            chip.text = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
            chip.isCloseIconVisible = tabs.size > 1
            chip.isChecked = tab.id == current
            if (chip.isChecked) {
                binding.tabScroll.post { binding.tabScroll.smoothScrollTo(chip.left, 0) }
            }
        }
    }

    private fun closeTab(tabId: Long) {
        val index = tabs.indexOfFirst { it.id == tabId }
        if (index == -1) return
        val tab = tabs.removeAt(index)
        (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
        tab.webView.stopLoading()
        tab.webView.destroy()

        if (tabs.isEmpty()) {
            activeTabId = null
            createTab(homepageUrl(), select = true)
        } else {
            val newIndex = index.coerceAtMost(tabs.lastIndex)
            selectTab(tabs[newIndex].id)
        }
        refreshTabStrip()
        persistSession()
    }

    private fun submitUrlFromBar() {
        val input = binding.urlBar.text?.toString().orEmpty()
        val target = buildTargetForInput(input) ?: return
        loadInActiveTab(target)
    }

    private fun loadInActiveTab(target: String) {
        val tab = activeTab ?: return
        tab.webView.loadUrl(target)
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

    private fun toggleBookmark() {
        val tab = activeTab ?: return
        val url = tab.url
        if (url.isBlank()) return
        val current = prefs.getStringSet(KEY_BOOKMARKS, emptySet())?.toMutableSet() ?: mutableSetOf()
        val added: Boolean
        if (current.contains(url)) {
            current.remove(url)
            added = false
        } else {
            current.add(url)
            added = true
        }
        prefs.edit().putStringSet(KEY_BOOKMARKS, current).apply()
        updateBookmarkIcon()
        val message = if (added) R.string.bookmark_added else R.string.bookmark_removed
        Toast.makeText(this, getString(message), Toast.LENGTH_SHORT).show()
    }

    private fun updateBookmarkIcon() {
        val tab = activeTab
        val currentUrl = tab?.url.orEmpty()
        val saved = prefs.getStringSet(KEY_BOOKMARKS, emptySet()) ?: emptySet()
        val icon = if (currentUrl.isNotBlank() && saved.contains(currentUrl)) {
            R.drawable.ic_star_filled
        } else {
            R.drawable.ic_star_border
        }
        binding.btnBookmark.setImageDrawable(AppCompatResources.getDrawable(this, icon))
    }

    private fun updateReloadButton(isLoading: Boolean) {
        val icon = if (isLoading) R.drawable.ic_close else R.drawable.ic_refresh
        binding.btnReload.setImageDrawable(AppCompatResources.getDrawable(this, icon))
        binding.btnReload.contentDescription = getString(
            if (isLoading) R.string.stop_loading else R.string.reload
        )
    }

    private fun updateNavigationState() {
        val tab = activeTab
        binding.btnBack.isEnabled = tab?.webView?.canGoBack() == true
        binding.btnForward.isEnabled = tab?.webView?.canGoForward() == true
        binding.btnReload.isEnabled = tab != null
        binding.btnHome.isEnabled = tab != null
        binding.btnBookmark.isEnabled = tab != null
    }

    private fun updateUrlBar(url: String) {
        ignoreUrlCallbacks = true
        binding.urlBar.setText(url)
        binding.urlBar.setSelection(binding.urlBar.text?.length ?: 0)
        ignoreUrlCallbacks = false
    }

    private fun updateStatus(text: String) {
        binding.statusBar.text = if (text.isBlank()) getString(R.string.status_ready) else text
    }

    private fun updateWindowTitle(tab: BrowserTab) {
        title = if (tab.title.isBlank()) {
            getString(R.string.app_name)
        } else {
            "${getString(R.string.app_name)} - ${tab.title}"
        }
        binding.topToolbar.subtitle = tab.title
    }

    private fun homepageUrl(): String =
        prefs.getString(KEY_HOMEPAGE, HOME_URL_DEFAULT)?.takeIf { it.isNotBlank() } ?: HOME_URL_DEFAULT

    private fun currentSearchEngine(): SearchEngine {
        val id = prefs.getString(KEY_SEARCH_ENGINE, searchEngines.first().id)
        return searchEngines.firstOrNull { it.id == id } ?: searchEngines.first()
    }

    private fun showAiPlaceholder() {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.ai_placeholder_title)
            .setMessage(R.string.ai_placeholder_message)
            .setPositiveButton(R.string.dialog_dismiss, null)
            .show()
    }

    private fun showSettingsDialog() {
        val content = LayoutInflater.from(this).inflate(R.layout.dialog_settings, null)
        val homepageInput =
            content.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.homepageInput)
        val searchInput = content.findViewById<MaterialAutoCompleteTextView>(R.id.searchEngineInput)

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
            .setView(content)
            .setPositiveButton(R.string.settings_save) { _, _ ->
                val homepageValue = homepageInput.text?.toString()?.trim().orEmpty()
                val normalizedHomepage = when {
                    homepageValue.isBlank() -> HOME_URL_DEFAULT
                    SCHEME_REGEX.containsMatchIn(homepageValue) -> homepageValue
                    else -> "https://$homepageValue"
                }
                val chosenEngine = searchEngines.firstOrNull { it.label == searchInput.text.toString() }
                    ?: currentSearchEngine()
                prefs.edit()
                    .putString(KEY_HOMEPAGE, normalizedHomepage)
                    .putString(KEY_SEARCH_ENGINE, chosenEngine.id)
                    .apply()
                Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.settings_cancel, null)
            .show()
    }

    private fun persistSession() {
        val ordered = LinkedHashSet<String>()
        tabs.mapNotNullTo(ordered) { it.url.takeIf { url -> url.isNotBlank() } }
        prefs.edit().putStringSet(KEY_LAST_SESSION, ordered).apply()
    }

    private fun handleExternalUrl(url: String?): Boolean {
        val uri = url?.let { Uri.parse(it) } ?: return false
        return handleExternalUri(uri)
    }

    private fun handleExternalUri(uri: Uri): Boolean {
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme == "http" || scheme == "https") {
            return false
        }
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
            true
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, getString(R.string.no_app_found), Toast.LENGTH_SHORT).show()
            true
        }
    }

    private fun getHostForStatus(url: String): String {
        return try {
            val uri = Uri.parse(url)
            uri.host ?: url
        } catch (_: Exception) {
            url
        }
    }

    companion object {
        private const val PREFS_NAME = "surfscape_mobile"
        private const val KEY_LAST_URL = "last_url"
        private const val KEY_BOOKMARKS = "bookmarks"
        private const val KEY_HOMEPAGE = "homepage_url"
        private const val KEY_SEARCH_ENGINE = "search_engine"
        private const val KEY_LAST_SESSION = "session_urls"
        private const val KEY_STATE_URLS = "state_urls"
        private const val KEY_STATE_ACTIVE_INDEX = "state_active_index"
        private const val HOME_URL_DEFAULT = "https://html.duckduckgo.com/html"
        private val SCHEME_REGEX = Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://")
    }
}
