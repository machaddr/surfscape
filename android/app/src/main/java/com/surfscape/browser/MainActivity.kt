package com.surfscape.browser

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.res.ColorStateList
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.net.Uri
import android.os.Build
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
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ArrayAdapter
import android.widget.Filter
import android.widget.Filter.FilterResults
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.content.res.AppCompatResources
import androidx.core.content.ContextCompat
import androidx.core.view.children
import androidx.core.view.doOnLayout
import androidx.core.view.isVisible
import androidx.core.widget.addTextChangedListener
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.slider.Slider
import com.google.android.material.switchmaterial.SwitchMaterial
import com.google.android.material.textfield.MaterialAutoCompleteTextView
import com.surfscape.browser.databinding.ActivityMainBinding
import java.io.File
import java.io.InputStream
import java.net.URLEncoder
import java.util.ArrayList
import java.util.LinkedHashSet
import java.util.Calendar
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import android.text.Html
import android.text.TextUtils

class MainActivity : AppCompatActivity() {

    private data class SearchEngine(val id: String, val label: String, val queryTemplate: String)

    private data class BrowserTab(
        val id: Long,
        val webView: WebView,
        var title: String = "",
        var url: String = "",
        var isLoading: Boolean = false,
        var canGoBack: Boolean = false,
        var canGoForward: Boolean = false,
        var faviconDrawable: Drawable? = null
    )

    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences(PREFS_NAME, MODE_PRIVATE) }
    private val tabIdGenerator = AtomicLong(0)
    private val tabs = mutableListOf<BrowserTab>()
    private var activeTabId: Long? = null
    private var ignoreUrlCallbacks = false
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private lateinit var mobileUserAgent: String
    private lateinit var desktopUserAgent: String

    private lateinit var searchEngines: List<SearchEngine>
    private data class HistoryEntry(val title: String, val url: String, val timestamp: Long, val iconPath: String?)
    private data class BookmarkEntry(val title: String, val url: String, val iconPath: String?)
    private data class DialogEntry(val index: Int, val title: String, val subtitle: String, val icon: Drawable?)
    private sealed class DialogListItem {
        data class Section(val title: String) : DialogListItem()
        data class Entry(val data: DialogEntry) : DialogListItem()
    }
    private data class SuggestionItem(val display: String, val secondary: String?, val url: String, val icon: Drawable?, val type: SuggestionType)
    private enum class SuggestionType { HISTORY, BOOKMARK }

    private val historyEntries = mutableListOf<HistoryEntry>()
    private val faviconDir: File by lazy { File(filesDir, "favicons").apply { mkdirs() } }
    private val faviconCache = mutableMapOf<String, Drawable?>()
    private val defaultFavicon by lazy { ContextCompat.getDrawable(this, R.drawable.ic_site_default) }
    private lateinit var suggestionAdapter: SuggestionAdapter
    private var bookmarkCache: List<BookmarkEntry>? = null
    private var statusOverrideMessage: String? = null
    private var lastStatusMessage: String = ""

    private val fileChooserLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = fileChooserCallback
            val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            callback?.onReceiveValue(uris)
            fileChooserCallback = null
        }

    private val exportBookmarksLauncher =
        registerForActivityResult(ActivityResultContracts.CreateDocument("text/html")) { uri ->
            if (uri != null) {
                exportBookmarksToUri(uri)
            }
        }

    private val importBookmarksLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) {
                importBookmarksFromUri(uri)
            }
        }

    private val activeTab: BrowserTab?
        get() = tabs.firstOrNull { it.id == activeTabId }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        mobileUserAgent = "${WebSettings.getDefaultUserAgent(this)} SurfscapeMobile/${BuildConfig.VERSION_NAME}"
        desktopUserAgent =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 SurfscapeDesktop/${BuildConfig.VERSION_NAME}"

        setSupportActionBar(binding.topToolbar)
        supportActionBar?.setDisplayShowTitleEnabled(false)
        binding.topToolbar.title = ""

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        CookieManager.getInstance().setAcceptCookie(true)

        updateTabCounter()
        setupBackNavigation()

        suggestionAdapter = SuggestionAdapter(this)
        binding.urlBar.setAdapter(suggestionAdapter)
        binding.urlBar.threshold = 1
        binding.urlBar.setDropDownBackgroundResource(R.drawable.bg_suggestion_dropdown)
        binding.urlInputLayout.doOnLayout {
            binding.urlBar.dropDownWidth = it.width
        }

        searchEngines = buildSearchEngines()
        setupUiListeners()
        applyUiPreferences()
        loadHistory()
        updateNavigationState()

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
        if (shouldClearOnExit()) {
            clearBrowsingData()
        }
        tabs.forEach { tab ->
            (tab.webView.parent as? ViewGroup)?.removeView(tab.webView)
            tab.webView.stopLoading()
            tab.webView.destroy()
        }
        tabs.clear()
        super.onDestroy()
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val tab = activeTab
                if (tab?.webView?.canGoBack() == true) {
                    tab.webView.goBack()
                } else {
                    finish()
                }
            }
        })
    }

    private fun setupUiListeners() {
        binding.urlBar.addTextChangedListener {
            if (!ignoreUrlCallbacks) {
                updateBookmarkIcon()
                updateSuggestions(it?.toString().orEmpty())
            } else {
                suggestionAdapter.update(emptyList())
            }
        }
        binding.urlBar.setOnItemClickListener { _, _, position, _ ->
            val item = suggestionAdapter.getItem(position) ?: return@setOnItemClickListener
            ignoreUrlCallbacks = true
            binding.urlBar.setText(item.url)
            binding.urlBar.setSelection(item.url.length)
            ignoreUrlCallbacks = false
            loadInActiveTab(item.url)
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

        binding.btnSend.setOnClickListener { submitUrlFromBar() }

        binding.btnBack.setOnClickListener {
            activeTab?.webView?.let { if (it.canGoBack()) it.goBack() }
        }

        binding.btnForward.setOnClickListener {
            activeTab?.webView?.let { if (it.canGoForward()) it.goForward() }
        }

        binding.btnReload.setOnClickListener {
            val tab = activeTab ?: return@setOnClickListener
            if (tab.isLoading) {
                tab.webView.stopLoading()
            } else {
                tab.webView.reload()
            }
        }

        binding.btnHome.setOnClickListener { loadInActiveTab(homepageUrl()) }
        binding.btnBookmark.setOnClickListener { toggleBookmark() }
        binding.btnHistory.setOnClickListener { showHistoryDialog() }
        binding.btnSaved.setOnClickListener { showBookmarksDialog() }
        binding.btnAi.setOnClickListener { showAiPlaceholder() }
        binding.btnSettings.setOnClickListener { showSettingsDialog() }
        binding.tabCounter.setOnClickListener { showTabSwitcherDialog() }

        binding.btnNewTab.setOnClickListener {
            val tab = createTab(homepageUrl(), select = true)
            tab.webView.requestFocus()
        }
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
        tab.faviconDrawable = loadDrawableForUrl(initialUrl) ?: defaultFavicon

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
            domStorageEnabled = true
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            builtInZoomControls = true
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
            textZoom = 100
        }

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

            override fun onReceivedIcon(view: WebView?, icon: Bitmap?) {
                if (icon == null) return
                val url = view?.url ?: tab.url
                val drawable = saveFaviconForUrl(url, icon)
                tab.faviconDrawable = drawable
                updateTabChipSelection()
                if (tab.id == activeTabId) {
                    updateBookmarkIcon()
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
                tab.faviconDrawable = loadDrawableForUrl(tab.url) ?: tab.faviconDrawable
                updateTabChipSelection()
                val historyTitle = view?.title?.takeIf { !it.isNullOrBlank() }?.toString()
                    ?: tab.title.takeIf { it.isNotBlank() }
                    ?: getHostForStatus(tab.url)
                recordHistory(historyTitle, tab.url)
                updateNavigationState()
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

        applySettingsToWebView(tab)
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
        updateTabCounter()
    }

    private fun createTabChip(tab: BrowserTab): Chip {
        val chip = Chip(this, null, com.google.android.material.R.attr.chipStyle)
        chip.id = View.generateViewId()
        chip.text = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
        chip.isCheckable = true
        chip.isChecked = tab.id == activeTabId
        chip.isCloseIconVisible = tabs.size > 1
        chip.closeIcon = AppCompatResources.getDrawable(this, R.drawable.ic_close)
        chip.chipIcon = tab.faviconDrawable ?: defaultFavicon
        chip.isChipIconVisible = true
        chip.chipIconTint = null
        chip.chipIconSize = resources.getDimension(R.dimen.tab_chip_icon_size)
        chip.checkedIcon = null
        chip.isCheckedIconVisible = false
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
            chip.chipIcon = tab.faviconDrawable ?: defaultFavicon
            chip.chipIconTint = null
            chip.isChipIconVisible = true
            chip.chipIconSize = resources.getDimension(R.dimen.tab_chip_icon_size)
            chip.checkedIcon = null
            chip.isCheckedIconVisible = false
            if (chip.isChecked) {
                binding.tabScroll.post { binding.tabScroll.smoothScrollTo(chip.left, 0) }
            }
        }
    }

    private fun updateTabCounter() {
        val count = tabs.size
        binding.tabCounter.text = count.toString()
        binding.tabCounter.contentDescription = getString(R.string.tab_counter_content_description)
        val enabled = count > 0
        binding.tabCounter.isEnabled = enabled
        binding.tabCounter.alpha = if (enabled) 1f else 0.5f
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
        binding.urlBar.dismissDropDown()
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
        val raw = loadBookmarksRaw()
        val existing = findBookmarkEntry(url, raw)
        val messageRes: Int
        if (existing != null) {
            raw.remove(existing)
            messageRes = R.string.bookmark_removed
        } else {
            val title = tab.title.takeIf { it.isNotBlank() } ?: getHostForStatus(url)
            raw.add(buildBookmarkRecord(title, url))
            messageRes = R.string.bookmark_added
        }
        saveBookmarksRaw(raw)
        updateBookmarkIcon()
        if (binding.urlBar.hasFocus()) {
            updateSuggestions(binding.urlBar.text?.toString().orEmpty())
        }
        Toast.makeText(this, getString(messageRes), Toast.LENGTH_SHORT).show()
        updateNavigationState()
    }

    private fun updateBookmarkIcon() {
        val tab = activeTab
        val currentUrl = tab?.url.orEmpty()
        val saved = loadBookmarksRaw()
        val hasBookmark = currentUrl.isNotBlank() && findBookmarkEntry(currentUrl, saved) != null
        val icon = if (hasBookmark) R.drawable.ic_star_filled else R.drawable.ic_star_border
        binding.btnBookmark.setImageDrawable(AppCompatResources.getDrawable(this, icon))
    }

    private fun updateSuggestions(query: String) {
        val trimmed = query.trim()
        if (trimmed.isEmpty()) {
            suggestionAdapter.update(emptyList())
            binding.urlBar.dismissDropDown()
            return
        }
        val lower = trimmed.lowercase()
        val suggestions = mutableListOf<SuggestionItem>()
        val seen = mutableSetOf<String>()
        val historyLabel = getString(R.string.suggestion_type_history)
        val bookmarkLabel = getString(R.string.suggestion_type_bookmark)

        for (entry in historyEntries.asReversed()) {
            if (entry.title.contains(lower, ignoreCase = true) || entry.url.contains(lower, ignoreCase = true)) {
                if (seen.add(entry.url)) {
                    val display = entry.title.takeIf { it.isNotBlank() } ?: getHostForStatus(entry.url)
                    val secondary = getString(R.string.suggestion_secondary_format, historyLabel, entry.url)
                    val icon = loadDrawableForPath(entry.iconPath) ?: loadDrawableForUrl(entry.url) ?: defaultFavicon
                    suggestions.add(SuggestionItem(display, secondary, entry.url, icon, SuggestionType.HISTORY))
                    if (suggestions.size >= 10) break
                }
            }
        }

        if (suggestions.size < 10) {
            for (bookmark in bookmarkEntries()) {
                if (bookmark.title.contains(lower, ignoreCase = true) || bookmark.url.contains(lower, ignoreCase = true)) {
                    if (seen.add(bookmark.url)) {
                        val display = bookmark.title
                            .takeIf { it.isNotBlank() }
                            ?: getHostForStatus(bookmark.url)
                        val secondary = getString(R.string.suggestion_secondary_format, bookmarkLabel, bookmark.url)
                        val icon = loadDrawableForBookmark(bookmark) ?: defaultFavicon
                        suggestions.add(SuggestionItem(display, secondary, bookmark.url, icon, SuggestionType.BOOKMARK))
                        if (suggestions.size >= 10) break
                    }
                }
            }
        }

        suggestionAdapter.update(suggestions)
        if (suggestions.isNotEmpty() && binding.urlBar.hasFocus()) {
            binding.urlBar.showDropDown()
        } else {
            binding.urlBar.dismissDropDown()
        }
    }

    private fun updateReloadButton(isLoading: Boolean) {
        val icon = if (isLoading) R.drawable.ic_close else R.drawable.ic_refresh
        binding.btnReload.setImageDrawable(AppCompatResources.getDrawable(this, icon))
        binding.btnReload.contentDescription = getString(if (isLoading) R.string.stop_loading else R.string.reload)
    }

    private fun updateNavigationState() {
        val tab = activeTab
        val canGoBack = tab?.webView?.canGoBack() == true
        val canGoForward = tab?.webView?.canGoForward() == true
        val hasTab = tab != null
        val hasBookmarks = bookmarkEntries().isNotEmpty()
        binding.btnBack.isEnabled = canGoBack
        binding.btnForward.isEnabled = canGoForward
        binding.btnReload.isEnabled = hasTab
        binding.btnHome.isEnabled = hasTab
        binding.btnBookmark.isEnabled = hasTab
        binding.btnHistory.isEnabled = historyEntries.isNotEmpty()
        binding.btnSaved.isEnabled = hasBookmarks
    }

    private fun updateUrlBar(url: String) {
        ignoreUrlCallbacks = true
        binding.urlBar.setText(url)
        binding.urlBar.setSelection(binding.urlBar.text?.length ?: 0)
        ignoreUrlCallbacks = false
        binding.urlBar.dismissDropDown()
    }

    private fun updateStatus(text: String) {
        lastStatusMessage = if (text.isBlank()) getString(R.string.status_ready) else text
        applyStatusDisplay()
    }

    private fun setStatusOverride(message: String?) {
        statusOverrideMessage = message
        applyStatusDisplay()
    }

    private fun applyStatusDisplay() {
        if (!::binding.isInitialized) return
        val base = if (lastStatusMessage.isBlank()) getString(R.string.status_ready) else lastStatusMessage
        val display = statusOverrideMessage ?: base
        binding.statusBar.text = display
    }

    private fun statusForActiveTab(): String {
        val currentUrl = activeTab?.url
        return if (currentUrl.isNullOrBlank()) {
            getString(R.string.status_ready)
        } else {
            getHostForStatus(currentUrl)
        }
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
        val switchDarkMode = content.findViewById<SwitchMaterial>(R.id.switchDarkMode)
        val switchShowToolbar = content.findViewById<SwitchMaterial>(R.id.switchShowToolbar)
        val switchJavascript = content.findViewById<SwitchMaterial>(R.id.switchJavascript)
        val switchDesktopMode = content.findViewById<SwitchMaterial>(R.id.switchDesktopMode)
        val switchBlockImages = content.findViewById<SwitchMaterial>(R.id.switchBlockImages)
        val switchEnableZoom = content.findViewById<SwitchMaterial>(R.id.switchEnableZoom)
        val switchBlockPopups = content.findViewById<SwitchMaterial>(R.id.switchBlockPopups)
        val switchThirdPartyCookies = content.findViewById<SwitchMaterial>(R.id.switchThirdPartyCookies)
        val switchSafeBrowsing = content.findViewById<SwitchMaterial>(R.id.switchSafeBrowsing)
        val switchAutoplay = content.findViewById<SwitchMaterial>(R.id.switchAutoplay)
        val switchClearOnExit = content.findViewById<SwitchMaterial>(R.id.switchClearOnExit)
        val sliderFontScale = content.findViewById<Slider>(R.id.sliderFontScale)
        val fontScaleValue = content.findViewById<TextView>(R.id.fontScaleValue)
        val btnImportBookmarks = content.findViewById<MaterialButton>(R.id.btnImportBookmarks)
        val btnExportBookmarks = content.findViewById<MaterialButton>(R.id.btnExportBookmarks)

        homepageInput.setText(homepageUrl())
        val engineLabels = searchEngines.map { it.label }
        var selectedEngineIndex = engineLabels.indexOf(currentSearchEngine().label).takeIf { it >= 0 } ?: 0
        var isSearchDialogShowing = false
        searchInput.setText(engineLabels[selectedEngineIndex], false)
        searchInput.keyListener = null
        searchInput.isCursorVisible = false

        fun showSearchEnginePicker() {
            if (isSearchDialogShowing) return
            searchInput.clearFocus()
            val dialog = MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_search_engine_label)
                .setSingleChoiceItems(engineLabels.toTypedArray(), selectedEngineIndex) { dialog, which ->
                    selectedEngineIndex = which
                    searchInput.setText(engineLabels[which], false)
                    dialog.dismiss()
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
            isSearchDialogShowing = true
            dialog.setOnDismissListener { isSearchDialogShowing = false }
        }

        searchInput.setOnClickListener { showSearchEnginePicker() }
        searchInput.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus) {
                showSearchEnginePicker()
            }
        }

        val initialDark = prefBoolean(KEY_DARK_MODE, true)
        val initialShowToolbar = prefBoolean(KEY_SHOW_TOOLBAR, true)
        val initialJs = prefBoolean(KEY_JS_ENABLED, true)
        val initialDesktop = prefBoolean(KEY_DESKTOP_MODE, false)
        val initialBlockImages = prefBoolean(KEY_BLOCK_IMAGES, false)
        val initialEnableZoom = prefBoolean(KEY_ENABLE_ZOOM, true)
        val initialBlockPopups = prefBoolean(KEY_BLOCK_POPUPS, true)
        val initialThirdParty = prefBoolean(KEY_THIRD_PARTY_COOKIES, true)
        val initialSafeBrowsing = prefBoolean(KEY_SAFE_BROWSING, true)
        val initialAutoplay = prefBoolean(KEY_ALLOW_AUTOPLAY, true)
        val initialClearOnExit = prefBoolean(KEY_CLEAR_ON_EXIT, false)
        val initialFontScale = prefInt(KEY_FONT_SCALE, 100)

        switchDarkMode.isChecked = initialDark
        switchShowToolbar.isChecked = initialShowToolbar
        switchJavascript.isChecked = initialJs
        switchDesktopMode.isChecked = initialDesktop
        switchBlockImages.isChecked = initialBlockImages
        switchEnableZoom.isChecked = initialEnableZoom
        switchBlockPopups.isChecked = initialBlockPopups
        switchThirdPartyCookies.isChecked = initialThirdParty
        switchSafeBrowsing.isChecked = initialSafeBrowsing
        switchAutoplay.isChecked = initialAutoplay
        switchClearOnExit.isChecked = initialClearOnExit
        sliderFontScale.value = initialFontScale.toFloat()
        fontScaleValue.text = getString(R.string.settings_font_scale_value, initialFontScale)
        sliderFontScale.addOnChangeListener { _, value, _ ->
            fontScaleValue.text = getString(R.string.settings_font_scale_value, value.toInt())
        }

        btnImportBookmarks.setOnClickListener {
            importBookmarksLauncher.launch(arrayOf("text/html", "application/json", "text/*"))
        }

        btnExportBookmarks.setOnClickListener {
            if (bookmarkEntries().isEmpty()) {
                Toast.makeText(this, getString(R.string.bookmarks_export_none), Toast.LENGTH_SHORT).show()
            } else {
                val suggested = "surfscape-bookmarks-${System.currentTimeMillis() / 1000}.html"
                exportBookmarksLauncher.launch(suggested)
            }
        }

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
                val chosenEngine = searchEngines.getOrNull(selectedEngineIndex) ?: currentSearchEngine()
                val newDark = switchDarkMode.isChecked
                val newShowToolbar = switchShowToolbar.isChecked
                val newJs = switchJavascript.isChecked
                val newDesktop = switchDesktopMode.isChecked
                val newBlockImages = switchBlockImages.isChecked
                val newEnableZoom = switchEnableZoom.isChecked
                val newBlockPopups = switchBlockPopups.isChecked
                val newThirdParty = switchThirdPartyCookies.isChecked
                val newSafeBrowsing = switchSafeBrowsing.isChecked
                val newAutoplay = switchAutoplay.isChecked
                val newClearOnExit = switchClearOnExit.isChecked
                val newFontScale = sliderFontScale.value.toInt()

                prefs.edit()
                    .putString(KEY_HOMEPAGE, normalizedHomepage)
                    .putString(KEY_SEARCH_ENGINE, chosenEngine.id)
                    .putBoolean(KEY_DARK_MODE, newDark)
                    .putBoolean(KEY_SHOW_TOOLBAR, newShowToolbar)
                    .putBoolean(KEY_JS_ENABLED, newJs)
                    .putBoolean(KEY_DESKTOP_MODE, newDesktop)
                    .putBoolean(KEY_BLOCK_IMAGES, newBlockImages)
                    .putBoolean(KEY_ENABLE_ZOOM, newEnableZoom)
                    .putBoolean(KEY_BLOCK_POPUPS, newBlockPopups)
                    .putBoolean(KEY_THIRD_PARTY_COOKIES, newThirdParty)
                    .putBoolean(KEY_SAFE_BROWSING, newSafeBrowsing)
                    .putBoolean(KEY_ALLOW_AUTOPLAY, newAutoplay)
                    .putBoolean(KEY_CLEAR_ON_EXIT, newClearOnExit)
                    .putInt(KEY_FONT_SCALE, newFontScale)
                    .apply()
                val requiresReload = initialDark != newDark ||
                    initialBlockPopups != newBlockPopups ||
                    initialJs != newJs ||
                    initialDesktop != newDesktop ||
                    initialBlockImages != newBlockImages ||
                    initialEnableZoom != newEnableZoom ||
                    initialThirdParty != newThirdParty ||
                    initialSafeBrowsing != newSafeBrowsing ||
                    initialAutoplay != newAutoplay ||
                    initialFontScale != newFontScale
                applySettingsToAllTabs()
                applyUiPreferences()
                if (requiresReload) {
                    tabs.forEach { tab ->
                        if (tab.url.isNotBlank()) {
                            tab.webView.reload()
                        }
                    }
                }
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

    private fun applySettingsToAllTabs() {
        tabs.forEach { applySettingsToWebView(it) }
        activeTab?.let { updateReloadButton(it.isLoading) }
        applyUiPreferences()
        updateNavigationState()
    }

    private fun showTabSwitcherDialog() {
        if (tabs.isEmpty()) {
            return
        }
        val view = layoutInflater.inflate(R.layout.dialog_list, null)
        val recycler = view.findViewById<RecyclerView>(R.id.listRecycler)
        recycler.layoutManager = LinearLayoutManager(this)
        val entries = tabs.mapIndexed { index, tab ->
            val title = tab.title.takeIf { it.isNotBlank() } ?: getString(R.string.default_tab_title)
            val subtitle = if (tab.url.isBlank()) getString(R.string.status_ready) else getHostForStatus(tab.url)
            DialogEntry(index + 1, title, subtitle, tab.faviconDrawable ?: defaultFavicon)
        }
        val items = entries.map { DialogListItem.Entry(it) }
        lateinit var dialog: AlertDialog
        val adapter = DialogListAdapter(items) { entry ->
            val targetTab = tabs.getOrNull(entry.index - 1)
            if (targetTab != null) {
                selectTab(targetTab.id)
            }
            dialog.dismiss()
        }
        recycler.adapter = adapter
        dialog = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.tabs_dialog_title)
            .setView(view)
            .setNegativeButton(android.R.string.cancel, null)
            .create()
        dialog.show()
    }

    private fun buildHistoryListItems(): List<DialogListItem> {
        if (historyEntries.isEmpty()) return emptyList()
        val now = System.currentTimeMillis()
        val calendar = Calendar.getInstance().apply {
            timeInMillis = now
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        val startOfToday = calendar.timeInMillis
        val startOfYesterday = startOfToday - DAY_MS
        val startOfWeek = startOfToday - 7 * DAY_MS
        val startOfMonth = startOfToday - 30 * DAY_MS
        val last24hThreshold = now - DAY_MS

        val sections = listOf(
            getString(R.string.history_section_last_24h) to { ts: Long -> ts >= last24hThreshold },
            getString(R.string.history_section_yesterday) to { ts: Long -> ts in startOfYesterday until startOfToday },
            getString(R.string.history_section_last_week) to { ts: Long -> ts >= startOfWeek && ts < startOfYesterday },
            getString(R.string.history_section_last_month) to { ts: Long -> ts >= startOfMonth && ts < startOfWeek },
            getString(R.string.history_section_all_time) to { ts: Long -> ts < startOfMonth }
        )

        val buckets = LinkedHashMap<String, MutableList<HistoryEntry>>().apply {
            sections.forEach { (label, _) -> this[label] = mutableListOf() }
        }

        val sorted = historyEntries.sortedByDescending { it.timestamp }
        sorted.forEach { entry ->
            val label = sections.firstOrNull { (_, matcher) -> matcher(entry.timestamp) }?.first
                ?: sections.last().first
            buckets.getValue(label).add(entry)
        }

        val items = mutableListOf<DialogListItem>()
        var indexCounter = 1
        sections.forEach { (label, _) ->
            val sectionEntries = buckets[label].orEmpty()
            if (sectionEntries.isEmpty()) return@forEach
            items += DialogListItem.Section(label)
            sectionEntries.forEach { entry ->
                val icon = loadDrawableForPath(entry.iconPath) ?: loadDrawableForUrl(entry.url) ?: defaultFavicon
                val title = entry.title.takeIf { it.isNotBlank() } ?: getHostForStatus(entry.url)
                items += DialogListItem.Entry(DialogEntry(indexCounter++, title, entry.url, icon))
            }
        }
        return items
    }

    private fun showHistoryDialog() {
        if (historyEntries.isEmpty()) {
            Toast.makeText(this, getString(R.string.history_empty), Toast.LENGTH_SHORT).show()
            return
        }
        val view = layoutInflater.inflate(R.layout.dialog_list, null)
        val recycler = view.findViewById<RecyclerView>(R.id.listRecycler)
        recycler.layoutManager = LinearLayoutManager(this)
        val items = buildHistoryListItems()
        if (items.isEmpty()) {
            Toast.makeText(this, getString(R.string.history_empty), Toast.LENGTH_SHORT).show()
            return
        }
        lateinit var dialog: AlertDialog
        val adapter = DialogListAdapter(items) { entry ->
            loadInActiveTab(entry.subtitle)
            dialog.dismiss()
        }
        recycler.adapter = adapter
        val builder = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.history_title)
            .setView(view)
            .setPositiveButton(R.string.history_clear) { _, _ ->
                historyEntries.clear()
                saveHistory()
                Toast.makeText(this, getString(R.string.history_empty), Toast.LENGTH_SHORT).show()
                updateNavigationState()
            }
            .setNegativeButton(android.R.string.cancel, null)
        dialog = builder.create()
        dialog.show()
    }

    private fun showBookmarksDialog() {
        val entries = bookmarkEntries()
        if (entries.isEmpty()) {
            Toast.makeText(this, getString(R.string.bookmarks_empty), Toast.LENGTH_SHORT).show()
            return
        }
        val view = layoutInflater.inflate(R.layout.dialog_list, null)
        val recycler = view.findViewById<RecyclerView>(R.id.listRecycler)
        recycler.layoutManager = LinearLayoutManager(this)
        val dialogEntries = entries.mapIndexed { index, entry ->
            val title = entry.title.takeIf { it.isNotBlank() } ?: getHostForStatus(entry.url)
            DialogEntry(index + 1, title, entry.url, loadDrawableForBookmark(entry))
        }
        val items = dialogEntries.map { DialogListItem.Entry(it) }
        lateinit var dialog: AlertDialog
        val adapter = DialogListAdapter(items) { entry ->
            loadInActiveTab(entry.subtitle)
            dialog.dismiss()
        }
        recycler.adapter = adapter
        dialog = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.bookmarks_title)
            .setView(view)
            .setNegativeButton(android.R.string.cancel, null)
            .create()
        dialog.show()
    }

    private fun loadBookmarksRaw(): MutableSet<String> {
        val stored = prefs.getStringSet(KEY_BOOKMARKS, emptySet())
        return if (stored != null) HashSet(stored) else HashSet()
    }

    private fun saveBookmarksRaw(raw: Set<String>) {
        prefs.edit().putStringSet(KEY_BOOKMARKS, HashSet(raw)).apply()
        invalidateBookmarkCache()
    }

    private fun findBookmarkEntry(url: String, entries: Set<String>): String? {
        entries.forEach { entry ->
            when {
                entry.startsWith("{") -> {
                    try {
                        if (JSONObject(entry).optString("url") == url) return entry
                    } catch (_: Exception) {
                        // ignore corrupt entry
                    }
                }
                entry.contains(BOOKMARK_DELIMITER) -> {
                    val candidate = entry.substringAfter(BOOKMARK_DELIMITER, entry)
                    if (candidate == url) return entry
                }
                entry == url -> return entry
            }
        }
        return null
    }

    private fun parseBookmarkEntry(entry: String): BookmarkEntry {
        return when {
            entry.startsWith("{") -> {
                try {
                    val obj = JSONObject(entry)
                    val url = obj.optString("url")
                    val title = obj.optString("title", getHostForStatus(url))
                    val icon = obj.optString("icon").takeIf { it.isNotBlank() }
                    BookmarkEntry(title, url, icon)
                } catch (_: Exception) {
                    val url = entry
                    BookmarkEntry(getHostForStatus(url), url, getFaviconPathForUrl(url))
                }
            }
            entry.contains(BOOKMARK_DELIMITER) -> {
                val parts = entry.split(BOOKMARK_DELIMITER, limit = 2)
                val url = parts.getOrNull(1).orEmpty()
                val title = parts.getOrNull(0)?.takeIf { it.isNotBlank() } ?: getHostForStatus(url)
                BookmarkEntry(title, url, getFaviconPathForUrl(url))
            }
            else -> BookmarkEntry(getHostForStatus(entry), entry, getFaviconPathForUrl(entry))
        }
    }

    private fun recordHistory(title: String, url: String) {
        if (url.isBlank() || url.startsWith("about:")) return
        historyEntries.removeAll { it.url == url }
        val iconPath = getFaviconPathForUrl(url)
        historyEntries.add(HistoryEntry(title, url, System.currentTimeMillis(), iconPath))
        if (MAX_HISTORY != Int.MAX_VALUE && historyEntries.size > MAX_HISTORY) {
            historyEntries.subList(0, historyEntries.size - MAX_HISTORY).clear()
        }
        saveHistory()
        updateNavigationState()
    }

    private fun saveHistory() {
        val array = JSONArray()
        historyEntries.forEach { entry ->
            val obj = JSONObject()
            obj.put("title", entry.title)
            obj.put("url", entry.url)
            obj.put("timestamp", entry.timestamp)
            entry.iconPath?.let { obj.put("icon", it) }
            array.put(obj)
        }
        prefs.edit().putString(KEY_HISTORY, array.toString()).apply()
    }

    private fun loadHistory() {
        historyEntries.clear()
        val json = prefs.getString(KEY_HISTORY, null) ?: return
        try {
            val array = JSONArray(json)
            for (i in 0 until array.length()) {
                val obj = array.optJSONObject(i) ?: continue
                val url = obj.optString("url")
                if (url.isNullOrBlank()) continue
                val title = obj.optString("title", getHostForStatus(url))
                val timestamp = obj.optLong("timestamp", System.currentTimeMillis())
                val icon = obj.optString("icon").takeIf { it.isNotBlank() }
                historyEntries.add(HistoryEntry(title, url, timestamp, icon))
            }
        } catch (_: Exception) {
            historyEntries.clear()
        }
        updateNavigationState()
    }

    private fun applySettingsToWebView(tab: BrowserTab) {
        val settings = tab.webView.settings
        val jsEnabled = prefBoolean(KEY_JS_ENABLED, true)
        settings.javaScriptEnabled = jsEnabled
        val blockImages = prefBoolean(KEY_BLOCK_IMAGES, false)
        settings.loadsImagesAutomatically = !blockImages
        val desktopMode = prefBoolean(KEY_DESKTOP_MODE, false)
        settings.userAgentString = if (desktopMode) desktopUserAgent else mobileUserAgent
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = desktopMode
        val enableZoom = prefBoolean(KEY_ENABLE_ZOOM, true)
        settings.setSupportZoom(enableZoom)
        settings.builtInZoomControls = enableZoom
        settings.displayZoomControls = false
        val blockPopups = prefBoolean(KEY_BLOCK_POPUPS, true)
        settings.javaScriptCanOpenWindowsAutomatically = !blockPopups
        settings.setSupportMultipleWindows(!blockPopups)
        val allowAutoplay = prefBoolean(KEY_ALLOW_AUTOPLAY, true)
        settings.mediaPlaybackRequiresUserGesture = !allowAutoplay
        val fontScale = prefInt(KEY_FONT_SCALE, 100).coerceIn(50, 200)
        settings.textZoom = fontScale
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(settings, prefBoolean(KEY_DARK_MODE, true))
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.SAFE_BROWSING_ENABLE)) {
            WebSettingsCompat.setSafeBrowsingEnabled(settings, prefBoolean(KEY_SAFE_BROWSING, true))
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.safeBrowsingEnabled = prefBoolean(KEY_SAFE_BROWSING, true)
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(tab.webView, prefBoolean(KEY_THIRD_PARTY_COOKIES, true))
        }
    }

    private fun exportBookmarksToUri(uri: Uri) {
        val entries = bookmarkEntries()
        try {
            contentResolver.openOutputStream(uri)?.use { output ->
                output.bufferedWriter(Charsets.UTF_8).use { writer ->
                    val now = System.currentTimeMillis() / 1000
                    writer.appendLine("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
                    writer.appendLine("<!-- This is an automatically generated file. -->")
                    writer.appendLine("<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">")
                    writer.appendLine("<TITLE>Surfscape Bookmarks</TITLE>")
                    writer.appendLine("<H1>Surfscape Bookmarks</H1>")
                    writer.appendLine("<DL><p>")
                    entries.forEach { entry ->
                        val safeUrl = escapeHtml(entry.url)
                        val safeTitle = escapeHtml(entry.title)
                        writer.append("    <DT><A HREF=\"")
                        writer.append(safeUrl)
                        writer.append("\" ADD_DATE=\"")
                        writer.append(now.toString())
                        writer.append("\">")
                        writer.append(safeTitle)
                        writer.appendLine("</A>")
                    }
                    writer.appendLine("</DL><p>")
                    writer.flush()
                }
            } ?: throw IllegalStateException("No output stream")
            Toast.makeText(this, getString(R.string.bookmarks_export_success), Toast.LENGTH_SHORT).show()
        } catch (t: Throwable) {
            Toast.makeText(this, getString(R.string.bookmarks_export_failed), Toast.LENGTH_SHORT).show()
        }
    }

    private fun importBookmarksFromUri(uri: Uri) {
        setStatusOverride(getString(R.string.status_importing_bookmarks))
        lifecycleScope.launch(Dispatchers.IO) {
            val importedUrls = mutableSetOf<String>()
            val imported = try {
                val preview = contentResolver.openInputStream(uri)?.use { input ->
                    val buffer = ByteArray(4096)
                    val read = input.read(buffer)
                    if (read <= 0) "" else String(buffer, 0, read, Charsets.UTF_8)
                } ?: throw IllegalStateException("Empty file")
                val trimmed = preview.trimStart()
                val raw = loadBookmarksRaw()
                val result = if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
                    val full = contentResolver.openInputStream(uri)?.use { stream ->
                        stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
                    } ?: ""
                    importBookmarksJson(full, raw, importedUrls)
                } else {
                    contentResolver.openInputStream(uri)?.use { stream ->
                        importBookmarksHtmlStream(stream, raw, importedUrls)
                    } ?: -1
                }
                if (result > 0) {
                    saveBookmarksRaw(raw)
                }
                result
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, getString(R.string.bookmarks_import_failed), Toast.LENGTH_SHORT).show()
                    updateStatus(statusForActiveTab())
                    setStatusOverride(null)
                }
                return@launch
            }
            if (imported > 0) {
                preloadFaviconsForUrls(importedUrls)
            }
            withContext(Dispatchers.Main) {
                when {
                    imported < 0 -> Toast.makeText(this@MainActivity, getString(R.string.bookmarks_import_failed), Toast.LENGTH_SHORT).show()
                    imported == 0 -> Toast.makeText(this@MainActivity, getString(R.string.bookmarks_import_none), Toast.LENGTH_SHORT).show()
                    else -> {
                        updateBookmarkIcon()
                        updateNavigationState()
                        if (binding.urlBar.hasFocus()) {
                            updateSuggestions(binding.urlBar.text?.toString().orEmpty())
                        }
                        Toast.makeText(this@MainActivity, getString(R.string.bookmarks_import_success), Toast.LENGTH_SHORT).show()
                    }
                }
                updateStatus(statusForActiveTab())
                setStatusOverride(null)
            }
        }
    }

    private fun importBookmarksJson(content: String, target: MutableSet<String>, importedUrls: MutableSet<String>): Int {
        return try {
            val array = JSONArray(content)
            var imported = 0
            for (i in 0 until array.length()) {
                val element = array.get(i)
                val (title, url) = when (element) {
                    is JSONObject -> {
                        val urlValue = element.optString("url")
                        val titleValue = element.optString("title", getHostForStatus(urlValue))
                        titleValue to urlValue
                    }
                    is String -> getHostForStatus(element) to element
                    else -> continue
                }
                if (url.isBlank()) continue
                findBookmarkEntry(url, target)?.let { target.remove(it) }
                val icon = (element as? JSONObject)?.optString("icon")?.takeIf { it.isNotBlank() }
                target.add(buildBookmarkRecord(title, url, icon))
                importedUrls.add(url)
                imported++
            }
            imported
        } catch (_: Exception) {
            -1
        }
    }

    private fun importBookmarksHtmlStream(stream: InputStream, raw: MutableSet<String>, importedUrls: MutableSet<String>): Int {
        val reader = stream.bufferedReader(Charsets.UTF_8)
        val buffer = StringBuilder()
        val chunk = CharArray(4096)
        var totalImported = 0
        try {
            reader.use { r ->
                while (true) {
                    val read = r.read(chunk)
                    if (read == -1) break
                    buffer.append(chunk, 0, read)
                    totalImported += extractHtmlLinks(buffer, raw, importedUrls)
                }
            }
            totalImported += extractHtmlLinks(buffer, raw, importedUrls, final = true)
        } catch (_: Exception) {
            return -1
        }
        return totalImported
    }

    private fun htmlToPlain(text: String): String {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            Html.fromHtml(text, Html.FROM_HTML_MODE_LEGACY).toString().trim()
        } else {
            @Suppress("DEPRECATION")
            Html.fromHtml(text).toString().trim()
        }
    }

    private fun escapeHtml(value: String): String {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            Html.escapeHtml(value)
        } else {
            TextUtils.htmlEncode(value)
        }
    }

    private fun extractHtmlLinks(
        buffer: StringBuilder,
        raw: MutableSet<String>,
        importedUrls: MutableSet<String>,
        final: Boolean = false
    ): Int {
        var imported = 0
        var lastProcessedEnd = 0
        var searchStart = 0
        while (true) {
            val match = HTML_LINK_REGEX.find(buffer, searchStart) ?: break
            val end = match.range.last + 1
            val url = match.groupValues.getOrNull(1)?.trim().orEmpty()
            val titleHtml = match.groupValues.getOrNull(2)?.trim().orEmpty()
            if (url.isNotBlank()) {
                val title = htmlToPlain(titleHtml).ifBlank { getHostForStatus(url) }
                findBookmarkEntry(url, raw)?.let { raw.remove(it) }
                raw.add(buildBookmarkRecord(title, url))
                importedUrls.add(url)
                imported++
            }
            lastProcessedEnd = end
            searchStart = end
        }
        if (lastProcessedEnd > 0) {
            buffer.delete(0, lastProcessedEnd)
        } else if (!final && buffer.length > 8192) {
            val keepFrom = (buffer.length - 4096).coerceAtLeast(0)
            buffer.delete(0, keepFrom)
        }
        return imported
    }

    private fun buildBookmarkRecord(title: String, url: String, providedIcon: String? = null): String {
        val obj = JSONObject()
        obj.put("title", title)
        obj.put("url", url)
        val iconPath = providedIcon?.takeIf { it.isNotBlank() } ?: getFaviconPathForUrl(url)
        iconPath?.let { obj.put("icon", it) }
        return obj.toString()
    }

    private fun bookmarkEntries(): List<BookmarkEntry> {
        bookmarkCache?.let { return it }
        val list = loadBookmarksRaw()
            .map { parseBookmarkEntry(it) }
            .filter { it.url.isNotBlank() }
            .sortedBy { it.title.lowercase() }
        bookmarkCache = list
        return list
    }

    private fun invalidateBookmarkCache() {
        bookmarkCache = null
    }

    private fun loadDrawableForBookmark(entry: BookmarkEntry): Drawable? {
        return loadDrawableForPath(entry.iconPath) ?: loadDrawableForUrl(entry.url) ?: defaultFavicon
    }

    private fun loadDrawableForPath(path: String?): Drawable? {
        if (path.isNullOrBlank()) return null
        val file = File(path)
        if (!file.exists()) return null
        val bitmap = BitmapFactory.decodeFile(file.path) ?: return null
        return BitmapDrawable(resources, bitmap)
    }

    private fun loadDrawableForUrl(url: String): Drawable? {
        val host = hostFromUrl(url) ?: return null
        return loadFaviconDrawable(host)
    }

    private fun updateBookmarkIconPath(url: String, iconPath: String) {
        val raw = loadBookmarksRaw()
        val existing = findBookmarkEntry(url, raw) ?: return
        val current = parseBookmarkEntry(existing)
        if (current.iconPath == iconPath) return
        raw.remove(existing)
        val updated = buildBookmarkRecord(current.title, current.url, iconPath)
        raw.add(updated)
        saveBookmarksRaw(raw)
    }

    private fun updateHistoryIconPath(url: String, iconPath: String) {
        var changed = false
        for (i in historyEntries.indices) {
            val entry = historyEntries[i]
            if (entry.url == url && entry.iconPath != iconPath) {
                historyEntries[i] = entry.copy(iconPath = iconPath)
                changed = true
            }
        }
        if (changed) {
            saveHistory()
            if (binding.urlBar.hasFocus()) {
                updateSuggestions(binding.urlBar.text?.toString().orEmpty())
            }
        }
    }

    private fun preloadFaviconsForUrls(urls: Set<String>) {
        if (urls.isEmpty()) return
        lifecycleScope.launch(Dispatchers.IO) {
            urls.forEach { fetchFaviconForUrl(it) }
        }
    }

    private fun fetchFaviconForUrl(url: String) {
        val host = hostFromUrl(url) ?: return
        val file = faviconFile(host)
        if (file.exists()) {
            updateBookmarkIconPath(url, file.path)
            updateHistoryIconPath(url, file.path)
            return
        }
        val iconUrl = "https://www.google.com/s2/favicons?sz=64&domain=$host"
        var connection: HttpURLConnection? = null
        try {
            connection = (URL(iconUrl).openConnection() as? HttpURLConnection)?.apply {
                connectTimeout = 6000
                readTimeout = 6000
                useCaches = true
            } ?: return
            connection.inputStream.use { stream ->
                val bitmap = BitmapFactory.decodeStream(stream) ?: return
                saveFaviconBitmap(host, bitmap)
                val path = file.path
                updateBookmarkIconPath(url, path)
                updateHistoryIconPath(url, path)
            }
        } catch (_: Exception) {
            // ignore fetch failures
        } finally {
            connection?.disconnect()
        }
    }

    private fun saveFaviconForUrl(url: String, bitmap: Bitmap): Drawable {
        val host = hostFromUrl(url)
        if (host == null) {
            return BitmapDrawable(resources, bitmap)
        }
        val drawable = saveFaviconBitmap(host, bitmap)
        val path = faviconFile(host).path
        updateBookmarkIconPath(url, path)
        updateHistoryIconPath(url, path)
        return drawable
    }

    private fun saveFaviconBitmap(host: String, bitmap: Bitmap): Drawable {
        val file = faviconFile(host)
        try {
            file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        } catch (_: Exception) {
            // ignore write failures
        }
        val drawable = BitmapDrawable(resources, bitmap)
        faviconCache[host] = drawable
        return drawable
    }

    private fun getFaviconPathForUrl(url: String): String? {
        val host = hostFromUrl(url) ?: return null
        val file = faviconFile(host)
        return if (file.exists()) file.path else null
    }

    private fun loadFaviconDrawable(host: String): Drawable? {
        faviconCache[host]?.let { return it }
        val file = faviconFile(host)
        if (!file.exists()) return null
        val bitmap = BitmapFactory.decodeFile(file.path) ?: return null
        val drawable = BitmapDrawable(resources, bitmap)
        faviconCache[host] = drawable
        return drawable
    }

    private fun hostFromUrl(url: String?): String? {
        if (url.isNullOrBlank()) return null
        return try {
            Uri.parse(url)?.host?.lowercase()
        } catch (_: Exception) {
            null
        }
    }

    private fun faviconFile(host: String): File {
        val safe = host.replace("[^a-z0-9._-]".toRegex(), "_")
        return File(faviconDir, "$safe.png")
    }

    private inner class DialogListAdapter(
        private val items: List<DialogListItem>,
        private val onEntryClick: (DialogEntry) -> Unit
    ) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

        inner class SectionViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val title: TextView = view.findViewById(R.id.sectionTitle)
        }

        inner class EntryViewHolder(view: View) : RecyclerView.ViewHolder(view) {
            val index: TextView = view.findViewById(R.id.itemIndex)
            val icon: ImageView = view.findViewById(R.id.itemIcon)
            val title: TextView = view.findViewById(R.id.itemTitle)
            val subtitle: TextView = view.findViewById(R.id.itemSubtitle)
        }

        override fun getItemViewType(position: Int): Int {
            return when (items[position]) {
                is DialogListItem.Section -> DIALOG_TYPE_SECTION
                is DialogListItem.Entry -> DIALOG_TYPE_ENTRY
            }
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            val inflater = LayoutInflater.from(parent.context)
            return if (viewType == DIALOG_TYPE_SECTION) {
                val view = inflater.inflate(R.layout.item_dialog_section, parent, false)
                SectionViewHolder(view)
            } else {
                val view = inflater.inflate(R.layout.item_dialog_entry, parent, false)
                EntryViewHolder(view)
            }
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            when (val item = items[position]) {
                is DialogListItem.Section -> {
                    val sectionHolder = holder as SectionViewHolder
                    sectionHolder.title.text = item.title
                    sectionHolder.itemView.isClickable = false
                }
                is DialogListItem.Entry -> {
                    val entryHolder = holder as EntryViewHolder
                    val entry = item.data
                    entryHolder.index.text = "${entry.index}."
                    entryHolder.title.text = entry.title
                    entryHolder.subtitle.text = entry.subtitle
                    entryHolder.icon.setImageDrawable(entry.icon ?: defaultFavicon)
                    entryHolder.itemView.setOnClickListener { onEntryClick(entry) }
                }
            }
        }

        override fun getItemCount(): Int = items.size
    }

    private inner class SuggestionAdapter(context: Context) : ArrayAdapter<SuggestionItem>(context, 0, mutableListOf()) {
        private val items = mutableListOf<SuggestionItem>()

        fun update(newItems: List<SuggestionItem>) {
            items.clear()
            items.addAll(newItems)
            notifyDataSetChanged()
        }

        override fun getCount(): Int = items.size

        override fun getItem(position: Int): SuggestionItem? = items.getOrNull(position)

        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            return bindView(position, convertView, parent)
        }

        override fun getDropDownView(position: Int, convertView: View?, parent: ViewGroup): View {
            return bindView(position, convertView, parent)
        }

        override fun getFilter(): Filter = object : Filter() {
            override fun performFiltering(constraint: CharSequence?): FilterResults {
                return FilterResults().apply {
                    values = items
                    count = items.size
                }
            }

            override fun publishResults(constraint: CharSequence?, results: FilterResults?) {
                notifyDataSetChanged()
            }

            override fun convertResultToString(resultValue: Any?): CharSequence {
                return (resultValue as? SuggestionItem)?.url ?: ""
            }
        }

        private fun bindView(position: Int, convertView: View?, parent: ViewGroup): View {
            val context = parent.context
            val view = convertView ?: LayoutInflater.from(context)
                .inflate(R.layout.item_suggestion, parent, false)
            val title = view.findViewById<TextView>(R.id.suggestionTitle)
            val subtitle = view.findViewById<TextView>(R.id.suggestionSubtitle)
            val icon = view.findViewById<ImageView>(R.id.suggestionIcon)
            val item = items[position]
            title.text = item.display
            if (item.secondary.isNullOrBlank()) {
                subtitle.visibility = View.GONE
            } else {
                subtitle.text = item.secondary
                subtitle.visibility = View.VISIBLE
            }
            val itemIcon = item.icon
            if (itemIcon != null) {
                icon.imageTintList = null
                icon.setImageDrawable(itemIcon)
            } else {
                icon.imageTintList = ColorStateList.valueOf(ContextCompat.getColor(context, R.color.suggestion_icon_tint))
                icon.setImageDrawable(defaultFavicon)
            }
            return view
        }
    }

    private fun prefBoolean(key: String, default: Boolean): Boolean = prefs.getBoolean(key, default)

    private fun prefInt(key: String, default: Int): Int = prefs.getInt(key, default)

    private fun applyUiPreferences() {
        binding.topActionBar.isVisible = prefBoolean(KEY_SHOW_TOOLBAR, true)
    }

    private fun shouldClearOnExit(): Boolean = prefBoolean(KEY_CLEAR_ON_EXIT, false)

    private fun clearBrowsingData() {
        tabs.forEach { tab ->
            tab.webView.clearHistory()
            tab.webView.clearCache(true)
            tab.webView.clearFormData()
        }
        CookieManager.getInstance().apply {
            removeAllCookies(null)
            flush()
        }
        WebStorage.getInstance().deleteAllData()
        historyEntries.clear()
        prefs.edit()
            .remove(KEY_LAST_SESSION)
            .remove(KEY_LAST_URL)
            .remove(KEY_HISTORY)
            .apply()
        updateNavigationState()
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
        private const val KEY_JS_ENABLED = "js_enabled"
        private const val KEY_DARK_MODE = "dark_mode"
        private const val KEY_SHOW_TOOLBAR = "show_toolbar"
        private const val KEY_DESKTOP_MODE = "desktop_mode"
        private const val KEY_BLOCK_IMAGES = "block_images"
        private const val KEY_ENABLE_ZOOM = "enable_zoom"
        private const val KEY_BLOCK_POPUPS = "block_popups"
        private const val KEY_THIRD_PARTY_COOKIES = "third_party_cookies"
        private const val KEY_SAFE_BROWSING = "safe_browsing"
        private const val KEY_ALLOW_AUTOPLAY = "allow_autoplay"
        private const val KEY_CLEAR_ON_EXIT = "clear_on_exit"
        private const val KEY_HISTORY = "history_entries"
        private const val KEY_FONT_SCALE = "font_scale"
        private const val KEY_STATE_URLS = "state_urls"
        private const val KEY_STATE_ACTIVE_INDEX = "state_active_index"
        private const val HOME_URL_DEFAULT = "https://html.duckduckgo.com/html"
        private const val BOOKMARK_DELIMITER = "||"
        private const val MAX_HISTORY = Int.MAX_VALUE
        private const val DAY_MS = 24L * 60L * 60L * 1000L
        private const val DIALOG_TYPE_SECTION = 0
        private const val DIALOG_TYPE_ENTRY = 1
        private val HTML_LINK_REGEX = Regex("<A\\s+[^>]*HREF\\s*=\\s*\\\"([^\\\"]+)\\\"[^>]*>(.*?)</A>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
        private val SCHEME_REGEX = Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://")
    }
}
