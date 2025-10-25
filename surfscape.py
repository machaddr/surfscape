#!/usr/bin/env python3

from __future__ import annotations

import os, sys, json, asyncio, aiohttp, re, pyaudio, speech_recognition as sr, anthropic, markdown, time, platform, pickle
from urllib.parse import urlparse

_DOMAIN_TOKEN_PATTERN = re.compile(r"\|\|([a-z0-9*_.-]+)")
_PLAIN_DOMAIN_PATTERN = re.compile(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)")
import argparse, concurrent.futures, threading
from PyQt6.QtCore import QUrl, Qt , QDateTime, QThread, pyqtSignal, QObject, QStandardPaths, QTimer, QSize, QCoreApplication
from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QTabWidget, QToolBar, QMessageBox, QMenu, QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QColorDialog, QFontDialog, QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QCheckBox, QSpinBox, QComboBox, QSlider, QGroupBox, QGridLayout, QScrollArea, QTextEdit, QFrame, QWidget, QSplitter, QSizePolicy
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QShortcut, QColor, QFont, QStandardItemModel, QStandardItem, QImage, QImageWriter
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtNetwork import QNetworkCookie, QNetworkProxy, QNetworkAccessManager, QNetworkRequest, QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineProfile, QWebEngineSettings
from adblockparser import AdblockRules

# --- Multi-core / thread pool utilities ------------------------------------------------------

def _markdown_convert_task(text: str, enable_markdown: bool):
    """Isolated task function executed in a separate process for heavy markdown conversion.
    We re-import modules inside the process space to avoid large object pickling overhead.
    Returns HTML string.
    """
    try:
        if enable_markdown:
            try:
                import markdown as _md
                return _md.markdown(text, extensions=['fenced_code'])
            except Exception:
                pass
        # Fallback simple escaping if markdown fails inside worker
        import html
        return '<pre>' + html.escape(text) + '</pre>'
    except Exception as e:
        return f"<pre>Markdown render error: {e}</pre>"

class IOPool:
    """Thread-based executor for background work to keep the UI responsive."""
    def __init__(self, workers: int | None = None):
        if workers is None:
            base = os.cpu_count() or 1
            if base <= 1:
                target = 2
            else:
                # Default to 2x CPU count (minimum 4 threads) to overlap IO and CPU-light work
                target = max(4, base * 2)
        else:
            target = max(1, int(workers))
        # Keep the pool reasonably bounded while still leveraging multi-core systems
        self.workers = max(2, min(64, target))
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.workers)
        self._lock = threading.Lock()
        self._futures = set()

    def submit(self, fn, *args, callback=None):
        if self._executor is None:
            return None
        future = self._executor.submit(fn, *args)
        if callback is not None:
            from PyQt6.QtCore import QTimer
            def _dispatch(fut):
                try:
                    result = fut.result()
                except Exception as exc:
                    result = exc
                QTimer.singleShot(0, lambda r=result: callback(r))
            future.add_done_callback(_dispatch)
        with self._lock:
            self._futures.add(future)
        def _cleanup(fut):
            with self._lock:
                self._futures.discard(fut)
        future.add_done_callback(_cleanup)
        return future

    def shutdown(self, wait: bool = False):
        executor = self._executor
        if executor is None:
            return
        try:
            executor.shutdown(wait=wait, cancel_futures=not wait)
        finally:
            self._executor = None
            with self._lock:
                self._futures.clear()
                
# --- Network request interceptor with ad-blocking ------------------------------------------

class NetworkRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, browser, ad_blocker_rules=None, is_private=False, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.request_count = 0
        self.ad_blocker_rules = ad_blocker_rules
        self.is_private = is_private
        # Fast domain-level block set populated asynchronously (optional)
        self.domain_block_set = set()
        # Simple LRU cache for rule decisions to reduce repeated expensive checks
        from collections import deque
        self._decision_cache = {}
        self._decision_cache_order = deque()
        self._cache_limit = 4000  # slightly smaller to reduce memory churn
        # Per first-party domain statistics to derive "safe" heuristic
        self._fp_stats = {}  # first_party_host -> {'total':int,'blocked':int}
        self._safe_first_party = set()  # domains considered low-risk (skip some rule checks)
        # Cache of third-party hosts already confirmed clean for images/media to skip repeat checks
        self._clean_tp_hosts = set()
        # Resource types we may skip for safe domains (cheap, numerous)
        self._skip_types_safe = {"Image", "Font", "Media", "Favicon"}
    
    def interceptRequest(self, info):
        # Capture network request details for internal diagnostics
        self.request_count += 1

        rules_provider = self.ad_blocker_rules
        if not rules_provider:
            return

        try:
            req_url = info.requestUrl()
        except Exception:
            return
        if req_url is None:
            return

        url = req_url.toString()
        if not url:
            return
        host = req_url.host()
        request_type = self._get_request_type(info.resourceType())

        options, first_party_host = self._build_adblock_options(info)
        fp = options.get('domain', '')
        third_party = options.get('third-party', False)

        if fp in self._safe_first_party and request_type in self._skip_types_safe:
            return

        cache_key = (
            url,
            fp,
            request_type,
            1 if third_party else 0,
        )

        decision = self._decision_cache.get(cache_key)
        if decision is not None:
            if decision:
                info.block(True)
            return

        if third_party and host in self._clean_tp_hosts and request_type in self._skip_types_safe:
            return

        blocked = False
        try:
            if hasattr(rules_provider, 'should_block') and callable(getattr(rules_provider, 'should_block')):
                blocked = bool(rules_provider.should_block(url, options))
            else:
                engine = None
                if hasattr(rules_provider, 'get_rules_for') and callable(getattr(rules_provider, 'get_rules_for')):
                    engine = rules_provider.get_rules_for(fp, host)
                else:
                    engine = rules_provider
                if engine:
                    blocked = bool(engine.should_block(url, options))
        except Exception:
            blocked = False

        self._decision_cache[cache_key] = blocked
        self._decision_cache_order.append(cache_key)
        if len(self._decision_cache_order) > self._cache_limit:
            try:
                old = self._decision_cache_order.popleft()
                self._decision_cache.pop(old, None)
            except Exception:
                pass

        if blocked:
            info.block(True)
            if fp:
                st = self._fp_stats.setdefault(fp, {'total': 0, 'blocked': 0})
                st['total'] += 1
                st['blocked'] += 1
            return

        if third_party and request_type in self._skip_types_safe:
            self._clean_tp_hosts.add(host)
            if len(self._clean_tp_hosts) > 8000:
                self._clean_tp_hosts.clear()

        if fp:
            st = self._fp_stats.setdefault(fp, {'total': 0, 'blocked': 0})
            st['total'] += 1
            blocked_ratio = st['blocked'] / max(1, st['total'])
            if (st['total'] >= 40 and st['blocked'] == 0) or (st['total'] >= 80 and blocked_ratio <= 0.01):
                self._safe_first_party.add(fp)
    
    def _prefilter_hit(self, host: str) -> bool:
        """Check if host or its registrable parent appears in the domain prefilter set.
        This is a heuristic without PSL: checks exact host and last two labels.
        """
        try:
            h = host.lower()
            if h in self.domain_block_set:
                return True
            parts = h.split('.')
            if len(parts) >= 2:
                parent = parts[-2] + '.' + parts[-1]
                if parent in self.domain_block_set:
                    return True
        except Exception:
            pass
        return False

    def _build_adblock_options(self, info):
        """Build options for AdblockRules.should_block reflecting the current tab/context.
        Returns (options_dict, first_party_host).
        """
        # First-party (top-level document) host
        try:
            first_party_url = info.firstPartyUrl() if hasattr(info, 'firstPartyUrl') else None
            first_party_host = first_party_url.host() if first_party_url else ''
        except Exception:
            first_party_host = ''

        # Request host and type
        try:
            req_url = info.requestUrl()
            req_host = req_url.host()
        except Exception:
            req_host = ''

        # Determine third-party heuristic
        third_party = False
        if req_host and first_party_host:
            third_party = not self._same_site(req_host, first_party_host)

        # Resource type flags mapping
        rtype = info.resourceType()
        flags = {
            'document': rtype == 0,
            'subdocument': rtype == 1,
            'stylesheet': rtype == 2,
            'script': rtype == 3,
            'image': rtype == 4,
            'font': rtype == 5,
            'object': rtype == 6,
            'media': rtype == 7,
            'worker': rtype in (8, 9),
            'prefetch': rtype == 10,
            'favicon': rtype == 11,
            'xmlhttprequest': rtype == 12,
            'ping': rtype == 13,
            'serviceworker': rtype == 14,
        }
        # Build options supported by adblockparser
        options = {k: v for k, v in flags.items() if v}
        if first_party_host:
            options['domain'] = first_party_host
        if third_party:
            options['third-party'] = True
        return options, first_party_host

    def _same_site(self, host_a: str, host_b: str) -> bool:
        """Heuristic check whether two hosts are same-site (approximate eTLD+1).
        Avoids external deps; good enough for most cases though not PSL-accurate.
        """
        if host_a == host_b:
            return True
        # Normalize
        a = host_a.lower()
        b = host_b.lower()
        # Direct subdomain relationship
        if a.endswith('.' + b) or b.endswith('.' + a):
            return True
        # Fallback: compare last two labels
        def regdom(h: str):
            parts = h.split('.')
            return '.'.join(parts[-2:]) if len(parts) >= 2 else h
        return regdom(a) == regdom(b)

    def _get_request_type(self, resource_type):
        """Convert QWebEngineUrlRequestInfo resource type to string"""
        type_map = {
            0: "Document",      # ResourceTypeMainFrame
            1: "Subdocument",   # ResourceTypeSubFrame  
            2: "Stylesheet",    # ResourceTypeStylesheet
            3: "Script",        # ResourceTypeScript
            4: "Image",         # ResourceTypeImage
            5: "Font",          # ResourceTypeFontResource
            6: "Object",        # ResourceTypeSubResource
            7: "Media",         # ResourceTypeMedia
            8: "Worker",        # ResourceTypeWorker
            9: "SharedWorker",  # ResourceTypeSharedWorker
            10: "Prefetch",     # ResourceTypePrefetch
            11: "Favicon",      # ResourceTypeFavicon
            12: "XHR",          # ResourceTypeXhr
            13: "Ping",         # ResourceTypePing
            14: "ServiceWorker", # ResourceTypeServiceWorker
            15: "CSP Report",   # ResourceTypeCspReport
            16: "Plugin Resource" # ResourceTypePluginResource
        }
        return type_map.get(resource_type, "Other")

# --- Settings management --------------------------------------------------------------------

class SettingsManager:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.settings_file = os.path.join(data_dir, "settings.json")
        self._settings = self._load_default_settings()
        self.load_settings()
    
    def _load_default_settings(self):
        return {
            # General Settings
            'homepage': 'https://html.duckduckgo.com/html',
            'restore_session': True,
            'confirm_close_multiple_tabs': True,
            'open_new_tab_next_to_current': True,
            'show_tab_close_buttons': True,
            'enable_smooth_scrolling': False,
            
            # Appearance Settings
            'theme': 'system',  # system, light, dark, custom
            'background_color': 'system',
            'font_color': '#000000',
            'font_family': 'system',
            'font_size': 12,
            'ui_scale': 1.0,
            'show_toolbar': True,
            'show_bookmarks_bar': False,
            'show_status_bar': True,
            'tab_position': 'top',  # top, bottom
            
            # Privacy & Security Settings
            'enable_javascript': True,
            'enable_plugins': True,
            'enable_images': True,
            'enable_webgl': True,
            'enable_geolocation': False,
            'enable_notifications': True,
            'enable_autoplay': False,
            'block_popups': True,
            'enable_do_not_track': True,
            'clear_data_on_exit': False,
            'incognito_by_default': False,
            
            # Network & Proxy Settings
            'proxy_type': 'none',  # none, http, socks5, tor, i2p
            'proxy_host': '127.0.0.1',
            'proxy_port': 8080,
            'proxy_username': '',
            'proxy_password': '',
            'user_agent': 'default',
            'enable_dns_over_https': False,
            'dns_server': 'system',
            
            # Download Settings
            'download_directory': '',
            'ask_download_location': True,
            'auto_open_downloads': False,
            'max_concurrent_downloads': 3,
            
            # Search Settings
            'default_search_engine': 'duckduckgo',
            'custom_search_engines': {},
            'enable_search_suggestions': True,
            'search_in_address_bar': True,
            
            # Advanced Settings
            # Default to software on platforms that often crash with GPU drivers
            'enable_hardware_acceleration': True,
            'max_cache_size': 100,  # MB
            'enable_spell_check': True,
            'spell_check_language': 'en-US',
            'enable_accessibility': False,
            'custom_css': '',
            'custom_js': '',
            
            # AI Assistant Settings
            'ai_enabled': True,
            'ai_api_key': '',
            'ai_model': 'claude-sonnet-4-5-20250929',
            'ai_panel_position': 'right',
            'ai_panel_width': 0.3,
            'voice_recognition_language': 'en-US',
            
            # Keyboard Shortcuts
            'shortcuts': {
                'new_tab': 'Ctrl+T',
                'close_tab': 'Ctrl+W',
                'reload': 'Ctrl+R',
                'hard_reload': 'Ctrl+Shift+R',
                'find': 'Ctrl+F',
                'zoom_in': 'Ctrl+=',
                'zoom_out': 'Ctrl+-',
                'zoom_reset': 'Ctrl+0',
                'home': 'Alt+Home',
                'back': 'Alt+Left',
                'forward': 'Alt+Right',
                'bookmark': 'Ctrl+D',
                'bookmarks': 'Ctrl+Shift+B',
                'history': 'Ctrl+H',
                'downloads': 'Ctrl+J',
                'settings': 'Ctrl+,',
                'view_source': 'Ctrl+U',
                'fullscreen': 'F11',
                'private_tab': 'Ctrl+Shift+N',
                'ai_assistant': 'Ctrl+Shift+A'
            }
        }
    
    def get(self, key, default=None):
        keys = key.split('.')
        value = self._settings
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key, value):
        # Validate value before setting
        if not self._validate_setting(key, value):
            print(f"Warning: Invalid value for setting '{key}': {value}")
            return False
        
        keys = key.split('.')
        target = self._settings
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        return True
    
    def _validate_setting(self, key, value):
        """Validate setting values before storing them"""
        validators = {
            'homepage': self._validate_url,
            'font_size': lambda v: isinstance(v, int) and 8 <= v <= 32,
            'ui_scale': lambda v: isinstance(v, (int, float)) and 0.5 <= v <= 2.0,
            'proxy_port': lambda v: isinstance(v, int) and 1 <= v <= 65535,
            'max_cache_size': lambda v: isinstance(v, int) and 10 <= v <= 1000,
            'max_concurrent_downloads': lambda v: isinstance(v, int) and 1 <= v <= 10,
            'ai_panel_width': lambda v: isinstance(v, (int, float)) and 0.1 <= v <= 0.8,
            'background_color': self._validate_color,
            'font_color': self._validate_color,
        }
        
        # Get the base key (without dots) for validation
        base_key = key.split('.')[0] if '.' in key else key
        
        # Check if we have a specific validator
        if base_key in validators:
            try:
                return validators[base_key](value)
            except Exception as e:
                print(f"Validation error for {key}: {e}")
                return False
        
        # Boolean settings validation
        if key.startswith('enable_') or key.startswith('show_') or key.startswith('block_') or \
           key in ['restore_session', 'confirm_close_multiple_tabs', 'open_new_tab_next_to_current', 
                   'show_tab_close_buttons', 'clear_data_on_exit', 'incognito_by_default', 
                   'ask_download_location', 'auto_open_downloads', 'ai_enabled']:
            return isinstance(value, bool)
        
        # String settings validation
        if key in ['proxy_host', 'proxy_username', 'proxy_password', 'user_agent', 
                   'dns_server', 'download_directory', 'ai_api_key', 'ai_model', 
                   'font_family', 'custom_css', 'custom_js']:
            return isinstance(value, str)
        
        # Default: allow any value
        return True
    
    def _validate_url(self, url):
        """Validate URL format"""
        if not isinstance(url, str):
            return False
        if url.startswith(('http://', 'https://')):
            return True
        # Allow relative URLs or simple domains
        return len(url) > 0 and not any(char in url for char in ['<', '>', '"', "'"])
    
    def _validate_color(self, color):
        """Validate color format"""
        if not isinstance(color, str):
            return False
        # Check hex color format
        if color.startswith('#') and len(color) in [4, 7]:
            try:
                int(color[1:], 16)
                return True
            except ValueError:
                return False
        # Check named colors and system theme
        return color.lower() in ['white', 'black', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'system']
    
    def save_settings(self):
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=4)
        except Exception as e:
            print(f"Failed to save settings: {e}")
    
    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    loaded_settings = json.load(f)
                    self._merge_settings(loaded_settings)
        except Exception as e:
            print(f"Failed to load settings: {e}")
    
    def _merge_settings(self, loaded_settings):
        def merge_dict(default, loaded):
            for key, value in loaded.items():
                if key in default:
                    if isinstance(default[key], dict) and isinstance(value, dict):
                        merge_dict(default[key], value)
                    else:
                        default[key] = value
                else:
                    default[key] = value
        merge_dict(self._settings, loaded_settings)
         
    def reset_to_defaults(self):
        self._settings = self._load_default_settings()
        self.save_settings()
    
    def export_settings(self, filepath):
        try:
            with open(filepath, 'w') as f:
                json.dump(self._settings, f, indent=4)
            return True
        except Exception as e:
            print(f"Failed to export settings: {e}")
            return False
    
    def import_settings(self, filepath):
        try:
            with open(filepath, 'r') as f:
                imported_settings = json.load(f)
                self._merge_settings(imported_settings)
                self.save_settings()
            return True
        except Exception as e:
            print(f"Failed to import settings: {e}")
            return False

# --- Advanced Settings Dialog -----------------------------------------------------------------

class AdvancedSettingsDialog(QDialog):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.parent_browser = parent
        self.setWindowTitle("Surfscape Settings")
        self.setMinimumSize(800, 600)
        self.resize(800, 600)
        
        # Create main layout (don't set on dialog yet)
        main_layout = QHBoxLayout()
        
        # Create sidebar for categories
        self.sidebar = QListWidget()
        self.sidebar.setMaximumWidth(200)
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #ddd;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
        """)
        
        # Add categories
        categories = [
            "General", "Appearance", "Privacy & Security", "Network & Proxy",
            "Downloads", "Search", "Advanced", "AI Assistant", "Shortcuts",
            "Data Management", "Import/Export"
        ]
        
        for category in categories:
            self.sidebar.addItem(category)
        
        # Create scroll area for settings panels
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        # Create stacked widget for different setting panels
        self.settings_panels = {}
        self.current_panel = None
        
        # Add widgets to main layout
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.scroll_area, 1)
        
        # Create all settings panels
        self._create_all_panels()
        
        # Connect sidebar selection
        self.sidebar.currentItemChanged.connect(self._on_category_changed)
        
        # Select first category
        self.sidebar.setCurrentRow(0)
        
        # Create button layout
        button_layout = QHBoxLayout()
        
        # Import/Export buttons
        import_btn = QPushButton("Import Settings")
        import_btn.clicked.connect(self._import_settings)
        button_layout.addWidget(import_btn)
        
        export_btn = QPushButton("Export Settings")
        export_btn.clicked.connect(self._export_settings)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        
        # Reset and action buttons
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_settings)
        button_layout.addWidget(apply_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._ok_clicked)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        # Add button layout to main layout
        main_layout_wrapper = QVBoxLayout()
        main_layout_wrapper.addLayout(main_layout)
        main_layout_wrapper.addLayout(button_layout)
        
        self.setLayout(main_layout_wrapper)
    
    def _create_all_panels(self):
        self.settings_panels["General"] = self._create_general_panel()
        self.settings_panels["Appearance"] = self._create_appearance_panel()
        self.settings_panels["Privacy & Security"] = self._create_privacy_panel()
        self.settings_panels["Network & Proxy"] = self._create_network_panel()
        self.settings_panels["Downloads"] = self._create_downloads_panel()
        self.settings_panels["Search"] = self._create_search_panel()
        self.settings_panels["Advanced"] = self._create_advanced_panel()
        self.settings_panels["AI Assistant"] = self._create_ai_panel()
        self.settings_panels["Shortcuts"] = self._create_shortcuts_panel()
        self.settings_panels["Data Management"] = self._create_data_panel()
        self.settings_panels["Import/Export"] = self._create_import_export_panel()
    
    def _create_general_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Homepage
        group = QGroupBox("Startup")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Homepage:"), 0, 0)
        self.homepage_edit = QLineEdit(self.settings_manager.get('homepage'))
        group_layout.addWidget(self.homepage_edit, 0, 1)
        
        self.restore_session_cb = QCheckBox("Restore previous session on startup")
        self.restore_session_cb.setChecked(self.settings_manager.get('restore_session'))
        group_layout.addWidget(self.restore_session_cb, 1, 0, 1, 2)
        
        layout.addWidget(group)
        
        # Tabs
        group = QGroupBox("Tabs")
        group_layout = QGridLayout(group)
        
        self.confirm_close_cb = QCheckBox("Confirm before closing multiple tabs")
        self.confirm_close_cb.setChecked(self.settings_manager.get('confirm_close_multiple_tabs'))
        group_layout.addWidget(self.confirm_close_cb, 0, 0, 1, 2)
        
        self.new_tab_adjacent_cb = QCheckBox("Open new tabs next to current tab")
        self.new_tab_adjacent_cb.setChecked(self.settings_manager.get('open_new_tab_next_to_current'))
        group_layout.addWidget(self.new_tab_adjacent_cb, 1, 0, 1, 2)
        
        self.show_tab_close_cb = QCheckBox("Show close buttons on tabs")
        self.show_tab_close_cb.setChecked(self.settings_manager.get('show_tab_close_buttons'))
        group_layout.addWidget(self.show_tab_close_cb, 2, 0, 1, 2)
        
        layout.addWidget(group)
        
        # Scrolling
        group = QGroupBox("Scrolling")
        group_layout = QGridLayout(group)
        
        self.smooth_scrolling_cb = QCheckBox("Enable smooth scrolling")
        self.smooth_scrolling_cb.setChecked(self.settings_manager.get('enable_smooth_scrolling'))
        group_layout.addWidget(self.smooth_scrolling_cb, 0, 0, 1, 2)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_appearance_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Theme
        group = QGroupBox("Theme")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Theme:"), 0, 0)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["System", "Light", "Dark", "Custom"])
        current_theme = self.settings_manager.get('theme', 'system')
        theme_index = max(0, ['system', 'light', 'dark', 'custom'].index(current_theme.lower()))
        self.theme_combo.setCurrentIndex(theme_index)
        group_layout.addWidget(self.theme_combo, 0, 1)
        
        # Custom colors
        self.bg_color_btn = QPushButton("Background Color")
        self.bg_color_btn.clicked.connect(self._choose_bg_color)
        group_layout.addWidget(self.bg_color_btn, 1, 0)
        
        self.font_color_btn = QPushButton("Text Color")
        self.font_color_btn.clicked.connect(self._choose_font_color)
        group_layout.addWidget(self.font_color_btn, 1, 1)
        
        layout.addWidget(group)
        
        # Font
        group = QGroupBox("Font")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Font Family:"), 0, 0)
        self.font_family_combo = QComboBox()
        self.font_family_combo.addItems(["System Default", "Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana", "Georgia"])
        group_layout.addWidget(self.font_family_combo, 0, 1)
        
        group_layout.addWidget(QLabel("Font Size:"), 1, 0)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 32)
        self.font_size_spin.setValue(self.settings_manager.get('font_size', 12))
        group_layout.addWidget(self.font_size_spin, 1, 1)
        
        layout.addWidget(group)
        
        # UI Scale
        group = QGroupBox("Interface")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("UI Scale:"), 0, 0)
        self.ui_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.ui_scale_slider.setRange(50, 200)
        self.ui_scale_slider.setValue(int(self.settings_manager.get('ui_scale', 1.0) * 100))
        self.ui_scale_label = QLabel(f"{self.ui_scale_slider.value()}%")
        self.ui_scale_slider.valueChanged.connect(lambda v: self.ui_scale_label.setText(f"{v}%"))
        group_layout.addWidget(self.ui_scale_slider, 0, 1)
        group_layout.addWidget(self.ui_scale_label, 0, 2)
        
        # Toolbar options
        self.show_toolbar_cb = QCheckBox("Show toolbar")
        self.show_toolbar_cb.setChecked(self.settings_manager.get('show_toolbar', True))
        group_layout.addWidget(self.show_toolbar_cb, 1, 0, 1, 3)
        
        self.show_bookmarks_bar_cb = QCheckBox("Show bookmarks bar")
        self.show_bookmarks_bar_cb.setChecked(self.settings_manager.get('show_bookmarks_bar', False))
        group_layout.addWidget(self.show_bookmarks_bar_cb, 2, 0, 1, 3)
        
        self.show_status_bar_cb = QCheckBox("Show status bar")
        self.show_status_bar_cb.setChecked(self.settings_manager.get('show_status_bar', True))
        group_layout.addWidget(self.show_status_bar_cb, 3, 0, 1, 3)
        
        group_layout.addWidget(QLabel("Tab Position:"), 4, 0)
        self.tab_position_combo = QComboBox()
        self.tab_position_combo.addItems(["Top", "Bottom"])
        self.tab_position_combo.setCurrentText(self.settings_manager.get('tab_position', 'top').title())
        group_layout.addWidget(self.tab_position_combo, 4, 1)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_privacy_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Web Features
        group = QGroupBox("Web Features")
        group_layout = QGridLayout(group)
        
        self.javascript_cb = QCheckBox("Enable JavaScript")
        self.javascript_cb.setChecked(self.settings_manager.get('enable_javascript', True))
        group_layout.addWidget(self.javascript_cb, 0, 0)
        
        self.plugins_cb = QCheckBox("Enable Plugins")
        self.plugins_cb.setChecked(self.settings_manager.get('enable_plugins', True))
        group_layout.addWidget(self.plugins_cb, 0, 1)
        
        self.images_cb = QCheckBox("Load Images")
        self.images_cb.setChecked(self.settings_manager.get('enable_images', True))
        group_layout.addWidget(self.images_cb, 1, 0)
        
        self.webgl_cb = QCheckBox("Enable WebGL")
        self.webgl_cb.setChecked(self.settings_manager.get('enable_webgl', True))
        group_layout.addWidget(self.webgl_cb, 1, 1)
        
        layout.addWidget(group)
        
        # Privacy
        group = QGroupBox("Privacy")
        group_layout = QGridLayout(group)
        
        self.geolocation_cb = QCheckBox("Allow Geolocation")
        self.geolocation_cb.setChecked(self.settings_manager.get('enable_geolocation', False))
        group_layout.addWidget(self.geolocation_cb, 0, 0)
        
        self.notifications_cb = QCheckBox("Allow Notifications")
        self.notifications_cb.setChecked(self.settings_manager.get('enable_notifications', True))
        group_layout.addWidget(self.notifications_cb, 0, 1)
        
        self.autoplay_cb = QCheckBox("Allow Media Autoplay")
        self.autoplay_cb.setChecked(self.settings_manager.get('enable_autoplay', False))
        group_layout.addWidget(self.autoplay_cb, 1, 0)
        
        self.popups_cb = QCheckBox("Block Pop-ups")
        self.popups_cb.setChecked(self.settings_manager.get('block_popups', True))
        group_layout.addWidget(self.popups_cb, 1, 1)
        
        self.do_not_track_cb = QCheckBox("Send Do Not Track requests")
        self.do_not_track_cb.setChecked(self.settings_manager.get('enable_do_not_track', True))
        group_layout.addWidget(self.do_not_track_cb, 2, 0, 1, 2)
        
        layout.addWidget(group)
        
        # Data Management
        group = QGroupBox("Data Management")
        group_layout = QGridLayout(group)
        
        self.clear_on_exit_cb = QCheckBox("Clear browsing data on exit")
        self.clear_on_exit_cb.setChecked(self.settings_manager.get('clear_data_on_exit', False))
        group_layout.addWidget(self.clear_on_exit_cb, 0, 0, 1, 2)
        
        self.incognito_default_cb = QCheckBox("Use private browsing by default")
        self.incognito_default_cb.setChecked(self.settings_manager.get('incognito_by_default', False))
        group_layout.addWidget(self.incognito_default_cb, 1, 0, 1, 2)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_network_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Proxy Settings
        group = QGroupBox("Proxy Settings")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Proxy Type:"), 0, 0)
        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["None", "HTTP", "SOCKS5", "Tor", "I2P"])
        current_proxy = self.settings_manager.get('proxy_type', 'none')
        proxy_index = max(0, ['none', 'http', 'socks5', 'tor', 'i2p'].index(current_proxy.lower()))
        self.proxy_type_combo.setCurrentIndex(proxy_index)
        group_layout.addWidget(self.proxy_type_combo, 0, 1)
        
        group_layout.addWidget(QLabel("Host:"), 1, 0)
        self.proxy_host_edit = QLineEdit(self.settings_manager.get('proxy_host', '127.0.0.1'))
        group_layout.addWidget(self.proxy_host_edit, 1, 1)
        
        group_layout.addWidget(QLabel("Port:"), 2, 0)
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(1, 65535)
        self.proxy_port_spin.setValue(self.settings_manager.get('proxy_port', 8080))
        group_layout.addWidget(self.proxy_port_spin, 2, 1)
        
        group_layout.addWidget(QLabel("Username:"), 3, 0)
        self.proxy_username_edit = QLineEdit(self.settings_manager.get('proxy_username', ''))
        group_layout.addWidget(self.proxy_username_edit, 3, 1)
        
        group_layout.addWidget(QLabel("Password:"), 4, 0)
        self.proxy_password_edit = QLineEdit(self.settings_manager.get('proxy_password', ''))
        self.proxy_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        group_layout.addWidget(self.proxy_password_edit, 4, 1)
        
        layout.addWidget(group)
        
        # User Agent
        group = QGroupBox("User Agent")
        group_layout = QGridLayout(group)
        
        self.user_agent_combo = QComboBox()
        self.user_agent_combo.setEditable(True)
        self.user_agent_combo.addItems([
            "Default",
            "Chrome/Windows", "Chrome/macOS", "Chrome/Linux",
            "Firefox/Windows", "Firefox/macOS", "Firefox/Linux",
            "Safari/macOS", "Safari/iOS",
            "Edge/Windows",
            "Custom"
        ])
        current_ua = self.settings_manager.get('user_agent', 'default')
        if current_ua != 'default':
            self.user_agent_combo.setEditText(current_ua)
        group_layout.addWidget(self.user_agent_combo, 0, 0, 1, 2)
        
        layout.addWidget(group)
        
        # DNS Settings
        group = QGroupBox("DNS Settings")
        group_layout = QGridLayout(group)
        
        self.dns_over_https_cb = QCheckBox("Enable DNS over HTTPS")
        self.dns_over_https_cb.setChecked(self.settings_manager.get('enable_dns_over_https', False))
        group_layout.addWidget(self.dns_over_https_cb, 0, 0, 1, 2)
        
        group_layout.addWidget(QLabel("DNS Server:"), 1, 0)
        self.dns_server_combo = QComboBox()
        self.dns_server_combo.setEditable(True)
        self.dns_server_combo.addItems([
            "System Default",
            "1.1.1.1 (Cloudflare)",
            "8.8.8.8 (Google)",
            "9.9.9.9 (Quad9)",
            "208.67.222.222 (OpenDNS)"
        ])
        group_layout.addWidget(self.dns_server_combo, 1, 1)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_downloads_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Download Location
        group = QGroupBox("Download Location")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Default Directory:"), 0, 0)
        self.download_dir_edit = QLineEdit(self.settings_manager.get('download_directory', ''))
        group_layout.addWidget(self.download_dir_edit, 0, 1)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_download_dir)
        group_layout.addWidget(browse_btn, 0, 2)
        
        self.ask_location_cb = QCheckBox("Always ask where to save files")
        self.ask_location_cb.setChecked(self.settings_manager.get('ask_download_location', True))
        group_layout.addWidget(self.ask_location_cb, 1, 0, 1, 3)
        
        layout.addWidget(group)
        
        # Download Behavior
        group = QGroupBox("Download Behavior")
        group_layout = QGridLayout(group)
        
        self.auto_open_cb = QCheckBox("Automatically open downloaded files")
        self.auto_open_cb.setChecked(self.settings_manager.get('auto_open_downloads', False))
        group_layout.addWidget(self.auto_open_cb, 0, 0, 1, 2)
        
        group_layout.addWidget(QLabel("Max Concurrent Downloads:"), 1, 0)
        self.max_downloads_spin = QSpinBox()
        self.max_downloads_spin.setRange(1, 10)
        self.max_downloads_spin.setValue(self.settings_manager.get('max_concurrent_downloads', 3))
        group_layout.addWidget(self.max_downloads_spin, 1, 1)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_search_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Default Search Engine
        group = QGroupBox("Default Search Engine")
        group_layout = QGridLayout(group)
        
        self.search_engine_combo = QComboBox()
        self.search_engine_combo.addItems([
            "DuckDuckGo", "Google", "Bing", "Yahoo", "Startpage", "Searx", "Custom"
        ])
        current_engine = self.settings_manager.get('default_search_engine', 'duckduckgo')
        engine_map = {'duckduckgo': 0, 'google': 1, 'bing': 2, 'yahoo': 3, 'startpage': 4, 'searx': 5}
        self.search_engine_combo.setCurrentIndex(engine_map.get(current_engine.lower(), 0))
        group_layout.addWidget(self.search_engine_combo, 0, 0, 1, 2)
        
        layout.addWidget(group)
        
        # Search Options
        group = QGroupBox("Search Options")
        group_layout = QGridLayout(group)
        
        self.search_suggestions_cb = QCheckBox("Enable search suggestions")
        self.search_suggestions_cb.setChecked(self.settings_manager.get('enable_search_suggestions', True))
        group_layout.addWidget(self.search_suggestions_cb, 0, 0, 1, 2)
        
        self.search_in_address_cb = QCheckBox("Search from address bar")
        self.search_in_address_cb.setChecked(self.settings_manager.get('search_in_address_bar', True))
        group_layout.addWidget(self.search_in_address_cb, 1, 0, 1, 2)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_advanced_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Performance
        group = QGroupBox("Performance")
        group_layout = QGridLayout(group)
        
        self.hardware_accel_cb = QCheckBox("Enable hardware acceleration")
        self.hardware_accel_cb.setChecked(self.settings_manager.get('enable_hardware_acceleration', True))
        group_layout.addWidget(self.hardware_accel_cb, 0, 0, 1, 2)
        
        group_layout.addWidget(QLabel("Cache Size (MB):"), 1, 0)
        self.cache_size_spin = QSpinBox()
        self.cache_size_spin.setRange(10, 1000)
        self.cache_size_spin.setValue(self.settings_manager.get('max_cache_size', 100))
        group_layout.addWidget(self.cache_size_spin, 1, 1)
        
        layout.addWidget(group)
        
        # Accessibility
        group = QGroupBox("Accessibility")
        group_layout = QGridLayout(group)
        
        self.spell_check_cb = QCheckBox("Enable spell checking")
        self.spell_check_cb.setChecked(self.settings_manager.get('enable_spell_check', True))
        group_layout.addWidget(self.spell_check_cb, 0, 0, 1, 2)
        
        group_layout.addWidget(QLabel("Spell Check Language:"), 1, 0)
        self.spell_lang_combo = QComboBox()
        self.spell_lang_combo.addItems(["en-US", "en-GB", "es-ES", "fr-FR", "de-DE", "it-IT", "pt-BR"])
        self.spell_lang_combo.setCurrentText(self.settings_manager.get('spell_check_language', 'en-US'))
        group_layout.addWidget(self.spell_lang_combo, 1, 1)
        
        self.accessibility_cb = QCheckBox("Enable accessibility features")
        self.accessibility_cb.setChecked(self.settings_manager.get('enable_accessibility', False))
        group_layout.addWidget(self.accessibility_cb, 2, 0, 1, 2)
        
        layout.addWidget(group)
        
        # Custom Code
        group = QGroupBox("Custom Code")
        group_layout = QVBoxLayout(group)
        
        group_layout.addWidget(QLabel("Custom CSS:"))
        self.custom_css_edit = QTextEdit()
        self.custom_css_edit.setMaximumHeight(100)
        self.custom_css_edit.setPlainText(self.settings_manager.get('custom_css', ''))
        group_layout.addWidget(self.custom_css_edit)
        
        group_layout.addWidget(QLabel("Custom JavaScript:"))
        self.custom_js_edit = QTextEdit()
        self.custom_js_edit.setMaximumHeight(100)
        self.custom_js_edit.setPlainText(self.settings_manager.get('custom_js', ''))
        group_layout.addWidget(self.custom_js_edit)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_ai_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # AI Assistant
        group = QGroupBox("AI Assistant")
        group_layout = QGridLayout(group)
        
        self.ai_enabled_cb = QCheckBox("Enable AI Assistant")
        self.ai_enabled_cb.setChecked(self.settings_manager.get('ai_enabled', True))
        group_layout.addWidget(self.ai_enabled_cb, 0, 0, 1, 2)
        
        group_layout.addWidget(QLabel("API Key:"), 1, 0)
        self.ai_api_key_edit = QLineEdit(self.settings_manager.get('ai_api_key', ''))
        self.ai_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        group_layout.addWidget(self.ai_api_key_edit, 1, 1)
        
        group_layout.addWidget(QLabel("Model:"), 2, 0)
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        self.ai_model_combo.addItems([
            "claude-sonnet-4-5-20250929"
        ])
        self.ai_model_combo.setCurrentText(self.settings_manager.get('ai_model', 'claude-sonnet-4-5-20250929'))
        group_layout.addWidget(self.ai_model_combo, 2, 1)
        
        group_layout.addWidget(QLabel("Panel Position:"), 3, 0)
        self.ai_position_combo = QComboBox()
        self.ai_position_combo.addItems(["Right", "Left", "Bottom"])
        self.ai_position_combo.setCurrentText(self.settings_manager.get('ai_panel_position', 'right').title())
        group_layout.addWidget(self.ai_position_combo, 3, 1)
        
        group_layout.addWidget(QLabel("Panel Width:"), 4, 0)
        self.ai_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.ai_width_slider.setRange(20, 60)
        self.ai_width_slider.setValue(int(self.settings_manager.get('ai_panel_width', 0.3) * 100))
        self.ai_width_label = QLabel(f"{self.ai_width_slider.value()}%")
        self.ai_width_slider.valueChanged.connect(lambda v: self.ai_width_label.setText(f"{v}%"))
        group_layout.addWidget(self.ai_width_slider, 4, 1)
        group_layout.addWidget(self.ai_width_label, 4, 2)
        
        layout.addWidget(group)
        
        # Voice Recognition
        group = QGroupBox("Voice Recognition")
        group_layout = QGridLayout(group)
        
        group_layout.addWidget(QLabel("Language:"), 0, 0)
        self.voice_lang_combo = QComboBox()
        self.voice_lang_combo.addItems([
            "English (en-US)", "English (en-GB)", "Arabic (ar-SA)",
            "Chinese (zh-CN)", "Danish (da-DK)", "Dutch (nl-NL)",
            "Finnish (fi-FI)", "French (fr-FR)", "German (de-DE)",
            "Italian (it-IT)", "Japanese (ja-JP)", "Korean (ko-KR)",
            "Norwegian (nb-NO)", "Portuguese (pt-BR)", "Portuguese (pt-PT)",
            "Spanish (es-ES)", "Swedish (sv-SE)", "Ukrainian (uk-UA)"
        ])
        current_lang = self.settings_manager.get('voice_recognition_language', 'en-US')
        for i, item in enumerate(self.voice_lang_combo.model().item(i).text() for i in range(self.voice_lang_combo.count())):
            if current_lang in item:
                self.voice_lang_combo.setCurrentIndex(i)
                break
        group_layout.addWidget(self.voice_lang_combo, 0, 1)
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_shortcuts_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Shortcuts
        group = QGroupBox("Keyboard Shortcuts")
        group_layout = QGridLayout(group)
        
        self.shortcut_edits = {}
        shortcuts = self.settings_manager.get('shortcuts', {})
        
        row = 0
        for action, shortcut in shortcuts.items():
            label = action.replace('_', ' ').title()
            group_layout.addWidget(QLabel(f"{label}:"), row, 0)
            
            edit = QLineEdit(shortcut)
            edit.setReadOnly(True)
            self.shortcut_edits[action] = edit
            group_layout.addWidget(edit, row, 1)
            
            change_btn = QPushButton("Change")
            change_btn.clicked.connect(lambda _, a=action: self._change_shortcut(a))
            group_layout.addWidget(change_btn, row, 2)
            
            reset_btn = QPushButton("Reset")
            reset_btn.clicked.connect(lambda _, a=action: self._reset_shortcut(a))
            group_layout.addWidget(reset_btn, row, 3)
            
            row += 1
        
        layout.addWidget(group)
        layout.addStretch()
        
        return panel
    
    def _create_data_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # History Management
        history_group = QGroupBox("Browsing History")
        history_layout = QVBoxLayout(history_group)

        # History list with individual delete options
        self.history_list = QListWidget()
        try:
            self.history_list.setIconSize(QSize(16, 16))
        except Exception:
            pass
        self.history_list.setMaximumHeight(200)
        self._populate_history_list()
        history_layout.addWidget(self.history_list)

        history_buttons = QHBoxLayout()
        delete_history_item_btn = QPushButton("Delete Selected")
        delete_history_item_btn.clicked.connect(self._delete_selected_history)
        history_buttons.addWidget(delete_history_item_btn)

        clear_all_history_btn = QPushButton("Clear All History")
        clear_all_history_btn.clicked.connect(self._clear_history)
        history_buttons.addWidget(clear_all_history_btn)

        history_layout.addLayout(history_buttons)
        layout.addWidget(history_group)

        # Bookmarks Management (placed below Browsing History)
        bookmarks_group = QGroupBox("Bookmarks")
        bookmarks_layout = QVBoxLayout(bookmarks_group)

        self.bookmarks_list = QListWidget()
        self.bookmarks_list.setMaximumHeight(200)
        self._populate_bookmarks_list()
        bookmarks_layout.addWidget(self.bookmarks_list)

        bookmarks_buttons = QHBoxLayout()
        delete_bookmark_item_btn = QPushButton("Delete Selected")
        delete_bookmark_item_btn.clicked.connect(self._delete_selected_bookmarks)
        bookmarks_buttons.addWidget(delete_bookmark_item_btn)

        clear_all_bookmarks_btn = QPushButton("Clear All Bookmarks")
        clear_all_bookmarks_btn.clicked.connect(self._clear_bookmarks)
        bookmarks_buttons.addWidget(clear_all_bookmarks_btn)

        bookmarks_layout.addLayout(bookmarks_buttons)
        layout.addWidget(bookmarks_group)

        # Cookie Management
        cookies_group = QGroupBox("Cookies")
        cookies_layout = QVBoxLayout(cookies_group)

        # Cookies list with individual delete options
        self.cookies_list = QListWidget()
        self.cookies_list.setMaximumHeight(200)
        self._populate_cookies_list()
        cookies_layout.addWidget(self.cookies_list)

        cookies_buttons = QHBoxLayout()
        delete_cookie_item_btn = QPushButton("Delete Selected")
        delete_cookie_item_btn.clicked.connect(self._delete_selected_cookies)
        cookies_buttons.addWidget(delete_cookie_item_btn)

        clear_all_cookies_btn = QPushButton("Clear All Cookies")
        clear_all_cookies_btn.clicked.connect(self._clear_cookies)
        cookies_buttons.addWidget(clear_all_cookies_btn)

        cookies_layout.addLayout(cookies_buttons)
        layout.addWidget(cookies_group)

        # Cache Management
        cache_group = QGroupBox("Cache")
        cache_layout = QVBoxLayout(cache_group)

        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.clicked.connect(self._clear_cache)
        cache_layout.addWidget(clear_cache_btn)

        layout.addWidget(cache_group)

        # Bulk Operations
        bulk_group = QGroupBox("Bulk Operations")
        bulk_layout = QVBoxLayout(bulk_group)

        clear_all_btn = QPushButton("Clear All Data")
        clear_all_btn.clicked.connect(self._clear_all_data)
        clear_all_btn.setStyleSheet("QPushButton { background-color: #d32f2f; color: white; }")
        bulk_layout.addWidget(clear_all_btn)

        layout.addWidget(bulk_group)
        layout.addStretch()

        return panel
    
    def _create_import_export_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Import/Export
        group = QGroupBox("Backup & Restore")
        group_layout = QVBoxLayout(group)
        export_settings_btn = QPushButton("Export Settings")
        export_settings_btn.clicked.connect(self._export_settings)
        group_layout.addWidget(export_settings_btn)

        import_settings_btn = QPushButton("Import Settings")
        import_settings_btn.clicked.connect(self._import_settings)
        group_layout.addWidget(import_settings_btn)

        group_layout.addWidget(QLabel("Export/import all browser settings to/from a file."))
        layout.addWidget(group)

        # Bookmarks Import/Export
        bookmarks_group = QGroupBox("Bookmarks")
        bookmarks_layout = QVBoxLayout(bookmarks_group)
        export_bookmarks_btn = QPushButton("Export Bookmarks…")
        export_bookmarks_btn.clicked.connect(lambda: self.parent_browser.export_bookmarks() if self.parent_browser else None)
        bookmarks_layout.addWidget(export_bookmarks_btn)
        import_bookmarks_btn = QPushButton("Import Bookmarks…")
        import_bookmarks_btn.clicked.connect(lambda: self.parent_browser.import_bookmarks() if self.parent_browser else None)
        bookmarks_layout.addWidget(import_bookmarks_btn)
        bookmarks_layout.addWidget(QLabel("Backup or restore your bookmarks in JSON or HTML format."))
        layout.addWidget(bookmarks_group)

        # Reset
        group = QGroupBox("Reset")
        group_layout = QVBoxLayout(group)

        reset_btn = QPushButton("Reset All Settings to Default")
        reset_btn.clicked.connect(self._reset_to_defaults)
        reset_btn.setStyleSheet("QPushButton { background-color: #d32f2f; color: white; }")
        group_layout.addWidget(reset_btn)

        group_layout.addWidget(QLabel("This will reset all settings to their default values."))

        layout.addWidget(group)
        layout.addStretch()

        return panel
    
    def _on_category_changed(self, current, previous):
        if current:
            category = current.text()
            if category in self.settings_panels:
                # Clear previous widget safely
                if self.scroll_area.widget():
                    old_widget = self.scroll_area.takeWidget()
                    if old_widget:
                        old_widget.setParent(None)
                
                # Set new widget
                self.scroll_area.setWidget(self.settings_panels[category])
                self.current_panel = self.settings_panels[category]
    
    def _choose_bg_color(self):
        color = QColorDialog.getColor(QColor(self.settings_manager.get('background_color', '#ffffff')))
        if color.isValid():
            self.settings_manager.set('background_color', color.name())
    
    def _choose_font_color(self):
        color = QColorDialog.getColor(QColor(self.settings_manager.get('font_color', '#000000')))
        if color.isValid():
            self.settings_manager.set('font_color', color.name())
    
    def _browse_download_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if dir_path:
            self.download_dir_edit.setText(dir_path)
    
    def _change_shortcut(self, action):
        # Simplified shortcut change - in a real implementation, you'd capture key presses
        QMessageBox.information(self, "Change Shortcut", f"Shortcut changing for {action} not implemented in this demo")
    
    def _reset_shortcut(self, action):
        default_shortcuts = self.settings_manager._load_default_settings()['shortcuts']
        if action in default_shortcuts:
            self.shortcut_edits[action].setText(default_shortcuts[action])
    
    def _clear_history(self):
        if self.parent_browser:
            reply = QMessageBox.question(
                self, 
                "Clear All History", 
                "Are you sure you want to clear all browsing history?\n\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.parent_browser.clear_all_history()
                # Refresh the history list in the UI
                self._populate_history_list()
                QMessageBox.information(self, "Success", "All browsing history has been cleared.")
    
    def _clear_cookies(self):
        if self.parent_browser:
            reply = QMessageBox.question(
                self, 
                "Clear All Cookies", 
                "Are you sure you want to clear all cookies?\n\nThis will sign you out of websites and remove saved preferences.\nThis action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.parent_browser.remove_all_cookies()
                # Refresh the cookies list in the UI
                self._populate_cookies_list()
                QMessageBox.information(self, "Success", "All cookies have been cleared.")
    
    def _clear_cache(self):
        QMessageBox.information(self, "Success", "Cache cleared.")
    
    def _populate_history_list(self):
        """Populate the history list widget"""
        if hasattr(self.parent_browser, 'history'):
            self.history_list.clear()
            for title, url in self.parent_browser.history[-50:]:  # Last 50 entries
                item_text = f"{title} - {url}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, (title, url))
                # Apply favicon if available from cache only to avoid heavy loads here
                try:
                    if hasattr(self.parent_browser, '_get_favicon_cached'):
                        icon = self.parent_browser._get_favicon_cached(url)
                        if icon:
                            item.setIcon(icon)
                except Exception:
                    pass
                self.history_list.addItem(item)

    def _populate_bookmarks_list(self):
        """Populate the bookmarks list widget"""
        if hasattr(self.parent_browser, 'bookmarks'):
            self.bookmarks_list.clear()
            # Show all bookmarks (up to a reasonable cap for UI snappiness)
            for title, url in self.parent_browser.bookmarks[:500]:
                item_text = f"{title} - {url}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, (title, url))
                try:
                    if hasattr(self.parent_browser, '_get_favicon_cached'):
                        icon = self.parent_browser._get_favicon_cached(url)
                        if icon:
                            item.setIcon(icon)
                except Exception:
                    pass
                self.bookmarks_list.addItem(item)
    
    def _populate_cookies_list(self):
        """Populate the cookies list widget"""
        if hasattr(self.parent_browser, 'cookies'):
            self.cookies_list.clear()
            for cookie in self.parent_browser.cookies:
                item_text = f"{cookie.get('name', 'Unknown')} - {cookie.get('domain', 'Unknown domain')}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, cookie)
                self.cookies_list.addItem(item)
    
    def _delete_selected_history(self):
        """Delete selected history items"""
        selected_items = self.history_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select history items to delete.")
            return
        
        reply = QMessageBox.question(self, "Delete History Items", 
                                   f"Are you sure you want to delete {len(selected_items)} history item(s)?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                title, url = item.data(Qt.ItemDataRole.UserRole)
                # Remove from browser history
                if hasattr(self.parent_browser, 'history'):
                    self.parent_browser.history = [(t, u) for t, u in self.parent_browser.history if not (t == title and u == url)]
                # Remove from list
                self.history_list.takeItem(self.history_list.row(item))
            
            # Save updated history
            if hasattr(self.parent_browser, 'save_json') and hasattr(self.parent_browser, 'history_file'):
                self.parent_browser.save_json(self.parent_browser.history_file, self.parent_browser.history)
                self.parent_browser.update_history_menu()
            
            QMessageBox.information(self, "Success", f"Deleted {len(selected_items)} history item(s).")
    
    def _delete_selected_bookmarks(self):
        """Delete selected bookmarks"""
        selected_items = self.bookmarks_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select bookmarks to delete.")
            return
        
        reply = QMessageBox.question(self, "Delete Bookmarks", 
                                   f"Are you sure you want to delete {len(selected_items)} bookmark(s)?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                title, url = item.data(Qt.ItemDataRole.UserRole)
                # Remove from browser bookmarks
                if hasattr(self.parent_browser, 'bookmarks'):
                    self.parent_browser.bookmarks = [b for b in self.parent_browser.bookmarks if not (b[0] == title and b[1] == url)]
                # Remove from list
                self.bookmarks_list.takeItem(self.bookmarks_list.row(item))
            
            # Save updated bookmarks
            if hasattr(self.parent_browser, 'save_json') and hasattr(self.parent_browser, 'bookmarks_file'):
                self.parent_browser.save_json(self.parent_browser.bookmarks_file, self.parent_browser.bookmarks)
                self.parent_browser.update_bookmarks_menu()
            
            QMessageBox.information(self, "Success", f"Deleted {len(selected_items)} bookmark(s).")
    
    def _clear_bookmarks(self):
        """Clear all bookmarks"""
        if not hasattr(self.parent_browser, 'bookmarks'):
            return
        reply = QMessageBox.question(self, "Clear All Bookmarks", 
                                   "Are you sure you want to clear all bookmarks?\n\nThis action cannot be undone.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.parent_browser.bookmarks = []
            # Save and refresh UI
            if hasattr(self.parent_browser, 'save_json') and hasattr(self.parent_browser, 'bookmarks_file'):
                self.parent_browser.save_json(self.parent_browser.bookmarks_file, self.parent_browser.bookmarks)
            self.parent_browser.update_bookmarks_menu()
            self._populate_bookmarks_list()
            QMessageBox.information(self, "Success", "All bookmarks have been cleared.")
    
    def _delete_selected_cookies(self):
        """Delete selected cookies"""
        selected_items = self.cookies_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select cookies to delete.")
            return
        
        reply = QMessageBox.question(self, "Delete Cookies", 
                                   f"Are you sure you want to delete {len(selected_items)} cookie(s)?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected_items:
                cookie_data = item.data(Qt.ItemDataRole.UserRole)
                # Remove from browser cookies
                if hasattr(self.parent_browser, 'cookies'):
                    self.parent_browser.cookies = [c for c in self.parent_browser.cookies if c != cookie_data]
                # Remove from list
                self.cookies_list.takeItem(self.cookies_list.row(item))
            
            # Save updated cookies
            if hasattr(self.parent_browser, 'save_json') and hasattr(self.parent_browser, 'cookies_file'):
                self.parent_browser.save_json(self.parent_browser.cookies_file, self.parent_browser.cookies)
                self.parent_browser.update_cookies_menu()
            
            QMessageBox.information(self, "Success", f"Deleted {len(selected_items)} cookie(s).")
    
    def _clear_all_data(self):
        reply = QMessageBox.question(self, "Clear All Data", 
                                   "Are you sure you want to clear all browsing data?\nThis cannot be undone.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._clear_history()
            self._clear_cookies()
            self._clear_cache()
            # Refresh the lists
            self._populate_history_list()
            self._populate_cookies_list()
    
    def _export_settings(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Export Settings", "surfscape_settings.json", "JSON Files (*.json)")
        if filepath:
            if self.settings_manager.export_settings(filepath):
                QMessageBox.information(self, "Success", "Settings exported successfully.")
            else:
                QMessageBox.warning(self, "Error", "Failed to export settings.")
    
    def _import_settings(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Import Settings", "", "JSON Files (*.json)")
        if filepath:
            if self.settings_manager.import_settings(filepath):
                QMessageBox.information(self, "Success", "Settings imported successfully. Restart the browser to apply all changes.")
                self._refresh_ui()
            else:
                QMessageBox.warning(self, "Error", "Failed to import settings.")
    
    def _reset_to_defaults(self):
        reply = QMessageBox.question(self, "Reset Settings", 
                                   "Are you sure you want to reset all settings to default values?\nThis cannot be undone.",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.settings_manager.reset_to_defaults()
            self._refresh_ui()
            QMessageBox.information(self, "Success", "Settings reset to defaults.")
    
    def _refresh_ui(self):
        # Refresh all UI elements with current settings
        self.homepage_edit.setText(self.settings_manager.get('homepage'))
        # Add more UI refresh code as needed
    
    def _apply_settings(self):
        self._save_all_settings()
        if self.parent_browser:
            self.parent_browser._apply_settings_to_browser()
        QMessageBox.information(self, "Success", "Settings applied successfully.")
    
    def _ok_clicked(self):
        self._save_all_settings()
        if self.parent_browser:
            self.parent_browser._apply_settings_to_browser()
        self.accept()
    
    def _save_all_settings(self):
        # Save all settings from UI elements
        self.settings_manager.set('homepage', self.homepage_edit.text())
        self.settings_manager.set('restore_session', self.restore_session_cb.isChecked())
        self.settings_manager.set('confirm_close_multiple_tabs', self.confirm_close_cb.isChecked())
        self.settings_manager.set('open_new_tab_next_to_current', self.new_tab_adjacent_cb.isChecked())
        self.settings_manager.set('show_tab_close_buttons', self.show_tab_close_cb.isChecked())
        self.settings_manager.set('enable_smooth_scrolling', self.smooth_scrolling_cb.isChecked())
        
        # Appearance
        theme_map = ['system', 'light', 'dark', 'custom']
        self.settings_manager.set('theme', theme_map[self.theme_combo.currentIndex()])
        self.settings_manager.set('font_size', self.font_size_spin.value())
        self.settings_manager.set('ui_scale', self.ui_scale_slider.value() / 100.0)
        self.settings_manager.set('show_toolbar', self.show_toolbar_cb.isChecked())
        self.settings_manager.set('show_bookmarks_bar', self.show_bookmarks_bar_cb.isChecked())
        self.settings_manager.set('show_status_bar', self.show_status_bar_cb.isChecked())
        self.settings_manager.set('tab_position', self.tab_position_combo.currentText().lower())
        
        # Privacy
        self.settings_manager.set('enable_javascript', self.javascript_cb.isChecked())
        self.settings_manager.set('enable_plugins', self.plugins_cb.isChecked())
        self.settings_manager.set('enable_images', self.images_cb.isChecked())
        self.settings_manager.set('enable_webgl', self.webgl_cb.isChecked())
        self.settings_manager.set('enable_geolocation', self.geolocation_cb.isChecked())
        self.settings_manager.set('enable_notifications', self.notifications_cb.isChecked())
        self.settings_manager.set('enable_autoplay', self.autoplay_cb.isChecked())
        self.settings_manager.set('block_popups', self.popups_cb.isChecked())
        self.settings_manager.set('enable_do_not_track', self.do_not_track_cb.isChecked())
        self.settings_manager.set('clear_data_on_exit', self.clear_on_exit_cb.isChecked())
        self.settings_manager.set('incognito_by_default', self.incognito_default_cb.isChecked())
        
        # Network settings with validation
        proxy_map = ['none', 'http', 'socks5', 'tor', 'i2p']
        proxy_type = proxy_map[self.proxy_type_combo.currentIndex()]
        
        # Validate proxy settings if proxy is enabled
        if proxy_type != 'none':
            proxy_host = self.proxy_host_edit.text().strip()
            if not proxy_host:
                QMessageBox.warning(self, "Invalid Proxy", "Proxy host cannot be empty when proxy is enabled.")
                return False
            
            # Validate proxy port
            proxy_port = self.proxy_port_spin.value()
            if not (1 <= proxy_port <= 65535):
                QMessageBox.warning(self, "Invalid Port", "Proxy port must be between 1 and 65535.")
                return False
        self.settings_manager.set('proxy_type', proxy_type)
        self.settings_manager.set('proxy_host', self.proxy_host_edit.text())
        self.settings_manager.set('proxy_port', self.proxy_port_spin.value())
        self.settings_manager.set('proxy_username', self.proxy_username_edit.text())
        self.settings_manager.set('proxy_password', self.proxy_password_edit.text())
        self.settings_manager.set('proxy_host', self.proxy_host_edit.text())
        self.settings_manager.set('proxy_port', self.proxy_port_spin.value())
        self.settings_manager.set('proxy_username', self.proxy_username_edit.text())
        self.settings_manager.set('proxy_password', self.proxy_password_edit.text())
        self.settings_manager.set('user_agent', self.user_agent_combo.currentText())
        self.settings_manager.set('enable_dns_over_https', self.dns_over_https_cb.isChecked())
        self.settings_manager.set('dns_server', self.dns_server_combo.currentText())
        
        # Download settings with validation
        download_dir = self.download_dir_edit.text().strip()
        if download_dir and not os.path.exists(download_dir):
            reply = QMessageBox.question(self, "Invalid Directory", 
                                        f"Download directory does not exist: {download_dir}\n" +
                                        "Do you want to create it?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(download_dir, exist_ok=True)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to create directory: {str(e)}")
                    return False
            else:
                return False
        
        self.settings_manager.set('download_directory', download_dir)
        self.settings_manager.set('ask_download_location', self.ask_location_cb.isChecked())
        self.settings_manager.set('auto_open_downloads', self.auto_open_cb.isChecked())
        self.settings_manager.set('max_concurrent_downloads', self.max_downloads_spin.value())
        
        # Search
        search_map = ['duckduckgo', 'google', 'bing', 'yahoo', 'startpage', 'searx', 'custom']
        self.settings_manager.set('default_search_engine', search_map[self.search_engine_combo.currentIndex()])
        self.settings_manager.set('enable_search_suggestions', self.search_suggestions_cb.isChecked())
        self.settings_manager.set('search_in_address_bar', self.search_in_address_cb.isChecked())
        
        # Advanced
        self.settings_manager.set('enable_hardware_acceleration', self.hardware_accel_cb.isChecked())
        self.settings_manager.set('max_cache_size', self.cache_size_spin.value())
        self.settings_manager.set('enable_spell_check', self.spell_check_cb.isChecked())
        self.settings_manager.set('spell_check_language', self.spell_lang_combo.currentText())
        self.settings_manager.set('enable_accessibility', self.accessibility_cb.isChecked())
        self.settings_manager.set('custom_css', self.custom_css_edit.toPlainText())
        self.settings_manager.set('custom_js', self.custom_js_edit.toPlainText())
        
        # AI settings with validation
        self.settings_manager.set('ai_enabled', self.ai_enabled_cb.isChecked())
        
        api_key = self.ai_api_key_edit.text().strip()
        if self.ai_enabled_cb.isChecked() and not api_key:
            reply = QMessageBox.question(self, "Missing API Key", 
                                        "AI Assistant is enabled but no API key is provided. " +
                                        "The AI features will not work. Continue anyway?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return False
        
        self.settings_manager.set('ai_api_key', api_key)
        self.settings_manager.set('ai_model', self.ai_model_combo.currentText())
        self.settings_manager.set('ai_panel_position', self.ai_position_combo.currentText().lower())
        self.settings_manager.set('ai_panel_width', self.ai_width_slider.value() / 100.0)
        
        # Voice recognition language
        try:
            voice_lang_text = self.voice_lang_combo.currentText()
            lang_code = voice_lang_text.split('(')[1].strip(')')
            self.settings_manager.set('voice_recognition_language', lang_code)
        except (IndexError, AttributeError):
            self.settings_manager.set('voice_recognition_language', 'en-US')
        
        # Save shortcuts with validation
        shortcuts = {}
        for action, edit in self.shortcut_edits.items():
            shortcut_text = edit.text().strip()
            if shortcut_text:
                # Basic shortcut validation
                try:
                    QKeySequence(shortcut_text)
                    shortcuts[action] = shortcut_text
                except Exception:
                    print(f"Invalid shortcut for {action}: {shortcut_text}")
        self.settings_manager.set('shortcuts', shortcuts)
    
        # Save to file
        self.settings_manager.save_settings()
        return True

# --- Download Manager Dialog -------------------------------------------------------------------

class DownloadItem:
    def __init__(self, download_request):
        self.download_request = download_request
        self.filename = download_request.suggestedFileName()
        self.url = download_request.url().toString()
        self.total_bytes = download_request.totalBytes()
        self.received_bytes = 0
        self.state = "In Progress"
        self.progress = 0
        self._progress_timer = None

# --- Download Manager Dialog -------------------------------------------------------------------

class DownloadManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Manager")
        self.setMinimumSize(600, 400)
        self.downloads = []
        
        layout = QVBoxLayout(self)
        
        self.downloads_table = QTableWidget(0, 5)
        self.downloads_table.setHorizontalHeaderLabels([
            "Filename", "URL", "Progress", "Size", "Status"
        ])
        self.downloads_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.downloads_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.downloads_table)
        
        button_layout = QHBoxLayout()
        self.clear_completed_btn = QPushButton("Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed_downloads)
        self.open_folder_btn = QPushButton("Open Downloads Folder")
        self.open_folder_btn.clicked.connect(self.open_downloads_folder)
        
        button_layout.addWidget(self.clear_completed_btn)
        button_layout.addWidget(self.open_folder_btn)
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def add_download(self, download_item):
        self.downloads.append(download_item)
        row = self.downloads_table.rowCount()
        self.downloads_table.insertRow(row)
        
        self.downloads_table.setItem(row, 0, QTableWidgetItem(download_item.filename))
        self.downloads_table.setItem(row, 1, QTableWidgetItem(download_item.url))
        
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        self.downloads_table.setCellWidget(row, 2, progress_bar)
        
        size_text = self.format_bytes(download_item.total_bytes) if download_item.total_bytes > 0 else "Unknown"
        self.downloads_table.setItem(row, 3, QTableWidgetItem(size_text))
        self.downloads_table.setItem(row, 4, QTableWidgetItem(download_item.state))
        
        try:
            from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
        except Exception:
            QWebEngineDownloadRequest = None

        # Poll progress periodically
        progress_timer = QTimer(self)
        progress_timer.setInterval(250)

        def _poll_progress(_row=row, item=download_item):
            try:
                received = int(item.download_request.receivedBytes())
            except Exception:
                received = item.received_bytes
            try:
                total = int(item.download_request.totalBytes())
            except Exception:
                total = item.total_bytes
            self.update_progress(_row, received, total)

        progress_timer.timeout.connect(_poll_progress)
        progress_timer.start()
        download_item._progress_timer = progress_timer

        # React to state changes for completion/cancel/interruption
        def _on_state_changed(state, _row=row, item=download_item):
            # Stop timer when no longer in progress
            if hasattr(item, '_progress_timer') and item._progress_timer is not None:
                try:
                    # For Completed/Cancelled/Interrupted stop polling
                    if QWebEngineDownloadRequest is None or state in (
                        getattr(QWebEngineDownloadRequest.DownloadState, 'DownloadCompleted', 2),
                        getattr(QWebEngineDownloadRequest.DownloadState, 'DownloadCancelled', 3),
                        getattr(QWebEngineDownloadRequest.DownloadState, 'DownloadInterrupted', 4),
                    ):
                        item._progress_timer.stop()
                        item._progress_timer.deleteLater()
                        item._progress_timer = None
                except Exception:
                    # Best-effort cleanup
                    try:
                        item._progress_timer.stop()
                        item._progress_timer.deleteLater()
                    except Exception:
                        pass
                    item._progress_timer = None

            # Update status by state
            try:
                if QWebEngineDownloadRequest and state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                    self.download_finished(_row)
                elif QWebEngineDownloadRequest and state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
                    if _row < len(self.downloads):
                        self.downloads[_row].state = "Cancelled"
                        self.downloads_table.setItem(_row, 4, QTableWidgetItem("Cancelled"))
                elif QWebEngineDownloadRequest and state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
                    if _row < len(self.downloads):
                        self.downloads[_row].state = "Interrupted"
                        self.downloads_table.setItem(_row, 4, QTableWidgetItem("Interrupted"))
                else:
                    # Fallback: when no enum available, mark as completed when received==total
                    item = self.downloads[_row] if _row < len(self.downloads) else None
                    if item and item.total_bytes > 0 and item.received_bytes >= item.total_bytes:
                        self.download_finished(_row)
            except Exception:
                pass

        # Connect state change if available
        try:
            download_item.download_request.stateChanged.connect(_on_state_changed)
        except Exception:
            # If stateChanged not available, try finished or rely on polling fallback
            try:
                download_item.download_request.finished.connect(lambda _row=row: self.download_finished(_row))
            except Exception:
                pass
    
    def update_progress(self, row, received_bytes, total_bytes):
        if row < len(self.downloads):
            download_item = self.downloads[row]
            download_item.received_bytes = received_bytes
            download_item.total_bytes = total_bytes
            
            if total_bytes > 0:
                progress = int((received_bytes / total_bytes) * 100)
                download_item.progress = progress
                
                progress_bar = self.downloads_table.cellWidget(row, 2)
                if progress_bar:
                    progress_bar.setValue(progress)
                
                size_text = f"{self.format_bytes(received_bytes)} / {self.format_bytes(total_bytes)}"
                self.downloads_table.setItem(row, 3, QTableWidgetItem(size_text))
    
    def download_finished(self, row):
        if row < len(self.downloads):
            download_item = self.downloads[row]
            download_item.state = "Completed"
            self.downloads_table.setItem(row, 4, QTableWidgetItem("Completed"))
            
            progress_bar = self.downloads_table.cellWidget(row, 2)
            if progress_bar:
                progress_bar.setValue(100)
            # Ensure progress timer is stopped/cleaned
            if hasattr(download_item, '_progress_timer') and download_item._progress_timer:
                try:
                    download_item._progress_timer.stop()
                    download_item._progress_timer.deleteLater()
                except Exception:
                    pass
                download_item._progress_timer = None
    
    def clear_completed_downloads(self):
        rows_to_remove = []
        for i, download in enumerate(self.downloads):
            if download.state == "Completed":
                rows_to_remove.append(i)
        
        for row in reversed(rows_to_remove):
            self.downloads_table.removeRow(row)
            del self.downloads[row]
    
    def open_downloads_folder(self):
        downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if os.path.exists(downloads_path):
            os.system(f'xdg-open "{downloads_path}"' if os.name != 'nt' else f'explorer "{downloads_path}"')
    
    def format_bytes(self, bytes_count):
        """Format a byte count into a human-readable string.
        Handles edge cases and avoids using os.path math functions.
        """
        try:
            import math
        except ImportError:
            # Fallback: simple formatting
            return f"{bytes_count} B"

        if bytes_count is None or bytes_count < 0:
            return "Unknown"
        if bytes_count == 0:
            return "0 B"

        k = 1024.0
        sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        i = int(math.floor(math.log(bytes_count, k))) if bytes_count > 0 else 0
        i = max(0, min(i, len(sizes) - 1))
        value = bytes_count / (k ** i)
        # Use 2 decimal places for KB and above, no decimals for bytes
        formatted = f"{value:.2f}" if i > 0 else f"{int(value)}"
        return f"{formatted} {sizes[i]}"

# --- Find in Page Dialog ----------------------------------------------------------------------\

class FindDialog(QDialog):
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.setWindowTitle("Find in Page")
        self.setModal(False)
        self.setFixedSize(400, 100)
        
        layout = QVBoxLayout(self)
        
        search_layout = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search text...")
        self.search_field.returnPressed.connect(self.find_next)
        search_layout.addWidget(self.search_field)
        
        self.find_next_btn = QPushButton("Next")
        self.find_next_btn.clicked.connect(self.find_next)
        search_layout.addWidget(self.find_next_btn)
        
        self.find_prev_btn = QPushButton("Previous")
        self.find_prev_btn.clicked.connect(self.find_previous)
        search_layout.addWidget(self.find_prev_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        search_layout.addWidget(close_btn)
        
        layout.addLayout(search_layout)
        
        self.match_label = QLabel("No matches found")
        layout.addWidget(self.match_label)
        
        self.search_field.textChanged.connect(self.search_text_changed)
    
    def find_next(self):
        text = self.search_field.text()
        if text:
            current_widget = self.browser.tabs.currentWidget()
            if current_widget:
                current_widget.findText(text)
    
    def find_previous(self):
        text = self.search_field.text()
        if text:
            current_widget = self.browser.tabs.currentWidget()
            if current_widget:
                from PyQt6.QtWebEngineCore import QWebEnginePage
                current_widget.findText(text, QWebEnginePage.FindFlag.FindBackward)
    
    def search_text_changed(self):
        text = self.search_field.text()
        if text:
            self.find_next()
        else:
            current_widget = self.browser.tabs.currentWidget()
            if current_widget:
                current_widget.findText("")
    
    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_field.setFocus()
        self.search_field.selectAll()
        
# --- Source View Dialog -----------------------------------------------------------------------

class SourceViewDialog(QDialog):
    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.setWindowTitle("View Source")
        self.setMinimumSize(900, 700)
        
        layout = QVBoxLayout(self)
        
        # Create tabs for different source types
        tabs = QTabWidget()
        
        # HTML tab
        self.html_widget = QTextEdit()
        self.html_widget.setReadOnly(True)
        self.html_widget.setStyleSheet("font-family: 'Courier New', monospace; font-size: 12px;")
        tabs.addTab(self.html_widget, "HTML")
        
        # CSS tab
        self.css_widget = QTextEdit()
        self.css_widget.setReadOnly(True)
        self.css_widget.setStyleSheet("font-family: 'Courier New', monospace; font-size: 12px;")
        tabs.addTab(self.css_widget, "CSS")
        
        # JavaScript tab
        self.js_widget = QTextEdit()
        self.js_widget.setReadOnly(True)
        self.js_widget.setStyleSheet("font-family: 'Courier New', monospace; font-size: 12px;")
        tabs.addTab(self.js_widget, "JavaScript")
        
        layout.addWidget(tabs)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_source)
        button_layout.addWidget(refresh_btn)
        
        save_btn = QPushButton("Save As...")
        save_btn.clicked.connect(self.save_source)
        button_layout.addWidget(save_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        self.tabs = tabs
        
        # Refresh source with error handling
        try:
            self.refresh_source()
        except Exception as e:
            self.html_widget.setPlainText(f"Error loading source: {str(e)}")
            self.css_widget.setPlainText(f"/* Error loading CSS: {str(e)} */")
            self.js_widget.setPlainText(f"// Error loading JavaScript: {str(e)}")
    
    def refresh_source(self):
        if not hasattr(self.browser, 'tabs') or self.browser.tabs is None:
            self.html_widget.setPlainText("Browser tabs not available yet")
            self.css_widget.setPlainText("/* Browser tabs not available yet */")
            self.js_widget.setPlainText("// Browser tabs not available yet")
            return
            
        current_widget = self.browser.tabs.currentWidget()
        if current_widget:
            current_widget.page().toHtml(self.parse_and_display_source)
        else:
            self.html_widget.setPlainText("No active tab to view source")
            self.css_widget.setPlainText("/* No active tab to view source */")
            self.js_widget.setPlainText("// No active tab to view source")
    
    def parse_and_display_source(self, html_content):
        # Extract and display HTML
        self.html_widget.setPlainText(html_content)
        
        # Extract CSS from <style> tags and <link> stylesheets
        css_content = self.extract_css(html_content)
        self.css_widget.setPlainText(css_content)
        
        # Extract JavaScript from <script> tags
        js_content = self.extract_javascript(html_content)
        self.js_widget.setPlainText(js_content)
    
    def extract_css(self, html_content):
        import re
        css_parts = []
        
        # Extract inline CSS from <style> tags
        style_pattern = r'<style[^>]*>(.*?)</style>'
        styles = re.findall(style_pattern, html_content, re.DOTALL | re.IGNORECASE)
        for style in styles:
            css_parts.append("/* Inline CSS */\n" + style.strip())
        
        # Extract linked CSS (show URLs)
        link_pattern = r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*>'
        links = re.findall(link_pattern, html_content, re.IGNORECASE)
        for link in links:
            css_parts.append(f"/* External CSS: {link} */\n/* Content not available in page source */\n")
        
        return '\n\n'.join(css_parts) if css_parts else "/* No CSS found in page source */"
    
    def extract_javascript(self, html_content):
        import re
        js_parts = []
        
        # Extract inline JavaScript from <script> tags
        script_pattern = r'<script[^>]*>(.*?)</script>'
        scripts = re.findall(script_pattern, html_content, re.DOTALL | re.IGNORECASE)
        for script in scripts:
            if script.strip():
                js_parts.append("// Inline JavaScript\n" + script.strip())
        
        # Extract external JavaScript (show URLs)
        external_pattern = r'<script[^>]*src=["\']([^"\']+)["\'][^>]*>'
        externals = re.findall(external_pattern, html_content, re.IGNORECASE)
        for external in externals:
            js_parts.append(f"// External JavaScript: {external}\n// Content not available in page source\n")
        
        return '\n\n'.join(js_parts) if js_parts else "// No JavaScript found in page source"
    
    def save_source(self):
        current_tab = self.tabs.currentIndex()
        tab_names = ["html", "css", "js"]
        tab_widgets = [self.html_widget, self.css_widget, self.js_widget]
        
        file_name, _ = QFileDialog.getSaveFileName(
            self, 
            f"Save {tab_names[current_tab].upper()} Source",
            f"source.{tab_names[current_tab]}",
            f"{tab_names[current_tab].upper()} files (*.{tab_names[current_tab]});;All files (*.*)"
        )
        
        if file_name:
            try:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(tab_widgets[current_tab].toPlainText())
                QMessageBox.information(self, "Success", f"Source saved to {file_name}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save file: {str(e)}")

# --- Custom WebEngineView with Context Menu --------------------------------------------------

class CustomWebEngineView(QWebEngineView):
    def __init__(self, browser, private_mode=False):
        super().__init__()
        self.browser = browser
        self.private_mode = private_mode
        # Legacy fallback for Qt versions without newWindowRequested signal
        self._legacy_create_window = False
        
        # Performance optimizations
        self._setup_performance_optimizations()
    
    def _setup_performance_optimizations(self):
        """Set up performance optimizations for this web view"""
        # Enable smooth scrolling and other performance features
        page = self.page()
        if page:
            settings = page.settings()
            if settings:
                # Performance optimizations
                settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)  # Disable smooth scrolling by default
                settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
                
        # Optimize rendering
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def contextMenuEvent(self, event):
        from PyQt6.QtWebEngineCore import QWebEnginePage

        menu = QMenu(self)
        page = self.page()
        data = None
        if page and hasattr(page, "contextMenuData"):
            try:
                data = page.contextMenuData()
            except Exception:
                data = None

        link_url = None
        image_url = None
        media_url = None
        media_type = None
        selected_text = ""
        suggested_name = ""
        is_editable = False

        if data:
            try:
                link = data.linkUrl()
                if link and link.isValid():
                    link_url = QUrl(link)
            except Exception:
                pass
            try:
                img = data.imageUrl()
                if img and img.isValid():
                    image_url = QUrl(img)
            except Exception:
                pass
            try:
                media = data.mediaUrl()
                if media and media.isValid():
                    media_url = QUrl(media)
            except Exception:
                pass
            try:
                media_type = data.mediaType()
            except Exception:
                media_type = None
            try:
                suggested_name = data.mediaFileName()
            except Exception:
                suggested_name = ""
            try:
                selected_text = data.selectedText()
            except Exception:
                selected_text = ""
            try:
                is_editable = data.isContentEditable()
            except Exception:
                is_editable = False

        # Link-related actions
        if link_url:
            open_link_action = menu.addAction("Open Link in New Tab")
            open_link_action.triggered.connect(lambda url=link_url: self.browser.add_new_tab(url, url.host() or "New Tab"))

            copy_link_action = menu.addAction("Copy Link Address")
            def _copy_link():
                try:
                    text_value = link_url.toString(QUrl.UrlFormattingOption.PrettyDecoded)
                except Exception:
                    text_value = link_url.toString()
                QApplication.clipboard().setText(text_value)
            copy_link_action.triggered.connect(_copy_link)
            menu.addSeparator()

        # Media download actions
        def media_filename(url_obj: QUrl, fallback: str) -> str:
            if suggested_name:
                return suggested_name
            if url_obj and url_obj.isValid():
                candidate = os.path.basename(url_obj.path())
                return candidate or fallback
            return fallback

        media_actions_added = False
        if image_url:
            download_image_action = menu.addAction("Download Image")
            download_image_action.triggered.connect(lambda url=image_url: self._trigger_download(url, media_filename(url, "image")))
            media_actions_added = True

        media_is_audio = False
        media_is_video = False
        if media_type is not None:
            media_type_str = str(media_type)
            media_value = getattr(media_type, "value", media_type)
            media_is_audio = ("audio" in media_type_str.lower()) or media_value == 2
            media_is_video = ("video" in media_type_str.lower()) or media_value == 3
        if media_url and (media_is_audio or media_is_video):
            label = "Download Audio" if media_is_audio and not media_is_video else "Download Video"
            download_media_action = menu.addAction(label)
            download_media_action.triggered.connect(lambda url=media_url: self._trigger_download(url, media_filename(url, "media")))
            media_actions_added = True
        
        if media_actions_added:
            menu.addSeparator()

        # Editing / clipboard actions
        if is_editable:
            cut_action = menu.addAction("Cut")
            cut_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.Cut))
            copy_action = menu.addAction("Copy")
            copy_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.Copy))
            paste_action = menu.addAction("Paste")
            paste_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.Paste))
            menu.addSeparator()
        elif selected_text:
            copy_selection_action = menu.addAction("Copy Selection")
            copy_selection_action.triggered.connect(lambda: page.triggerAction(QWebEnginePage.WebAction.Copy))
            menu.addSeparator()

        # Standard navigation actions
        back_action = menu.addAction("← Back")
        back_action.triggered.connect(self.back)
        back_action.setEnabled(self.history().canGoBack())

        forward_action = menu.addAction("→ Forward")
        forward_action.triggered.connect(self.forward)
        forward_action.setEnabled(self.history().canGoForward())

        reload_action = menu.addAction("⟳ Reload")
        reload_action.triggered.connect(self.reload)

        menu.addSeparator()

        # Page actions
        view_source_action = menu.addAction("View Page Source")
        view_source_action.triggered.connect(self.browser.view_source)

        print_action = menu.addAction("Print...")
        print_action.triggered.connect(self.browser.print_page)

        menu.addSeparator()

        # Bookmark action
        bookmark_action = menu.addAction("Add to Bookmarks")
        bookmark_action.triggered.connect(self.browser.toggle_bookmark)

        menu.exec(event.globalPos())

    def _trigger_download(self, url: QUrl, suggested_filename: str | None = None):
        if not url or not url.isValid():
            return
        page = self.page()
        if page is None:
            return
        profile = page.profile()
        filename = (suggested_filename or "").strip()
        try:
            if profile:
                if filename:
                    profile.download(url, filename)
                else:
                    profile.download(url)
            else:
                if filename:
                    page.download(url, filename)
                else:
                    page.download(url)
            if self.browser and hasattr(self.browser, "_notify_download_started"):
                self.browser._notify_download_started(url)
        except TypeError:
            try:
                profile.download(url)
            except Exception:
                pass
        except Exception as exc:
            print(f"Failed to start download for {url.toString()}: {exc}")

    def createWindow(self, web_window_type):
        if getattr(self, "_legacy_create_window", False):
            return self.browser._create_window_from_create_window(self, web_window_type)
        return super().createWindow(web_window_type)

# --- Claude AI Integration --------------------------------------------------------------------

class ClaudeAIWorker(QThread):
    response_received = pyqtSignal(str)

    def __init__(self, user_input, settings_manager, parent=None):
        super().__init__(parent)
        self.user_input = user_input
        self.settings_manager = settings_manager

    def run(self):
        # Get API key from settings
        api_key = self.settings_manager.get('ai_api_key', '')
        if not api_key or api_key == 'YOUR-CLAUDE-API':
            self.response_received.emit("Error: No API key configured. Please set your Claude API key in Settings > AI Assistant.")
            return

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                messages=[
                    {"role": "user", "content": self.user_input}
                ],
                max_tokens=4096,
                temperature=0.7
            )
            self.response_received.emit(response.content[0].text)
        except Exception as e:
            self.response_received.emit(f"Error: {e}")

# --- Claude AI Widget -------------------------------------------------------------------------

class ClaudeAIWidget(QWidget):
    def closeEvent(self, event):
            if hasattr(self, 'worker') and self.worker.isRunning():
                self.worker.quit()
                if not self.worker.wait(1000):  # Wait up to 1 second
                    self.worker.terminate()  # Force terminate if not quitting cleanly
                    self.worker.wait()  # Wait for termination
            event.accept()
        
    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager

        # Set up the layout
        self.layout = QVBoxLayout(self)

        # Output window (read-only)
        self.output_window = QTextEdit(self)
        self.output_window.setStyleSheet("background-color: #FDF6E3; color: #657B83;")
        
        # Set font size and type
        font = QFont("Monospace")
        font.setPointSize(11)
        self.output_window.setFont(font)
        
        self.output_window.setReadOnly(True)        
        self.layout.addWidget(self.output_window)

        # Controls row (language selector and actions)
        controls_layout = QHBoxLayout()

        # Add language selector for speech recognition
        self.language_selector = QComboBox(self)
        self.language_selector.addItems([
            "English (en-US)",
            "English (en-GB)",
            "Arabic (ar-SA)",
            "Chinese (zh-CN)",
            "Danish (da-DK)",
            "Dutch (nl-NL)",
            "Finnish (fi-FI)",
            "French (fr-FR)",
            "German (de-DE)",
            "Italian (it-IT)",
            "Japanese (ja-JP)",
            "Korean (ko-KR)",
            "Norwegian (nb-NO)",
            "Portuguese (pt-BR)",
            "Portuguese (pt-PT)",
            "Spanish (es-ES)",
            "Swedish (sv-SE)",
            "Ukrainian (uk-UA)"
        ])
        self.language_selector.setToolTip("Select Speech Recognition Language")
        self.language_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(self.language_selector)
        
        # Add a microphone button to trigger voice input
        self.microphone_button = QPushButton("Mic", self)
        self.microphone_button.setToolTip("Start/Stop Voice Input")
        self.microphone_button.clicked.connect(self.toggle_voice_input)
        self.is_listening = False  # Flag to track voice input state
        self.microphone_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(self.microphone_button)
        
        # Add a send button to send the input
        self.layout.addLayout(controls_layout)

        # Input field with inline send button for extra writing space
        input_row = QHBoxLayout()
        self.input_field = QLineEdit(self)
        input_row.addWidget(self.input_field)
        self.send_button = QPushButton("Send", self)
        self.send_button.setToolTip("Send the input to Claude")
        self.send_button.clicked.connect(self.send_request)
        input_row.addWidget(self.send_button)
        self.layout.addLayout(input_row)
        
        # Add a loading spinner while getting the response from Claude
        self.loading_spinner = QProgressBar(self)
        self.loading_spinner.setRange(0, 0)  # Indeterminate progress
        self.layout.addWidget(self.loading_spinner)
        self.loading_spinner.hide()  # Hide initially

        # Initialize worker
        self.worker = ClaudeAIWorker("", self.settings_manager, self)
        self.worker.response_received.connect(self.update_output)

        # Connect signals to show and hide the loading spinner
        self.worker.started.connect(self.loading_spinner.show)
        self.worker.finished.connect(self.loading_spinner.hide)

        # Send request on pressing Enter
        self.input_field.returnPressed.connect(self.send_request)
        
        # Set size of AI prompt widget
        self.setFixedWidth(int(0.25 * QApplication.primaryScreen().size().width()))
        
        # Try to import markdown library
        try:
            self.markdown_module = markdown
        except ImportError:
            self.markdown_module = None
            
    def toggle_voice_input(self):
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()
            
    def start_listening(self):
        self.is_listening = True
        self.microphone_button.setStyleSheet("background-color: red;")
        self.microphone_button.setText("Stop")
        self.input_field.setPlaceholderText("Listening...")
        
        # Create a timer to stop listening after silence
        self.silence_timer = QTimer(self)
        self.silence_timer.setInterval(10000)  # 10 seconds for longer inputs
        self.silence_timer.setSingleShot(True)
        self.silence_timer.timeout.connect(self.stop_listening)
        
        try:
            # Initialize PyAudio explicitly first
            self.audio = pyaudio.PyAudio()
            
            # Start listening for voice input
            self.recognizer = sr.Recognizer()
            self.microphone = sr.Microphone()
            
            # Set up listening in background
            self.stop_listening_callback = self.recognizer.listen_in_background(
                self.microphone, self.process_voice_input)
            
            # Start the silence timer
            self.silence_timer.start()
                
        except Exception as e:
            self.is_listening = False
            self.microphone_button.setStyleSheet("")
            self.microphone_button.setText("Mic")
            self.input_field.setPlaceholderText("")
            
    def stop_listening(self):
        self.is_listening = False
        self.microphone_button.setStyleSheet("")
        self.microphone_button.setText("Mic")
        self.input_field.setPlaceholderText("")
        
        # Stop the silence timer if it exists and is active
        if hasattr(self, 'silence_timer') and self.silence_timer.isActive():
            self.silence_timer.stop()
        
        # First, stop the background listening and wait for it to complete
        # This ensures the thread isn't still using the resources we're about to clean up
        if hasattr(self, 'stop_listening_callback'):
            try:
                # Wait for the callback to stop properly
                self.stop_listening_callback(wait_for_stop=True)
            except Exception:
                pass
            finally:
                # Remove the reference
                if hasattr(self, 'stop_listening_callback'):
                    del self.stop_listening_callback
        
        # Give a short delay to ensure threads have stopped
        QThread.msleep(100)
        
        # Clean up microphone (which will also clean up its stream)
        if hasattr(self, 'microphone'):
            try:
                # Check if the microphone has a stream attribute and it's not None
                if hasattr(self.microphone, 'stream') and self.microphone.stream is not None:
                    self.microphone.__exit__(None, None, None)
            except Exception as e:
                print(f"Error closing microphone: {e}")
            finally:
                # Always delete the microphone reference
                del self.microphone
            
    def process_voice_input(self, recognizer, audio):
        try:
            # Get the language from settings if available, otherwise from UI
            if self.settings_manager:
                language_code = self.settings_manager.get('voice_recognition_language', 'en-US')
            else:
                selected_language = self.language_selector.currentText()
                language_code = selected_language.split('(')[1].strip(')')
            
            user_input = recognizer.recognize_google(audio, language=language_code)
            if user_input:
                self.input_field.setText(user_input)
                # Only send if we detected actual text
                if len(user_input.strip()) > 0:
                    self.send_request()
                    # After sending, wait a bit before stopping
                    QTimer.singleShot(500, self.stop_listening)
                    return
            
            # Voice input was detected, reset the silence timer to continue listening
            if hasattr(self, 'silence_timer'):
                # Increase timeout to 10 seconds for longer speaking time
                self.silence_timer.setInterval(10000)  
                self.silence_timer.start()
                      
        except sr.UnknownValueError:
            # Reset the silence timer even when nothing is recognized
            # This gives more time when user is thinking
            if hasattr(self, 'silence_timer'):
                self.silence_timer.start()
        except sr.RequestError:
            # Handle network errors more gracefully
            self.input_field.setPlaceholderText("Network error, try again")
            QTimer.singleShot(2000, self.stop_listening)
        except Exception as e:
            # Generic error handler
            self.input_field.setPlaceholderText(f"Error: {str(e)[:20]}")
            QTimer.singleShot(2000, self.stop_listening)            
            if hasattr(self, 'silence_timer'):
                # Increase timeout to 10 seconds for longer speaking time
                self.silence_timer.setInterval(10000)  
                self.silence_timer.start()
            
    def send_request(self):
        user_input = str(self.input_field.text())
        if user_input.strip() == "/clear":
            self.output_window.clear()
        else:
            self.worker.user_input = user_input
            self.worker.start()
        self.input_field.clear()

    def format_markdown(self, text):
        """
        Convert markdown text to HTML using a markdown transpiler.
        Uses the markdown library if available, otherwise falls back to basic formatter.
        """
        # Heuristic: offload large markdown blocks to background worker pool
        if getattr(self, 'background_pool', None) and text and len(text) > 4000:
            self._offload_markdown(text)
            return "<i>Rendering large markdown in background...</i>"

        if self.markdown_module:
            try:
                html = self.markdown_module.markdown(text, extensions=['fenced_code'])
                return html
            except Exception:
                pass  # Fall back to basic formatter on error
        
        # Fallback to basic formatter
        return self.format_markdown_code_blocks(text)

    def format_markdown_code_blocks(self, text):
        # Detect code fences and wrap them in HTML for better readability
        pattern = r'```(.*?)\n(.*?)´´´'
        def replacer(match):
            lang = match.group(1).strip()
            code_text = match.group(2).replace('<', '&lt;').replace('>', '&gt;')
            if lang and lang.lower() == 'python':
                # Python code
                return f"<pre><code style='color: #0000AA;'>{code_text}</code></pre>"
            else:
                # No specified language
                return f"<pre><code>{code_text}</code></pre>"
        
        # Process code blocks
        processed_text = re.sub(pattern, replacer, text, flags=re.DOTALL)
        
        # Process headers (# Header)
        processed_text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', processed_text, flags=re.MULTILINE)
        processed_text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', processed_text, flags=re.MULTILINE)
        processed_text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', processed_text, flags=re.MULTILINE)
        
        # Process bullet lists
        processed_text = re.sub(r'^\*\s+(.+)$', r'<li>\1</li>', processed_text, flags=re.MULTILINE)
        processed_text = re.sub(r'^-\s+(.+)$', r'<li>\1</li>', processed_text, flags=re.MULTILINE)
        
        # Process numbered lists
        processed_text = re.sub(r'^\d+\.\s+(.+)$', r'<li>\1</li>', processed_text, flags=re.MULTILINE)
        
        # Process bold (**text**)
        processed_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', processed_text)
        
        # Process italic (*text*)
        processed_text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', processed_text)
        
        # Process links [text](url)
        processed_text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', processed_text)
        
        # Add paragraph breaks
        processed_text = re.sub(r'\n\n+', r'<br><br>', processed_text)
        
        return processed_text

    def update_output(self, response):
        user_input = self.worker.user_input
        formatted_response = self.format_markdown(response)
        self.output_window.append(
            f"<span style='color: red; font-weight: bold;'>Human:</span> {user_input}<br><br>"
            f"<span style='color: blue; font-weight: bold;'>Assistant:</span> {formatted_response}<br>"
        )
    def _offload_markdown(self, md_text: str):
        pool = getattr(self, 'background_pool', None)
        if not pool:
            return
        enable_md = bool(getattr(self, 'markdown_module', None))
        def _apply(html):
            try:
                self.output_window.append(html)
            except Exception:
                pass
        try:
            pool.submit(_markdown_convert_task, md_text, enable_md, callback=_apply)
        except Exception as e:
            self.output_window.append(f"<pre>Background render failed: {e}</pre>")

# --- AdBlocker Worker -------------------------------------------------------------------------

class AdBlockerWorker:
    def __init__(self, rules=None, pool: 'IOPool' | None = None, cache_path: str | None = None, cache_max_age: int = 86400):
        self.rules = rules  # Monolithic engine (legacy)
        # Incremental mode attributes
        self._all_rule_lines: list[str] | None = None
        self._domain_index: dict[str, list[int]] = {}
        self._compiled_cache: dict[tuple[str, ...], AdblockRules] = {}
        self._compiled_cache_order: list[tuple[str, ...]] = []
        self._compiled_cache_limit = 128  # cached subset variants
        self._lock = threading.RLock()
        self.incremental_enabled = False  # Use monolithic engine for simplicity
        self._building: set[tuple[str, ...]] = set()  # domains currently being built asynchronously
        self.pool = pool
        self.cache_path = cache_path
        self.cache_max_age = cache_max_age
        self.generic_engine: AdblockRules | None = None  # quick generic engine for early blocking
        self.blocked_domains: set[str] = set()  # Fast prefilter set of domains to block
        self.domain_block_set: set[str] = set()
        self._generic_subset_lines: list[str] = []
        self._full_rules_future = None
        self._full_rules_timer: threading.Timer | None = None

    async def download_adblock_lists(self):
        """Download EasyList + EasyPrivacy and prepare incremental-friendly structures."""
        lines: list[str] = []
        self.incremental_enabled = False
        self.rules = None
        self.generic_engine = None
        self._all_rule_lines = []
        self._domain_index.clear()
        self.blocked_domains.clear()
        self.domain_block_set.clear()
        # 1. Try cache
        if self.cache_path and os.path.exists(self.cache_path):
            try:
                mtime = os.path.getmtime(self.cache_path)
                if (time.time() - mtime) < self.cache_max_age:
                    with open(self.cache_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.read().splitlines()
                    print(f"Adblock: loaded cached lists ({len(lines)} lines)")
            except Exception as e:
                print(f"Adblock cache read failed: {e}")
        # 2. If no fresh cache, download in background (still inside this async)
        if not lines:
            urls = [
                "https://easylist.to/easylist/easylist.txt",
                "https://easylist.to/easylist/easyprivacy.txt",
                "https://easylist.to/easylist/fanboy-annoyance.txt"
            ]
            texts = []
            try:
                async with aiohttp.ClientSession() as session:
                    for url in urls:
                        try:
                            async with session.get(url, timeout=30) as resp:
                                texts.append(await resp.text())
                        except Exception as e:
                            print(f"Adblock download warning: {url} failed: {e}")
            except Exception as e:
                print(f"Adblock download failed: {e}")
                texts = []
            combined = "\n".join([t for t in texts if t])
            lines = combined.splitlines() if combined else []
            # Persist cache (best effort)
            if lines and self.cache_path:
                try:
                    with open(self.cache_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(lines))
                except Exception as e:
                    print(f"Adblock cache write failed: {e}")
        if not lines:
            return

        signature = self._compute_signature(lines)
        index_path = f"{self.cache_path}.index" if self.cache_path else None
        snapshot = None
        if index_path:
            snapshot = self._load_incremental_snapshot(index_path, signature)
            if snapshot:
                try:
                    self._apply_incremental_snapshot(
                        lines,
                        snapshot.get('domain_index', {}),
                        snapshot.get('blocked', []),
                        snapshot.get('generic_subset', []),
                        clone=False,
                    )
                    print(f"Adblock: restored incremental index ({len(self._domain_index)} domains) from cache")
                except Exception as e:
                    print(f"Adblock index restore failed: {e}")
                    snapshot = None

        if snapshot is None:
            snapshot = self._prepare_incremental_structures(lines)
            mode = "on" if self.incremental_enabled else "off"
            print(f"Adblock: prepared {len(lines)} source rules (incremental={mode})")
            if index_path:
                self._store_incremental_snapshot(index_path, signature, snapshot)

        if not self.incremental_enabled:
            self._ensure_full_rules_async(delay=0.0)

    def _prepare_incremental_structures(self, lines: list[str]):
        """Build domain index and generic subsets for incremental ad blocking."""
        domain_index: dict[str, list[int]] = {}
        blocked: set[str] = set()
        generic_subset: list[str] = []

        def _normalize_token(token: str) -> str:
            token = token.strip().lower()
            if not token:
                return ""
            # Strip common rule prefixes/suffixes without losing core domain portion
            token = token.strip('|')
            token = token.replace('*', '')
            token = token.split('^', 1)[0]
            token = token.split('/', 1)[0]
            token = token.split('?', 1)[0]
            token = token.strip('.')
            if token.startswith('.'):
                token = token[1:]
            if not token or '.' not in token:
                return ""
            if re.search(r"[^a-z0-9.-]", token):
                return ""
            return token

        def _record(token: str, idx: int, is_exception: bool):
            if not token:
                return
            parts = token.split('.')
            keys = {token}
            if len(parts) >= 2:
                keys.add('.'.join(parts[-2:]))
            for key in keys:
                bucket = domain_index.setdefault(key, [])
                if len(bucket) < 160:
                    bucket.append(idx)
            if not is_exception:
                blocked.add(token)
                if len(parts) >= 2:
                    blocked.add('.'.join(parts[-2:]))

        for idx, raw in enumerate(lines):
            line = raw.strip()
            if not line or line.startswith('!'):
                continue
            is_exception = line.startswith('@@')
            tokens = set()
            for match in _DOMAIN_TOKEN_PATTERN.finditer(line):
                tokens.add(match.group(1))
            if '||' not in line or not tokens:
                for match in _PLAIN_DOMAIN_PATTERN.finditer(line):
                    tokens.add(match.group(1))
            for token in tokens:
                _record(_normalize_token(token), idx, is_exception)
            if not is_exception and '##' not in line and '#@#' not in line and '||' not in line:
                if len(generic_subset) < 400:
                    generic_subset.append(line)

        snapshot = {
            'domain_index': {k: list(v) for k, v in domain_index.items()},
            'blocked': list(blocked),
            'generic_subset': list(generic_subset),
        }
        self._apply_incremental_snapshot(
            lines,
            domain_index,
            blocked,
            generic_subset,
            clone=False,
        )
        return snapshot

    def _apply_incremental_snapshot(self, lines, domain_index, blocked, generic_subset, clone: bool):
        if clone:
            domain_index_local = {str(k): list(v) for k, v in (domain_index or {}).items()}
        else:
            domain_index_local = domain_index or {}
        blocked_set = set(blocked or [])
        generic_list = list(generic_subset or [])

        self._all_rule_lines = list(lines)
        self._domain_index = domain_index_local
        self.blocked_domains = blocked_set
        self.domain_block_set = set(blocked_set)
        self._compiled_cache.clear()
        self._compiled_cache_order.clear()
        self._building.clear()
        self._generic_subset_lines = generic_list
        with self._lock:
            self.rules = None
        if self._full_rules_timer and self._full_rules_timer.is_alive():
            try:
                self._full_rules_timer.cancel()
            except Exception:
                pass
        self._full_rules_timer = None
        self._full_rules_future = None

        if generic_list:
            try:
                self.generic_engine = AdblockRules(generic_list, supported_options=[
                    'domain','third-party','image','script','stylesheet','xmlhttprequest','subdocument','document','media','font','object','ping','other'
                ])
            except Exception:
                self.generic_engine = None
        else:
            self.generic_engine = None

        self.incremental_enabled = bool(self._domain_index) and self.pool is not None

    def _compute_signature(self, lines: list[str]):
        if not lines:
            return (0, 0, 0)
        head = tuple(lines[:16])
        tail = tuple(lines[-16:]) if len(lines) >= 16 else tuple(lines)
        return (len(lines), hash(head), hash(tail))

    def _load_incremental_snapshot(self, index_path: str, signature):
        if not index_path or not os.path.exists(index_path):
            return None
        try:
            with open(index_path, 'rb') as handle:
                payload = pickle.load(handle)
            if payload.get('signature') != signature:
                return None
            return payload.get('snapshot')
        except Exception as e:
            print(f"Adblock index load failed: {e}")
            return None

    def _store_incremental_snapshot(self, index_path: str, signature, snapshot: dict):
        if not index_path or not snapshot:
            return
        directory = os.path.dirname(index_path)
        if directory:
            try:
                os.makedirs(directory, exist_ok=True)
            except Exception:
                pass
        try:
            payload = {'signature': signature, 'snapshot': snapshot}
            with open(index_path, 'wb') as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            print(f"Adblock index save failed: {e}")

    def _build_full_rules(self):
        lines = self._all_rule_lines or []
        if not lines:
            return None
        try:
            return AdblockRules(lines, supported_options=[
                'domain','third-party','image','script','stylesheet','xmlhttprequest','subdocument','document','media','font','object','ping','other'
            ])
        except Exception as e:
            print(f"Adblock full-rule build failed: {e}")
            return None

    def _set_full_rules(self, rules):
        if rules:
            with self._lock:
                self.rules = rules
            try:
                total = len(getattr(rules, 'rules', []))
                print(f"Adblock: full fallback rules ready ({total} entries)")
            except Exception:
                print("Adblock: full fallback rules ready")
        self._full_rules_future = None

    def _on_full_rules_future_done(self, future):
        try:
            rules = future.result()
        except Exception as e:
            print(f"Adblock fallback future error: {e}")
            rules = None
        self._set_full_rules(rules)

    def _ensure_full_rules_async(self, delay: float = 0.0):
        if self.rules or not self._all_rule_lines:
            return

        def _start():
            self._full_rules_timer = None
            if self.rules or not self._all_rule_lines:
                return
            if self._full_rules_future is not None:
                return
            if self.pool:
                future = self.pool.submit(self._build_full_rules)
                self._full_rules_future = future
                future.add_done_callback(self._on_full_rules_future_done)
            else:
                sentinel = object()
                self._full_rules_future = sentinel
                def runner():
                    rules = self._build_full_rules()
                    self._set_full_rules(rules)
                threading.Thread(target=runner, daemon=True).start()

        if delay <= 0:
            if self._full_rules_timer and self._full_rules_timer.is_alive():
                try:
                    self._full_rules_timer.cancel()
                except Exception:
                    pass
                self._full_rules_timer = None
            _start()
            return

        if self._full_rules_future is not None or self.rules:
            return
        if self._full_rules_timer and self._full_rules_timer.is_alive():
            return
        timer = threading.Timer(delay, _start)
        timer.daemon = True
        self._full_rules_timer = timer
        timer.start()

    def _tokenize_host(self, host: str | None) -> set[str]:
        if not host:
            return set()
        host_norm = host.lower().strip()
        if not host_norm:
            return set()
        if host_norm.startswith('www.'):
            host_norm = host_norm[4:]
        host_norm = host_norm.strip('.')
        if not host_norm:
            return set()
        parts = [p for p in host_norm.split('.') if p]
        tokens: set[str] = set()
        for i in range(len(parts)):
            suffix = '.'.join(parts[i:])
            if suffix.count('.') >= 1:
                tokens.add(suffix)
        return tokens

    def _domain_might_match(self, host: str | None) -> bool:
        if not host:
            return False
        tokens = self._tokenize_host(host)
        for token in tokens:
            if token in self.blocked_domains:
                return True
        return False

    def likely_blocks_host(self, host: str) -> bool:
        return self._domain_might_match(host)

    def should_block(self, url: str, options: dict | None) -> bool:
        opts = options or {}
        first_party = ""
        request_host = ""
        try:
            first_party = str(opts.get('domain', '') or "").lower()
        except Exception:
            first_party = ""
        try:
            request_host = (urlparse(url).hostname or "").lower()
        except Exception:
            request_host = ""

        blocked = False
        subset_engine = None
        fallback_needed = False

        if self.incremental_enabled:
            subset_engine = self.get_rules_for(first_party, request_host)
            if subset_engine:
                try:
                    blocked = bool(subset_engine.should_block(url, opts))
                except Exception as e:
                    print(f"Adblock subset error: {e}")
                    blocked = False
                fallback_needed = (subset_engine is None) or (subset_engine is self.generic_engine)
            else:
                fallback_needed = True
        else:
            fallback_needed = True

        if fallback_needed and not blocked:
            self._ensure_full_rules_async()
            if self.rules and self.rules is not subset_engine:
                try:
                    blocked = bool(self.rules.should_block(url, opts))
                except Exception as e:
                    print(f"Adblock should_block error: {e}")
                    blocked = False

        return blocked

    def _lru_touch(self, key):
        try:
            if key in self._compiled_cache_order:
                self._compiled_cache_order.remove(key)
            self._compiled_cache_order.append(key)
            while len(self._compiled_cache_order) > self._compiled_cache_limit:
                old = self._compiled_cache_order.pop(0)
                old_engine = self._compiled_cache.pop(old, None)
                # Let GC reclaim
        except Exception:
            pass

    def _select_subset_lines(self, tokens: set[str]):
        """Return rule lines relevant to the provided token set."""
        if not tokens:
            return []
        lines = self._all_rule_lines or []
        domain_index = self._domain_index
        line_indexes: set[int] = set()
        for token in tokens:
            bucket = domain_index.get(token)
            if not bucket:
                continue
            for idx in bucket:
                line_indexes.add(idx)
                if len(line_indexes) >= 1200:
                    break
            if len(line_indexes) >= 1200:
                break
        if not line_indexes:
            return []
        subset = [lines[i] for i in sorted(line_indexes)]
        if self._generic_subset_lines:
            subset.extend(self._generic_subset_lines[:200])
        return subset

    @staticmethod
    def _subset_builder_task(token_key: tuple[str, ...], lines: list[str], domain_index: dict[str, list[int]], generic_subset: list[str] | None):
        tokens = set(token_key)
        line_indexes: set[int] = set()
        for token in tokens:
            bucket = domain_index.get(token)
            if not bucket:
                continue
            for idx in bucket:
                line_indexes.add(idx)
                if len(line_indexes) >= 1200:
                    break
            if len(line_indexes) >= 1200:
                break
        if not line_indexes:
            subset = []
        else:
            subset = [lines[i] for i in sorted(line_indexes)]
        if generic_subset:
            subset.extend(generic_subset[:200])
        return token_key, subset

    def prefetch_domain(self, host: str):
        """Asynchronously build and cache rules for a domain using the background pool.
        Safe to call multiple times; only the first will enqueue work.
        """
        if not self.incremental_enabled or not self.pool or not host:
            return
        tokens = self._tokenize_host(host)
        if not tokens:
            return
        key = tuple(sorted(tokens))
        with self._lock:
            if key in self._compiled_cache or key in self._building:
                return
            self._building.add(key)
            lines = self._all_rule_lines or []
            domain_index = self._domain_index
        # Submit task (arguments must be picklable)
        generic_subset = self._generic_subset_lines
        future = self.pool.submit(self._subset_builder_task, key, lines, domain_index, generic_subset)
        future.add_done_callback(lambda f: self._on_subset_ready(f.result()))

    def _on_subset_ready(self, result):
        try:
            bundle = result if isinstance(result, tuple) else (None, [])
            if len(bundle) != 2:
                key = None
                selected = []
            else:
                key, selected = bundle
            if not key or not selected:
                with self._lock:
                    if key in self._building:
                        self._building.remove(key)
                return
            try:
                engine = AdblockRules(selected, supported_options=[
                    'domain','third-party','image','script','stylesheet','xmlhttprequest','subdocument','document','media','font','object','ping','other'
                ])
            except Exception as e:
                print(f"Adblock async subset build failed for {key}: {e}")
                with self._lock:
                    if key in self._building:
                        self._building.remove(key)
                return
            with self._lock:
                self._compiled_cache[key] = engine
                self._lru_touch(key)
                if key in self._building:
                    self._building.remove(key)
        except Exception as e:
            print(f"Adblock subset callback error: {e}")

    def get_rules_for(self, first_party_domain: str | None, request_host: str | None):
        """Return a compiled rules engine for the combination of first-party and request host."""
        if not self.incremental_enabled:
            if not self.rules:
                self._ensure_full_rules_async()
            return self.rules or self.generic_engine

        token_set = self._tokenize_host(first_party_domain)
        token_set.update(self._tokenize_host(request_host))
        if not token_set:
            return self.rules or self.generic_engine

        key = tuple(sorted(token_set))
        with self._lock:
            engine = self._compiled_cache.get(key)
            if engine:
                self._lru_touch(key)
                return engine

        selected = self._select_subset_lines(token_set)
        if not selected and self.generic_engine:
            return self.generic_engine
        if not selected:
            return self.rules
        try:
            engine = AdblockRules(selected, supported_options=[
                'domain','third-party','image','script','stylesheet','xmlhttprequest','subdocument','document','media','font','object','ping','other'
            ])
        except Exception as e:
            print(f"Adblock subset compile failed for {key}: {e}")
            return self.generic_engine or self.rules

        with self._lock:
            self._compiled_cache[key] = engine
            self._lru_touch(key)
        return engine

# --- Main Browser Window ----------------------------------------------------------------------

class Browser(QMainWindow):
    def __init__(self, io_pool: IOPool | None = None, fast_start: bool | None = None):
        super().__init__()
        self.setWindowTitle("surfscape")
        self.setMinimumSize(800, 640)
        self.background_pool = io_pool if io_pool is not None else IOPool()
        self._io_write_lock = threading.Lock()
        # Reuse the same pool for assorted IO and CPU-light background tasks
        self.io_pool = self.background_pool

        # Set application icon if available
        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'icon', 'icon.png')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
            else:
                pm = QPixmap(1, 1)
                pm.fill()
                self.setWindowIcon(QIcon(pm))
        except Exception:
            pm = QPixmap(1, 1)
            pm.fill()
            self.setWindowIcon(QIcon(pm))

        self.showMaximized()

        # Paths for the data files
        self.data_dir = os.path.expanduser("~/.surfscape") if os.name != 'nt' else os.path.join(os.getenv("USERPROFILE"), ".surfscape")
        os.makedirs(self.data_dir, exist_ok=True)
        self.bookmarks_file = os.path.join(self.data_dir, "bookmarks.json")
        self.history_file = os.path.join(self.data_dir, "history.json")
        self.cookies_file = os.path.join(self.data_dir, "cookies.json")
        self.session_file = os.path.join(self.data_dir, "session.json")

        # Initialize settings manager
        self.settings_manager = SettingsManager(self.data_dir)

        # Status bar setup
        self.status_bar = self.statusBar()
        self.status_info_label = QLabel("")
        self.status_hover_label = QLabel("")
        try:
            self.status_hover_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        except Exception:
            pass
        self.status_hover_label.setStyleSheet("margin-left: 12px;")
        self.status_hover_label.setMinimumWidth(240)
        self.status_progress = QProgressBar()
        self.status_progress.setMaximum(100)
        self.status_progress.setTextVisible(False)
        self.status_progress.setFixedWidth(120)
        self.status_progress.hide()
        self.status_bar.addWidget(self.status_info_label)
        self.status_bar.addPermanentWidget(self.status_hover_label, 1)
        self.status_bar.addPermanentWidget(self.status_progress)
        self.status_bar.setVisible(self.settings_manager.get('show_status_bar', True))
        self.status_bar.showMessage("Ready")
        self._status_default_url = ""

        # Theme/font legacy variables
        bg_color = self.settings_manager.get('background_color', 'system')
        font_color = self.settings_manager.get('font_color', '#000000')
        self.background_color = QColor(bg_color) if bg_color != 'system' else QColor()
        self.font_color = QColor(font_color) if font_color != 'system' else QColor()
        self.font = QFont()
        self.homepage_url = self.settings_manager.get('homepage', 'https://html.duckduckgo.com/html')

        # Deferred JSON loads (faster perceived startup)
        self.bookmarks = []
        self.history = []
        self.cookies = []
        QTimer.singleShot(50, lambda: self._deferred_load_json('bookmarks'))
        QTimer.singleShot(80, lambda: self._deferred_load_json('history'))
        QTimer.singleShot(110, lambda: self._deferred_load_json('cookies'))
        QTimer.singleShot(120, self.update_url_autocomplete)

        # Legacy flat settings
        self.settings = self.load_json(os.path.join(self.data_dir, 'settings.json'))

        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Enter URL or Search Query")

        # Ad blocker placeholder
        self.ad_blocker_rules = None

        # Favicon handling
        self._favicon_cache = {}
        self._favicon_pending = {}
        self._favicon_default = QIcon()
        try:
            default_pm = QPixmap(16, 16)
            default_pm.fill(QColor(200, 200, 200))
            self._favicon_default = QIcon(default_pm)
        except Exception:
            pass
        self._favicon_manager = QNetworkAccessManager(self)
        self.favicon_dir = os.path.join(self.data_dir, 'favicons')
        os.makedirs(self.favicon_dir, exist_ok=True)

        # Lazy heavy components
        self.download_manager = None
        self.find_dialog = None

        # Profiles & interceptors
        self.network_interceptor = NetworkRequestInterceptor(self, self.ad_blocker_rules, is_private=False)
        self.private_profile = QWebEngineProfile()
        self.private_network_interceptor = NetworkRequestInterceptor(self, self.ad_blocker_rules, is_private=True)
        self.private_profile.setUrlRequestInterceptor(self.private_network_interceptor)
        self.default_profile = QWebEngineProfile.defaultProfile()
        self.default_profile.setUrlRequestInterceptor(self.network_interceptor)
        self._optimize_web_engine_profile(self.default_profile)
        self._optimize_web_engine_profile(self.private_profile)

        # Fast start flag (now ON by default unless explicitly disabled)
        # Resolution order: explicit ctor arg > env var > default True
        if fast_start is not None:
            self.fast_start = bool(fast_start)
        else:
            env_val = os.environ.get("SURFSCAPE_FAST_START")
            if env_val is None:
                # No override provided: default enable
                self.fast_start = True
            else:
                env_val_l = env_val.lower()
                # Treat common false-y indicators as disable; everything else enables
                self.fast_start = env_val_l not in ("0", "false", "no", "off", "disable", "disabled")
        # Optional detailed page performance tracing (disabled by default)
        self.perf_trace = os.environ.get("SURFSCAPE_TRACE_PAGE", "").lower() in ("1","true","yes","on")

        # Kick off adblock init (deferred if fast start to unblock UI sooner)
        cache_path = os.path.join(self.data_dir, 'adblock_lists.cache')
        cache_exists = os.path.exists(cache_path)
        adblock_delay = 700 if self.fast_start and not cache_exists else 0
        QTimer.singleShot(adblock_delay, self._init_adblock_legacy)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBarDoubleClicked.connect(self.tab_open_doubleclick)
        self.tabs.currentChanged.connect(self.current_tab_changed)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(self.settings_manager.get('show_tab_close_buttons', True))
        tab_position = self.settings_manager.get('tab_position', 'top')
        self.tabs.setTabPosition(QTabWidget.TabPosition.South if tab_position == 'bottom' else QTabWidget.TabPosition.North)
        self.tabs.tabCloseRequested.connect(self.close_current_tab)
        self.tab_loading_pool = set()
        self.setCentralWidget(self.tabs)

        # Session restore / first tab (blank quick tab if fast start enabled)
        restore_delay = 160 if self.fast_start else 120
        homepage_delay = 90 if self.fast_start else 60
        if self.settings_manager.get('restore_session', True):
            QTimer.singleShot(restore_delay, self.restore_session)
        else:
            QTimer.singleShot(homepage_delay, lambda: self.add_new_tab(QUrl(self.homepage_url), "Homepage"))

        # Menus / shortcuts
        self.create_menu_bar()
        self.create_shortcuts()

        # Deferred cookie store sync (later if fast start)
        QTimer.singleShot(400 if self.fast_start else 250, self.load_cookies_to_web_engine)

        # Apply settings (deferred)
        self.load_settings()
        QTimer.singleShot(300 if self.fast_start else 100, self._apply_settings_to_browser)

        # DevTools loads lazily on first open

    def _deferred_load_json(self, which: str):
        file_map = {
            'bookmarks': (self.bookmarks_file, 500, 'bookmarks'),
            'history': (self.history_file, 1000, 'history'),
            'cookies': (self.cookies_file, 500, 'cookies'),
        }
        target = file_map.get(which)
        if not target:
            return
        path_value, limit, attr = target

        try:
            result = self.load_json(path_value)
        except Exception as exc:
            print(f'Failed to load {attr}: {exc}')
            return
        data = (result or [])[-limit:]
        setattr(self, attr, data)
        if attr == 'bookmarks' and hasattr(self, 'bookmarks_menu'):
            self._populate_bookmarks_menu()
        if attr == 'history' and hasattr(self, 'history_menu'):
            self.update_history_menu()
        if attr == 'cookies' and hasattr(self, 'update_cookies_menu'):
            try:
                self.update_cookies_menu()
            except Exception as exc:
                print(f"Failed to refresh cookies menu: {exc}")
        if attr in ('bookmarks', 'history'):
            self.update_url_autocomplete()

    def _ensure_download_manager(self):
        if self.download_manager is None:
            self.download_manager = DownloadManager(self)
            QWebEngineProfile.defaultProfile().downloadRequested.connect(self.handle_download_request)
        return self.download_manager

    def _ensure_find_dialog(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self, self)
        return self.find_dialog

    def load_json(self, file_path):
        """Load data from a JSON file, or return an empty list if the file doesn't exist."""
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as exc:
            print(f"Warning: failed to load JSON data from {file_path}: {exc}")
            return []

    def save_json(self, file_path, data):
        """Persist JSON data without blocking the UI thread."""
        try:
            payload = json.dumps(data, indent=4)
        except Exception as exc:
            print(f'Failed to serialize {file_path}: {exc}')
            return

        def _write(target_path, text):
            directory = os.path.dirname(target_path)
            if directory:
                try:
                    os.makedirs(directory, exist_ok=True)
                except Exception as exc:
                    print(f"Failed to ensure directory for {target_path}: {exc}")
                    return
            tmp_path = f"{target_path}.tmp"
            try:
                with self._io_write_lock:
                    with open(tmp_path, 'w', encoding='utf-8') as handle:
                        handle.write(text)
                        handle.flush()
                        try:
                            os.fsync(handle.fileno())
                        except Exception:
                            pass
                    os.replace(tmp_path, target_path)
            except Exception as exc:
                print(f"Failed to persist JSON to {target_path}: {exc}")
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

        pool = getattr(self, 'io_pool', None)
        if pool is not None:
            pool.submit(_write, file_path, payload)
        else:
            _write(file_path, payload)

    def _create_web_view(self, private_mode: bool = False) -> CustomWebEngineView:
        """Create a web view configured for normal or private browsing."""
        view = CustomWebEngineView(self, private_mode=private_mode)
        if private_mode:
            try:
                from PyQt6.QtWebEngineCore import QWebEnginePage
            except ImportError:
                QWebEnginePage = None
            if QWebEnginePage is not None:
                private_page = QWebEnginePage(self.private_profile, view)
                view.setPage(private_page)
        return view

    def _attach_web_view(self, browser: CustomWebEngineView, label: str, select: bool = True) -> int:
        """Add the provided view to the tab widget and wire standard signals."""
        if not isinstance(browser, CustomWebEngineView):
            return -1

        if self.settings_manager.get('open_new_tab_next_to_current', True) and self.tabs.count() > 0:
            insert_index = min(self.tabs.currentIndex() + 1, self.tabs.count())
        else:
            insert_index = self.tabs.count()

        if insert_index >= self.tabs.count():
            tab_index = self.tabs.addTab(browser, label)
        else:
            tab_index = self.tabs.insertTab(insert_index, browser, label)

        if select:
            self.tabs.setCurrentIndex(tab_index)

        browser.urlChanged.connect(lambda qurl, b=browser: self.update_urlbar(qurl, b))
        browser.urlChanged.connect(lambda qurl, i=tab_index: self._update_tab_favicon(i, qurl))
        browser.loadFinished.connect(lambda ok, i=tab_index, b=browser: self._on_tab_load_finished(i, b, ok))
        browser.loadStarted.connect(lambda b=browser: self._on_tab_load_started(b))
        browser.loadProgress.connect(lambda progress, b=browser: self._on_tab_load_progress(b, progress))
        page = browser.page()
        if page:
            page.iconUrlChanged.connect(lambda _url, i=tab_index, b=browser: self._update_tab_favicon(i, b.url()))
            try:
                page.linkHovered.connect(lambda url, b=browser: self._update_status_hover(url, b))
            except Exception:
                pass
            try:
                cookie_store = page.profile().cookieStore()
                cookie_store.cookieAdded.connect(self.add_cookie)
            except Exception:
                pass
            supports_new_window_signal = hasattr(page, "newWindowRequested")
            browser._legacy_create_window = not supports_new_window_signal
            if supports_new_window_signal:
                try:
                    page.newWindowRequested.connect(lambda request, b=browser: self._handle_new_window_request(b, request))
                except Exception:
                    browser._legacy_create_window = True
        self.apply_settings_to_new_tab(browser)
        if select:
            QTimer.singleShot(0, lambda b=browser: self._update_status_from_view(b))
        return tab_index

    def _handle_new_window_request(self, source_view: CustomWebEngineView, request):
        """Handle window/tab requests coming from web content."""
        try:
            requested_url = request.requestedUrl()
        except Exception:
            requested_url = QUrl()

        is_user_initiated = True
        try:
            is_user_initiated = bool(request.isUserInitiated())
        except Exception:
            pass

        if self.settings_manager.get('block_popups', True) and not is_user_initiated:
            try:
                request.reject()
            except Exception:
                pass
            self._show_status_message("Popup blocked", 3000)
            return

        private_mode = getattr(source_view, 'private_mode', False)
        label = requested_url.host() if requested_url and requested_url.isValid() else ""
        if not label and requested_url and requested_url.isValid():
            try:
                label = requested_url.toDisplayString(QUrl.UrlFormattingOption.RemoveScheme)
            except Exception:
                label = requested_url.toDisplayString()
        label = label or "New Tab"
        new_view = self._create_web_view(private_mode=private_mode)
        select_tab = True
        try:
            destination = request.destination()
            dest_name = getattr(destination, "name", str(destination))
            if dest_name and "Background" in dest_name:
                select_tab = False
        except Exception:
            pass
        tab_index = self._attach_web_view(new_view, label, select=select_tab)

        try:
            request.setNewPage(new_view.page())
            request.accept()
        except Exception:
            if requested_url and requested_url.isValid():
                new_view.setUrl(requested_url)
            try:
                request.accept()
            except Exception:
                pass

        if tab_index >= 0:
            self.tabs.setTabText(tab_index, label)
        if select_tab:
            self._show_status_message("Opened in new tab", 2000)

    def _create_window_from_create_window(self, source_view: CustomWebEngineView, web_window_type):
        """Legacy fallback when Qt does not expose newWindowRequested."""
        if self.settings_manager.get('block_popups', True):
            # Without request metadata we err on the side of caution.
            self._show_status_message("Popup blocked", 3000)
            return None
        private_mode = getattr(source_view, 'private_mode', False)
        new_view = self._create_web_view(private_mode=private_mode)
        self._attach_web_view(new_view, "New Tab", select=True)
        self._show_status_message("Opened in new tab", 2000)
        return new_view

    def _update_status_from_view(self, view: CustomWebEngineView | None):
        if not hasattr(self, 'status_bar'):
            return
        if view is None:
            self.status_info_label.setText("")
            self._status_default_url = ""
            self.status_hover_label.setText("")
            self.status_progress.hide()
            return
        try:
            qurl = view.url()
        except Exception:
            qurl = None
        if not qurl or not isinstance(qurl, QUrl) or qurl.isEmpty():
            self.status_info_label.setText("")
            self._status_default_url = ""
            self.status_hover_label.setText("")
            return
        try:
            display_url = qurl.toDisplayString(QUrl.UrlFormattingOption.RemovePassword)
        except Exception:
            display_url = qurl.toDisplayString()
        self._status_default_url = display_url
        self.status_hover_label.setText(display_url)
        scheme = qurl.scheme().lower()
        host = qurl.host() or display_url
        if scheme == "https":
            info = f"Secure | {host}"
        elif scheme == "http":
            info = f"Not secure | {host}"
        elif scheme:
            info = f"{scheme.upper()} | {host}"
        else:
            info = host
        self.status_info_label.setText(info)

    def _update_status_hover(self, text: str, view: CustomWebEngineView):
        if not hasattr(self, 'status_bar'):
            return
        if view is not self._current_web_view():
            return
        if text:
            self.status_hover_label.setText(text)
        else:
            self.status_hover_label.setText(self._status_default_url)

    def _set_status_progress(self, value: int | None, view: CustomWebEngineView):
        if not hasattr(self, 'status_progress'):
            return
        if view is not self._current_web_view():
            return
        if value is None or value >= 100:
            self.status_progress.hide()
            return
        self.status_progress.show()
        try:
            self.status_progress.setValue(int(max(0, min(100, value))))
        except Exception:
            pass

    def _show_status_message(self, text: str, timeout: int = 0):
        if not hasattr(self, 'status_bar'):
            return
        try:
            self.status_bar.showMessage(text, timeout)
        except Exception:
            pass

    def _notify_download_started(self, url: QUrl):
        if not hasattr(self, 'status_bar'):
            return
        try:
            description = url.fileName() or url.host() or url.toDisplayString()
        except Exception:
            description = ""
        description = description or "download"
        self._show_status_message(f"Download started: {description}", 3000)

    def add_new_tab(self, qurl=None, label="Homepage"):
        if qurl is None:
            qurl = QUrl(self.homepage_url)
        elif not isinstance(qurl, QUrl):
            qurl = QUrl(str(qurl))

        browser = self._create_web_view(private_mode=False)
        self._attach_web_view(browser, label, select=True)
        browser.setUrl(qurl)
        return browser

    def add_private_tab(self, qurl=None, label="Private Tab"):
        # Check if private browsing should be default
        if self.settings_manager.get('incognito_by_default', False):
            # All tabs are private by default, so just add normal tab
            self.add_new_tab(qurl, label)
            return
        
        if qurl is None:
            qurl = QUrl(self.homepage_url)
        elif not isinstance(qurl, QUrl):
            qurl = QUrl(str(qurl))

        browser = self._create_web_view(private_mode=True)
        self._attach_web_view(browser, f"🔒 {label}", select=True)
        browser.setUrl(qurl)
        return browser

    def _current_web_view(self):
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, CustomWebEngineView) else None

    def _ensure_active_web_view(self, default_url: QUrl | None = None, label: str = "Homepage"):
        view = self._current_web_view()
        if view is None:
            created = self.add_new_tab(default_url or QUrl(self.homepage_url), label)
            view = created if isinstance(created, CustomWebEngineView) else self._current_web_view()
        return view

    def _open_url(self, url, label: str = "Tab"):
        if not url:
            return
        target = url if isinstance(url, QUrl) else QUrl(str(url))
        view = self._ensure_active_web_view(target, label)
        if view is not None:
            view.setUrl(target)

    def navigate_back(self):
        view = self._current_web_view()
        if view is not None and hasattr(view, 'back'):
            view.back()

    def navigate_forward(self):
        view = self._current_web_view()
        if view is not None and hasattr(view, 'forward'):
            view.forward()

    def tab_open_doubleclick(self, i):
        if i == -1:
            self.add_new_tab()

    def current_tab_changed(self, i):
        if i < 0:
            return
        widget = self._current_web_view()
        if widget is None:
            return
        qurl = widget.url()
        self.update_urlbar(qurl, widget)
        self.update_title(widget)
        self._update_status_from_view(widget)
        if widget in self.tab_loading_pool:
            self._set_status_progress(0, widget)
        else:
            self._set_status_progress(None, widget)

    def close_current_tab(self, i):
        if self.tabs.count() < 2:
            # Check if we should close the browser when closing the last tab
            reply = QMessageBox.question(
                self, "Close Browser",
                "This is the last tab. Do you want to close the browser?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.close()
            return

        closing_view = self.tabs.widget(i)
        if isinstance(closing_view, CustomWebEngineView):
            self.tab_loading_pool.discard(closing_view)
        self.tabs.removeTab(i)
        current_view = self._current_web_view()
        self._update_status_from_view(current_view)
        if current_view and current_view in self.tab_loading_pool:
            self._set_status_progress(0, current_view)
        else:
            self._set_status_progress(None, current_view)

    def update_title(self, browser):
        widget = self._current_web_view()
        if widget is None or browser is not widget:
            return
        page = widget.page() if hasattr(widget, 'page') else None
        if page is not None:
            title = page.title()
            self.setWindowTitle(f"surfscape - {title}")

    def navigate_home(self):
        self._open_url(self.homepage_url, "Homepage")

    def update_urlbar(self, q, browser=None):
        current = self._current_web_view()
        if browser is not None and browser is not current:
            return
        if current is None and browser is None:
            return

        # Set full URL including the scheme
        self.url_bar.setText(q.toString(QUrl.ComponentFormattingOption.FullyEncoded))
        self.url_bar.setCursorPosition(0)
        if current is not None:
            self._update_status_from_view(current)

    def navigate_to_url(self):
        url = self.url_bar.text()
        if not url.startswith("http://") and not url.startswith("https://"):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                # Use configured search engine
                search_engine = self.settings_manager.get('default_search_engine', 'duckduckgo')
                search_urls = {
                    'duckduckgo': 'https://html.duckduckgo.com/html?q={}',
                    'google': 'https://www.google.com/search?q={}',
                    'bing': 'https://www.bing.com/search?q={}',
                    'yahoo': 'https://search.yahoo.com/search?p={}',
                    'startpage': 'https://www.startpage.com/sp/search?query={}',
                    'searx': 'https://searx.org/?q={}'
                }
                search_url = search_urls.get(search_engine, search_urls['duckduckgo'])
                url = search_url.format(url)
        self._open_url(url, "Navigation")

    # -------------------- Favicon utilities --------------------
    def _favicon_key_for_url(self, url: str) -> str:
        try:
            q = QUrl(url)
            host = q.host() or url
            return host.lower()
        except Exception:
            return str(url).lower()

    def _favicon_path_for_key(self, key: str) -> str:
        safe = re.sub(r"[^a-z0-9_.-]", "_", key)
        return os.path.join(self.favicon_dir, f"{safe}.png")

    def _favicon_from_disk(self, key: str) -> QIcon | None:
        path = self._favicon_path_for_key(key)
        if os.path.exists(path):
            try:
                pm = QPixmap(path)
                if pm.isNull():
                    return None
                # Recreate QImage to ensure it's sane, then repack as PNG if needed
                img = pm.toImage()
                if img.isNull():
                    return None
                # If the file might be problematic, re-encode once
                try:
                    writer = QImageWriter(path, b"png")
                    writer.setQuality(100)
                    writer.write(img)
                except Exception:
                    pass
                return QIcon(QPixmap.fromImage(img))
            except Exception:
                return None
        return None

    def _get_favicon_cached(self, url: str) -> QIcon | None:
        """Return favicon from memory or disk cache only; do not trigger network fetch."""
        key = self._favicon_key_for_url(url)
        if key in self._favicon_cache:
            return self._favicon_cache[key]
        icon = self._favicon_from_disk(key)
        if icon:
            self._favicon_cache[key] = icon
            return icon
        return None

    def _fetch_favicon(self, url: str, key: str, callbacks: list):
        """Fetch favicon.ico for host; on load, save to disk, update callbacks.
        callbacks: list of callables taking (QIcon)
        """
        # If already pending, queue callbacks
        if key in self._favicon_pending:
            self._favicon_pending[key].extend(callbacks)
            return
        self._favicon_pending[key] = list(callbacks)

        # Build common favicon locations
        q = QUrl(url)
        if not q.scheme():
            q.setScheme('https')
        base = QUrl()
        base.setScheme(q.scheme())
        base.setHost(q.host())
        candidates = [
            QUrl(base.toString() + "/favicon.ico"),
            QUrl(base.toString() + "/favicon.png"),
        ]

        def try_next(i=0):
            if i >= len(candidates):
                # Give up; use default
                icon = self._favicon_default
                self._favicon_cache[key] = icon
                for cb in self._favicon_pending.pop(key, []):
                    try:
                        cb(icon)
                    except Exception:
                        pass
                return

            req = QNetworkRequest(candidates[i])
            # Prefer HTTP/1.1 for small icon fetches to avoid some HTTP/2 edge cases
            try:
                attr = getattr(QNetworkRequest.Attribute, 'HTTP2AllowedAttribute', None)
                if attr is None:
                    attr = getattr(QNetworkRequest.Attribute, 'Http2AllowedAttribute', None)
                if attr is not None:
                    req.setAttribute(attr, False)
            except Exception:
                pass
            reply = self._favicon_manager.get(req)

            def on_finished():
                ok = False
                try:
                    if reply.error() == reply.NetworkError.NoError:
                        # Reject non-image responses and very large payloads
                        try:
                            ctype = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
                        except Exception:
                            ctype = ""
                        # Skip SVGs and non-images; QImage won't handle SVG without extra module
                        if ctype and ("svg" in ctype.lower()):
                            return
                        if ctype and not ("image/" in ctype or "x-icon" in ctype or "vnd.microsoft.icon" in ctype):
                            # Not an image; let finally advance to next
                            return
                        try:
                            clen = int(reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader) or 0)
                        except Exception:
                            clen = 0
                        if clen and clen > 1024 * 1024:
                            # Too large; let finally advance to next
                            return
                        data = reply.readAll()
                        # Hard limit if no Content-Length header
                        if len(data) > 1024 * 1024:
                            # Too large; let finally advance to next
                            return
                        # Decode using QImage to sanitize metadata
                        img = QImage()
                        img.loadFromData(bytes(data))
                        if img.isNull():
                            # Invalid image; let finally advance to next
                            return
                        # Normalize size to 16x16 for consistent UI and to avoid very large icons
                        if img.width() > 0 and img.height() > 0:
                            img = img.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        # Save to disk as clean PNG (re-encoded) to avoid libpng warnings
                        path = self._favicon_path_for_key(key)
                        try:
                            writer = QImageWriter(path, b"png")
                            writer.setQuality(100)
                            writer.write(img)
                        except Exception:
                            pass
                        icon = QIcon(QPixmap.fromImage(img))
                        self._favicon_cache[key] = icon
                        for cb in self._favicon_pending.pop(key, []):
                            try:
                                cb(icon)
                            except Exception:
                                pass
                        ok = True
                        return
                finally:
                    reply.deleteLater()
                    # If not successful, move to next candidate
                    if not ok and key in self._favicon_pending:
                        try_next(i + 1)

            reply.finished.connect(on_finished)

        try_next(0)

    def _get_favicon_async(self, url: str, apply_icon):
        """Get favicon for url; apply_icon is a callback that accepts QIcon."""
        key = self._favicon_key_for_url(url)
        # Memory cache
        if key in self._favicon_cache:
            apply_icon(self._favicon_cache[key])
            return
        # Disk cache
        icon = self._favicon_from_disk(key)
        if icon:
            self._favicon_cache[key] = icon
            apply_icon(icon)
            return
        # Fetch
        self._fetch_favicon(url, key, [apply_icon])

    # -------------------- End favicon utilities --------------------

    def _update_tab_favicon(self, tab_index: int, url) -> None:
        """Set the tab icon for the given index using the page's favicon.
        Falls back to a default icon while fetching.
        """
        try:
            url_str = url.toString() if isinstance(url, QUrl) else str(url)
        except Exception:
            url_str = str(url)

        # Show a placeholder immediately
        try:
            self.tabs.setTabIcon(tab_index, self._favicon_default)
        except Exception:
            pass

        # Try cache first, else fetch async
        icon = self._get_favicon_cached(url_str)
        if icon:
            try:
                self.tabs.setTabIcon(tab_index, icon)
            except Exception:
                pass
            return

        def apply_icon(ic: QIcon):
            try:
                self.tabs.setTabIcon(tab_index, ic)
            except Exception:
                pass

        self._get_favicon_async(url_str, apply_icon)

    def create_menu_bar(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("File")
        new_tab_action = QAction("New Tab", self)
        new_tab_action.triggered.connect(lambda _: self.add_new_tab())
        file_menu.addAction(new_tab_action)
        
        new_private_tab_action = QAction("New Private Tab", self)
        new_private_tab_action.triggered.connect(lambda: self.add_private_tab())
        file_menu.addAction(new_private_tab_action)
        
        file_menu.addSeparator()
        
        print_action = QAction("Print", self)
        print_action.triggered.connect(self.print_page)
        file_menu.addAction(print_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menu_bar.addMenu("Edit")
        
        cut_action = QAction("Cut", self)
        cut_action.triggered.connect(self.cut_text)
        edit_menu.addAction(cut_action)
        
        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(self.copy_text)
        edit_menu.addAction(copy_action)
        
        paste_action = QAction("Paste", self)
        paste_action.triggered.connect(self.paste_text)
        edit_menu.addAction(paste_action)
        
        # Separator
        edit_menu.addSeparator()
        
        select_all_action = QAction("Select All", self)
        select_all_action.triggered.connect(self.select_all_text)
        edit_menu.addAction(select_all_action)
        
        # Separator
        edit_menu.addSeparator()
        
        find_action = QAction("Find in Page", self)
        find_action.triggered.connect(self.show_find_dialog)
        edit_menu.addAction(find_action)

        # View menu
        view_menu = menu_bar.addMenu("View")
        
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.triggered.connect(self.zoom_in)
        view_menu.addAction(zoom_in_action)
        
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.triggered.connect(self.zoom_out)
        zoom_out_action.setShortcut(QKeySequence("Ctrl+_"))
        view_menu.addAction(zoom_out_action)
        
        zoom_reset_action = QAction("Reset Zoom", self)
        zoom_reset_action.triggered.connect(self.zoom_reset)
        view_menu.addAction(zoom_reset_action)
        
        view_menu.addSeparator()
        
        fullscreen_action = QAction("Full Screen", self)
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)
        
        view_menu.addSeparator()
        
        view_source_action = QAction("View Page Source", self)
        view_source_action.triggered.connect(self.view_source)
        view_menu.addAction(view_source_action)
        
        # History menu (before Bookmarks)
        self.history_menu = menu_bar.addMenu("History")
        self.history_menu.aboutToShow.connect(self.update_history_menu)

        # Bookmarks menu
        self.bookmarks_menu = menu_bar.addMenu("Bookmarks")
            
        # Static actions for import/export
        self.action_import_bookmarks = QAction("Import Bookmarks...", self)
        self.action_import_bookmarks.triggered.connect(self.import_bookmarks)
        self.bookmarks_menu.addAction(self.action_import_bookmarks)
        self.action_export_bookmarks = QAction("Export Bookmarks...", self)
        self.action_export_bookmarks.triggered.connect(self.export_bookmarks)
        self.bookmarks_menu.addAction(self.action_export_bookmarks)
        self.bookmarks_menu.addSeparator()
        self.bookmarks_menu.aboutToShow.connect(self._populate_bookmarks_menu)

        # Cookies menu
        self.cookies_menu = menu_bar.addMenu("Cookies")
        self.cookies_menu.aboutToShow.connect(self.update_cookies_menu)

        # Downloads menu
        downloads_menu = menu_bar.addMenu("Downloads")
        downloads_action = QAction("Show Downloads", self)
        downloads_action.triggered.connect(self.show_download_manager)
        downloads_menu.addAction(downloads_action)

        # Settings menu
        settings_menu = menu_bar.addMenu("Settings")
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings_dialog)
        settings_menu.addAction(settings_action)

        # Help menu
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        # Navigation bar
        navtb = QToolBar("Navigation")
        navtb.setMovable(False)  # Disable detachable toolbar
        self.addToolBar(navtb)

        self.back_button = QAction("←", self)
        self.back_button.triggered.connect(self.navigate_back)
        navtb.addAction(self.back_button)

        self.forward_button = QAction("→", self)
        self.forward_button.triggered.connect(self.navigate_forward)
        navtb.addAction(self.forward_button)

        self.reload_button = QAction("⟳", self)
        self.reload_button.triggered.connect(self.refresh_current_tab)
        navtb.addAction(self.reload_button)

        self.home_button = QAction("Home", self)
        self.home_button.triggered.connect(self.navigate_home)
        navtb.addAction(self.home_button)

        self.url_bar.returnPressed.connect(self.navigate_to_url)
        navtb.addWidget(self.url_bar)

        self.bookmark_button = QAction("☆", self)
        self.bookmark_button.triggered.connect(self.toggle_bookmark)
        navtb.addAction(self.bookmark_button)
        
        self.ai_button = QAction("Ai", self)
        self.ai_button.triggered.connect(self.show_ai_widget)
        navtb.addAction(self.ai_button)
        
        self.settings_button = QAction("⚙", self)
        self.settings_button.triggered.connect(self.show_settings_dialog)
        navtb.addAction(self.settings_button)

    def create_shortcuts(self):
        # Apply default shortcuts (can be overridden by settings)
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(lambda: self.add_new_tab())
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(lambda: self.close_current_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.refresh_current_tab)
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_current_tab)
        QShortcut(QKeySequence("Alt+Home"), self).activated.connect(self.navigate_home)
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(self.navigate_back)
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(self.navigate_forward)
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.show_find_dialog)
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(self.zoom_reset)
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(self.view_source)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self.print_page)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self).activated.connect(lambda: self.add_private_tab())
        
        # Add AI assistant shortcut
        ai_shortcut = self.settings_manager.get('shortcuts.ai_assistant', 'Ctrl+Shift+A')
        if ai_shortcut:
            QShortcut(QKeySequence(ai_shortcut), self).activated.connect(self.show_ai_widget)
        
        # Apply all custom shortcuts from settings
        self._apply_custom_shortcuts()
    
    def _apply_custom_shortcuts(self):
        """Apply custom keyboard shortcuts from settings"""
        shortcuts = self.settings_manager.get('shortcuts', {})
        
        # Map of action names to methods
        action_map = {
            'new_tab': lambda: self.add_new_tab(),
            'close_tab': lambda: self.close_current_tab(self.tabs.currentIndex()),
            'reload': self.refresh_current_tab,
            'hard_reload': self.refresh_current_tab,
            'find': self.show_find_dialog,
            'zoom_in': self.zoom_in,
            'zoom_out': self.zoom_out,
            'zoom_reset': self.zoom_reset,
            'home': self.navigate_home,
            'back': self.navigate_back,
            'forward': self.navigate_forward,
            'bookmark': self.toggle_bookmark,
            'bookmarks': lambda: None,  # Placeholder for bookmarks manager
            'history': lambda: None,  # Placeholder for history manager
            'downloads': self.show_download_manager,
            'settings': self.show_settings_dialog,
            'view_source': self.view_source,
            'fullscreen': self.toggle_fullscreen,
            'private_tab': lambda: self.add_private_tab()
        }
        
        # Apply shortcuts (skip ones already handled by default shortcuts)
        skip_defaults = {'new_tab', 'close_tab', 'reload', 'find', 'zoom_in', 'zoom_reset', 
                        'home', 'back', 'forward', 'bookmark', 
                        'view_source', 'fullscreen', 'private_tab'}
        
        for action, method in action_map.items():
            if action in skip_defaults:
                continue
            shortcut_key = shortcuts.get(action)
            if shortcut_key and method:
                try:
                    QShortcut(QKeySequence(shortcut_key), self).activated.connect(method)
                except Exception as e:
                    print(f"Failed to set shortcut {shortcut_key} for {action}: {e}")

    def toggle_bookmark(self):
        url = self.url_bar.text()
        if url in [bookmark[1] for bookmark in self.bookmarks]:
            # Remove existing bookmark
            self.bookmarks = [bookmark for bookmark in self.bookmarks if bookmark[1] != url]
            self.bookmark_button.setIconText("☆")  # Set to unpressed state
        else:
            # Add new bookmark
            current_widget = self._current_web_view()
            title = url
            if current_widget is not None and current_widget.page() is not None:
                try:
                    title = current_widget.page().title() or title
                except Exception:
                    title = url
            self.bookmarks.append([title, url])
            self.bookmark_button.setIconText("★")  # Change to pressed state
        self.save_json(self.bookmarks_file, self.bookmarks)  # Save bookmarks

        # Reset the bookmark button state when the URL changes
        self.url_bar.textChanged.connect(self.reset_bookmark_button)
        # Refresh menu UI
        self._populate_bookmarks_menu()

    def reset_bookmark_button(self):
        url = self.url_bar.text()
        if url not in [bookmark[1] for bookmark in self.bookmarks]:
            self.bookmark_button.setIconText("☆")  # Set to unpressed state
            
    def show_ai_widget(self):
        # Check if AI is enabled in settings
        if not self.settings_manager.get('ai_enabled', True):
            QMessageBox.information(self, "AI Assistant", "AI Assistant is disabled in settings.")
            return
        
        # Check if we already have a splitter and AI widget
        if not hasattr(self, 'splitter'):
            # Get AI panel configuration from settings
            panel_position = self.settings_manager.get('ai_panel_position', 'right')
            panel_width = self.settings_manager.get('ai_panel_width', 0.3)
            
            # Create a splitter based on position
            if panel_position == 'bottom':
                self.splitter = QSplitter(Qt.Orientation.Vertical)
            else:
                self.splitter = QSplitter(Qt.Orientation.Horizontal)
            
            # Move the tabs to the splitter
            self.tabs.setParent(self.splitter)
            
            # Create the AI widget
            self.ai_widget = ClaudeAIWidget(self.settings_manager)
            self.ai_widget.background_pool = self.background_pool
            
            # Add widgets based on position
            if panel_position == 'left':
                self.splitter.addWidget(self.ai_widget)
                self.splitter.addWidget(self.tabs)
                self.splitter.setSizes([int(self.width() * panel_width), int(self.width() * (1 - panel_width))])
            elif panel_position == 'bottom':
                self.splitter.addWidget(self.tabs)
                self.splitter.addWidget(self.ai_widget)
                self.splitter.setSizes([int(self.height() * (1 - panel_width)), int(self.height() * panel_width)])
            else:  # right (default)
                self.splitter.addWidget(self.tabs)
                self.splitter.addWidget(self.ai_widget)
                self.splitter.setSizes([int(self.width() * (1 - panel_width)), int(self.width() * panel_width)])
            
            # Make the splitter the central widget
            self.setCentralWidget(self.splitter)
        else:
            # Toggle visibility of the AI panel
            if self.ai_widget.isVisible():
                self.ai_widget.hide()
            else:
                self.ai_widget.show()
                # Restore proportions from settings
                panel_width = self.settings_manager.get('ai_panel_width', 0.3)
                panel_position = self.settings_manager.get('ai_panel_position', 'right')
                
                if panel_position == 'bottom':
                    self.splitter.setSizes([int(self.height() * (1 - panel_width)), int(self.height() * panel_width)])
                elif panel_position == 'left':
                    self.splitter.setSizes([int(self.width() * panel_width), int(self.width() * (1 - panel_width))])
                else:  # right
                    self.splitter.setSizes([int(self.width() * (1 - panel_width)), int(self.width() * panel_width)])

    def select_all_text(self):
        widget = self.focusWidget()
        view = self._current_web_view()
        page = view.page() if view is not None and hasattr(view, 'page') else None
        if isinstance(widget, QLineEdit):
            widget.selectAll()
        elif page is not None:
            page.runJavaScript("document.execCommand('selectAll');")

    def cut_text(self):
        widget = self.focusWidget()
        view = self._current_web_view()
        page = view.page() if view is not None and hasattr(view, 'page') else None
        if isinstance(widget, QLineEdit):
            widget.cut()
        elif page is not None:
            page.runJavaScript("document.execCommand('cut');")

    def copy_text(self):
        widget = self.focusWidget()
        view = self._current_web_view()
        page = view.page() if view is not None and hasattr(view, 'page') else None
        if isinstance(widget, QLineEdit):
            widget.copy()
        elif page is not None:
            page.runJavaScript("document.execCommand('copy');")

    def paste_text(self):
        widget = self.focusWidget()
        view = self._current_web_view()
        page = view.page() if view is not None and hasattr(view, 'page') else None
        if isinstance(widget, QLineEdit):
            widget.paste()
        elif page is not None:
            page.runJavaScript("document.execCommand('paste');")
            
    def add_to_history(self, qurl, title):
        """ Add a page to the history """
        url = self.url_bar.text()
        if url != "about:blank":
            self.history.append((title, url))
            self.history = self.history[-1000:]  # Keep only the last 1000 entries
            self.update_history_menu()
            self.save_json(self.history_file, self.history)  # Save history

    def update_history_menu(self):
        """Update the History menu with a scrollable list of entries."""
        self.history_menu.clear()
        try:
            from PyQt6.QtWidgets import QListWidget, QWidgetAction, QListWidgetItem, QLineEdit
            from PyQt6.QtCore import Qt
            # Search field (above the list) that filters in place
            search_line = QLineEdit()
            search_line.setPlaceholderText("Search history…")
            try:
                search_line.setClearButtonEnabled(True)
            except Exception:
                pass
            search_action = QWidgetAction(self.history_menu)
            search_action.setDefaultWidget(search_line)
            self.history_menu.addAction(search_action)

            # Create list widget
            history_list = QListWidget()
            history_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            history_list.setMinimumWidth(420)
            history_list.setMaximumHeight(300)
            # Enable hover selection
            try:
                history_list.setMouseTracking(True)
                def _history_item_entered(item):
                    if item is not None:
                        history_list.setCurrentItem(item)
                history_list.itemEntered.connect(_history_item_entered)
            except Exception:
                pass

            def populate_history(filter_text: str = ""):
                history_list.clear()
                ft = (filter_text or "").lower()
                for title, url in reversed(self.history[-200:]):
                    display = f"{title} — {url}" if title else url
                    if not ft or ft in (title or "").lower() or ft in (url or "").lower():
                        item = QListWidgetItem(display)
                        item.setData(Qt.ItemDataRole.UserRole, url)
                        # Set favicon asynchronously
                        def _apply(icon, item_ref=item):
                            try:
                                if item_ref is not None:
                                    item_ref.setIcon(icon)
                            except Exception:
                                pass
                        self._get_favicon_async(url, _apply)
                        history_list.addItem(item)

            def on_item_clicked(item):
                url = item.data(Qt.ItemDataRole.UserRole)
                if url:
                    self._open_url(url, 'History')
                    self.history_menu.hide()

            history_list.itemClicked.connect(on_item_clicked)

            # Wire search to filter the list
            def on_search_text_changed(text: str):
                populate_history(text)
            search_line.textChanged.connect(on_search_text_changed)
            def on_search_return():
                if history_list.count() > 0:
                    item = history_list.item(0)
                    if item:
                        on_item_clicked(item)
            search_line.returnPressed.connect(on_search_return)

            # Initial population
            populate_history("")

            list_action = QWidgetAction(self.history_menu)
            list_action.setDefaultWidget(history_list)
            self.history_menu.addAction(list_action)
        except Exception:
                # Fallback to basic actions
                for title, url in reversed(self.history[-50:]):
                    history_action = QAction(title or url, self)
                    history_action.triggered.connect(lambda _, url=url: self._open_url(url, 'History'))
                    self.history_menu.addAction(history_action)
        # Keep URL bar autocomplete fresh
        self.update_url_autocomplete()

    def _populate_bookmarks_menu(self):
        """Populate the Bookmarks menu with a scrollable list of bookmarks."""
        # Clear and rebuild menu content
        self.bookmarks_menu.clear()
        # Static actions
        if hasattr(self, 'action_import_bookmarks'):
            self.bookmarks_menu.addAction(self.action_import_bookmarks)
        if hasattr(self, 'action_export_bookmarks'):
            self.bookmarks_menu.addAction(self.action_export_bookmarks)
        # Inline bookmarks search (below Export Bookmarks). Filter in-menu list, no popup.
        try:
            from PyQt6.QtWidgets import QLineEdit, QWidgetAction
            search_line = QLineEdit()
            search_line.setPlaceholderText("Search bookmarks…")
            try:
                search_line.setClearButtonEnabled(True)
            except Exception:
                pass
            search_action = QWidgetAction(self.bookmarks_menu)
            search_action.setDefaultWidget(search_line)
            self.bookmarks_menu.addAction(search_action)
        except Exception:
            search_line = None

        self.bookmarks_menu.addSeparator()

        # Build a scrollable bookmarks list inside the menu
        try:
            # Create list widget
            bookmarks_list = QListWidget()
            bookmarks_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            bookmarks_list.setMinimumWidth(420)
            bookmarks_list.setMaximumHeight(300)
            # Enable hover selection
            try:
                bookmarks_list.setMouseTracking(True)
                def _bookmark_item_entered(item):
                    if item is not None:
                        bookmarks_list.setCurrentItem(item)
                bookmarks_list.itemEntered.connect(_bookmark_item_entered)
            except Exception:
                pass

            def populate_bookmarks(filter_text: str = ""):
                bookmarks_list.clear()
                ft = (filter_text or "").lower()
                for title, url in self.bookmarks:
                    display = f"{title} — {url}" if title else url
                    if not ft or ft in (title or "").lower() or ft in (url or "").lower():
                        item = QListWidgetItem(display)
                        item.setData(Qt.ItemDataRole.UserRole, url)
                        # Set favicon asynchronously
                        def _apply(icon, item_ref=item):
                            try:
                                if item_ref is not None:
                                    item_ref.setIcon(icon)
                            except Exception:
                                pass
                        self._get_favicon_async(url, _apply)
                        bookmarks_list.addItem(item)

            def on_item_clicked(item):
                url = item.data(Qt.ItemDataRole.UserRole)
                if url:
                    self._open_url(url, 'Bookmark')
                    # Close the menu after selection
                    self.bookmarks_menu.hide()

            bookmarks_list.itemClicked.connect(on_item_clicked)

            # Wire search to filter the in-menu list
            if search_line is not None:
                def on_search_text_changed(text: str):
                    populate_bookmarks(text)
                search_line.textChanged.connect(on_search_text_changed)
                def on_search_return():
                    # Navigate to the first visible item if any
                    if bookmarks_list.count() > 0:
                        item = bookmarks_list.item(0)
                        if item:
                            on_item_clicked(item)
                search_line.returnPressed.connect(on_search_return)

            # Initial population
            populate_bookmarks("")

            list_action = QWidgetAction(self.bookmarks_menu)
            list_action.setDefaultWidget(bookmarks_list)
            self.bookmarks_menu.addAction(list_action)
        except Exception as e:
                # Fallback to simple actions if anything goes wrong
                for title, url in self.bookmarks:
                    bookmark_action = QAction(title or url, self)
                    bookmark_action.triggered.connect(lambda _, url=url: self._open_url(url, 'Bookmark'))
                    self.bookmarks_menu.addAction(bookmark_action)
        # Keep URL bar autocomplete fresh
        self.update_url_autocomplete()

    def export_bookmarks(self):
        """Export bookmarks to JSON or HTML (Netscape format)."""
        try:
            default_path = os.path.join(self.data_dir, "bookmarks.json")
            file_path, selected_filter = QFileDialog.getSaveFileName(
                self,
                "Export Bookmarks",
                default_path,
                "JSON Files (*.json);;HTML Bookmarks (*.html)"
            )
            if not file_path:
                return

            if file_path.lower().endswith('.html') or (selected_filter and 'HTML' in selected_filter):
                html = self._export_bookmarks_as_html()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)
            else:
                # Default to JSON
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.bookmarks, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Export Bookmarks", f"Exported {len(self.bookmarks)} bookmarks.")
        except Exception as e:
            QMessageBox.warning(self, "Export Bookmarks", f"Failed to export bookmarks: {e}")

    def import_bookmarks(self):
        """Import bookmarks from JSON or HTML (Netscape format)."""
        try:
            file_path, selected_filter = QFileDialog.getOpenFileName(
                self,
                "Import Bookmarks",
                "",
                "JSON Files (*.json);;HTML Bookmarks (*.html)"
            )
            if not file_path:
                return

            imported = []
            if file_path.lower().endswith('.html') or (selected_filter and 'HTML' in selected_filter):
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    html_text = f.read()
                imported = self._parse_netscape_bookmarks(html_text)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Expect list of [title, url]
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            imported.append([str(item[0]), str(item[1])])

            if not imported:
                QMessageBox.information(self, "Import Bookmarks", "No bookmarks found to import.")
                return

            existing_urls = {u for _, u in self.bookmarks}
            added = 0
            for title, url in imported:
                if url and url not in existing_urls:
                    self.bookmarks.append([title or url, url])
                    existing_urls.add(url)
                    added += 1

            if added:
                self.save_json(self.bookmarks_file, self.bookmarks)
                self._populate_bookmarks_menu()
            QMessageBox.information(self, "Import Bookmarks", f"Imported {added} new bookmark(s).")
        except Exception as e:
            QMessageBox.warning(self, "Import Bookmarks", f"Failed to import bookmarks: {e}")

    def _export_bookmarks_as_html(self) -> str:
        """Create a simple Netscape-style bookmarks HTML string."""
        from datetime import datetime
        lines = [
            "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
            "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">",
            f"<!-- This file was generated by Surfscape on {datetime.now().isoformat()} -->",
            "<TITLE>Bookmarks</TITLE>",
            "<H1>Bookmarks</H1>",
            "<DL><p>"
        ]
        for title, url in self.bookmarks:
            safe_title = (title or url).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_url = (url or '').replace('"', '&quot;')
            lines.append(f"    <DT><A HREF=\"{safe_url}\">{safe_title}</A>")
        lines.append("</DL><p>")
        return "\n".join(lines)

    def _parse_netscape_bookmarks(self, html_text: str):
        """Parse a minimal Netscape-style bookmarks HTML and return list of [title, url]."""
        import re
        results = []
        # Capture href and inner text of anchor tags
        for href, text in re.findall(r'<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>', html_text, flags=re.IGNORECASE|re.DOTALL):
            # Strip any nested HTML tags from title
            clean_text = re.sub(r'<[^>]+>', '', text).strip()
            results.append([clean_text or href, href.strip()])
        return results

    def update_cookies_menu(self):
        """Update the Cookies menu with a scrollable list of cookies."""
        self.cookies_menu.clear()
        try:
            from PyQt6.QtWidgets import QListWidget, QWidgetAction, QListWidgetItem
            # Build scrollable list
            cookies_list = QListWidget()
            cookies_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
            cookies_list.setMinimumWidth(420)
            cookies_list.setMaximumHeight(300)
            # Enable hover selection
            try:
                cookies_list.setMouseTracking(True)
                def _cookies_item_entered(item):
                    if item is not None:
                        cookies_list.setCurrentItem(item)
                cookies_list.itemEntered.connect(_cookies_item_entered)
            except Exception:
                pass

            for cookie in self.cookies:
                name = cookie.get('name', '')
                domain = cookie.get('domain', '')
                item_text = f"{name} — {domain}" if name or domain else "(cookie)"
                item = QListWidgetItem(item_text)
                cookies_list.addItem(item)

            list_action = QWidgetAction(self.cookies_menu)
            list_action.setDefaultWidget(cookies_list)
            self.cookies_menu.addAction(list_action)
        except Exception:
            # Fallback to simple actions
            for cookie in self.cookies:
                name = cookie.get('name', '')
                domain = cookie.get('domain', '')
                cookie_action = QAction(f"{name} - {domain}", self)
                self.cookies_menu.addAction(cookie_action)

    def update_url_autocomplete(self):
        """Build and apply URL bar autocomplete with icons from history and bookmarks."""
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QCompleter
        except Exception:
            return

        # Build label + maintain mapping to URL for icon loading
        items: list[tuple[str, str]] = []  # (display_text, url)
        added_urls: set[str] = set()

        def add_entry(title: str, url: str, source: str):
            if not url or url in added_urls:
                return
            base = f"{title} — {url}" if title else url
            items.append((f"{base} ({source})", url))
            added_urls.add(url)

        # Bookmarks then history
        for title, url in self.bookmarks:
            add_entry(title, url, "Bookmarks")
        for title, url in reversed(self.history[-500:]):
            add_entry(title, url, "History")

        # Create or update item model with icons
        if not hasattr(self, '_url_item_model'):
            self._url_item_model = QStandardItemModel(self)
        else:
            self._url_item_model.clear()

        # Limit entries to avoid spawning too many network operations at once
        for text, url in items[:600]:
            it = QStandardItem(text)
            it.setEditable(False)
            # Load favicon asynchronously
            def _apply(icon, item_ref=it):
                try:
                    if item_ref is not None:
                        item_ref.setIcon(icon)
                except Exception:
                    pass
            self._get_favicon_async(url, _apply)
            self._url_item_model.appendRow(it)

        if not hasattr(self, '_url_completer'):
            extract = self._extract_url_from_completion_text
            class UrlOnlyCompleter(QCompleter):
                def pathFromIndex(self_inner, index):
                    try:
                        text = index.data()
                    except Exception:
                        return super().pathFromIndex(index)
                    return extract(str(text))

            self._url_completer = UrlOnlyCompleter(self._url_item_model, self)
            self._url_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            try:
                self._url_completer.setFilterMode(Qt.MatchFlag.MatchContains)
            except Exception:
                pass
            self._url_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self._url_completer.activated[str].connect(self._on_url_completion_activated)
            self.url_bar.setCompleter(self._url_completer)
        else:
            self._url_completer.setModel(self._url_item_model)

    def _on_url_completion_activated(self, text: str):
        """When a completion is chosen, extract URL and navigate."""
        url = self._extract_url_from_completion_text(text)
        self.url_bar.setText(url)
        self.navigate_to_url()

    def _extract_url_from_completion_text(self, text: str) -> str:
        """Extract the pure URL from an autocomplete display string."""
        url = text or ""
        # Prefer splitting on the em dash we use for display
        if ' — ' in url:
            parts = url.rsplit(' — ', 1)
            if len(parts) == 2:
                url = parts[1]
        elif ' - ' in url:
            parts = url.rsplit(' - ', 1)
            if len(parts) == 2:
                url = parts[1]
        # Strip label suffixes like " (Bookmarks)" or " (History)"
        for suffix in (" (Bookmarks)", " (History)"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
                break
        return url.strip()

    def add_cookie(self, cookie):
        """ Add a cookie to the list and save it """
        cookie_dict = {
            'name': cookie.name().data().decode('utf-8'),
            'value': cookie.value().data().decode('utf-8'),
            'domain': cookie.domain(),
            'path': cookie.path(),
            'expiry': cookie.expirationDate().toString(Qt.DateFormat.ISODate)
        }

        # Check if the cookie already exists
        for existing_cookie in self.cookies:
            if (existing_cookie['name'] == cookie_dict['name'] and
                    existing_cookie['domain'] == cookie_dict['domain'] and
                    existing_cookie['path'] == cookie_dict['path']):
                # Update the existing cookie value and expiry
                existing_cookie['value'] = cookie_dict['value']
                existing_cookie['expiry'] = cookie_dict['expiry']
                break
        else:
            # If the cookie does not exist, add it to the list
            self.cookies.append(cookie_dict)
            self.cookies = self.cookies[-500:]  # Keep last 500

        self.save_json(self.cookies_file, self.cookies)
        self.update_cookies_menu()
        
    def load_cookies_to_web_engine(self):
        """ Load cookies into the web engine """
        view = self._current_web_view()
        if view is None:
            return
            
        try:
            page = view.page() if hasattr(view, 'page') else None
            if page is None:
                return
            profile = page.profile()
            cookie_store = profile.cookieStore()
            for cookie in self.cookies:
                qcookie = QNetworkCookie(
                    cookie['name'].encode('utf-8'),
                    cookie['value'].encode('utf-8')
                )
                qcookie.setDomain(cookie['domain'])
                qcookie.setPath(cookie['path'])
                qcookie.setExpirationDate(QDateTime.fromString(cookie['expiry'], Qt.DateFormat.ISODate))
                cookie_store.setCookie(qcookie)
        except Exception as e:
            # Silently handle any errors during cookie loading
            pass

    def show_settings_dialog(self):
        dialog = AdvancedSettingsDialog(self.settings_manager, self)
        dialog.adjustSize()
        dialog.show()
        dialog.exec()
        
    def set_homepage(self, homepage_url):
        self.homepage_url = homepage_url
        self.settings_manager.set('homepage', homepage_url)
        self.settings_manager.save_settings()

    def add_bookmark(self, title, url, bookmarks_list):
        if title and url:
            self.bookmarks.append([title, url])
            self.bookmarks = self.bookmarks[-500:]  # Keep last 500
            self.save_json(self.bookmarks_file, self.bookmarks)
            bookmarks_list.addItem(f"{title} - {url}")
            self._populate_bookmarks_menu()

    def remove_selected_bookmark(self, bookmarks_list):
        selected_items = bookmarks_list.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            item_text = item.text()
            title, url = item_text.split(" - ", 1)
            self.bookmarks = [bookmark for bookmark in self.bookmarks if bookmark[1] != url]
            bookmarks_list.takeItem(bookmarks_list.row(item))
        self.save_json(self.bookmarks_file, self.bookmarks)
        self._populate_bookmarks_menu()

    def update_history_on_uncheck(self, item, history_list):
        if item.checkState() == Qt.CheckState.Unchecked:
            item_text = item.text()
            title, url = item_text.split(" - ", 1)
            self.history = [entry for entry in self.history if entry[1] != url]
            history_list.takeItem(history_list.row(item))
            self.save_json(self.history_file, self.history)
            self.update_history_menu()

    def clear_all_history(self):
        self.history = []
        self.save_json(self.history_file, self.history)
        self.update_history_menu()
        
    def remove_all_cookies(self):
        self.cookies = []
        self.save_json(self.cookies_file, self.cookies)
        
        # Clear cookies from web engine
        view = self._current_web_view()
        if view is not None:
            try:
                page = view.page() if hasattr(view, 'page') else None
                if page is None:
                    return
                profile = page.profile()
                cookie_store = profile.cookieStore()
                cookie_store.deleteAllCookies()
            except Exception:
                pass
        
        # Update UI displays
        self.update_cookies_menu()
        
    def choose_background_color(self):
        current_color = QColor(self.settings_manager.get('background_color', '#ffffff'))
        color = QColorDialog.getColor(current_color)
        if color.isValid():
            self.background_color = color
            self.settings_manager.set('background_color', color.name())
            self.settings_manager.save_settings()
            self.apply_styles()
            
    def choose_font(self):
        current_font = QApplication.instance().font()
        font, ok = QFontDialog.getFont(current_font)
        if ok:
            QApplication.instance().setFont(font)
            self.settings_manager.set('font_family', font.toString())
            self.settings_manager.set('font_size', font.pointSize())
            self.settings_manager.save_settings()
        
    def choose_font_color(self):
        current_color = QColor(self.settings_manager.get('font_color', '#000000'))
        color = QColorDialog.getColor(current_color)
        if color.isValid():
            self.font_color = color
            self.settings_manager.set('font_color', color.name())
            self.settings_manager.save_settings()
            self.apply_styles()
            
    def apply_styles(self):
        style = ""
        bg_color = self.settings_manager.get('background_color', 'system')
        font_color = self.settings_manager.get('font_color', '#000000')
        
        # Only apply custom colors if not using system theme
        if bg_color != 'system':
            if hasattr(self, 'background_color') and self.background_color.isValid():
                style += f"background-color: {self.background_color.name()};"
            elif bg_color.startswith('#'):
                style += f"background-color: {bg_color};"
        
        if font_color != 'system':
            if hasattr(self, 'font_color') and self.font_color.isValid():
                style += f" color: {self.font_color.name()};"
            elif font_color.startswith('#'):
                style += f" color: {font_color};"
        
        self.setStyleSheet(style)
        
    def reset_background_color(self):
        self.background_color = QColor(Qt.GlobalColor.white)
        self.settings_manager.set('background_color', 'system')
        self.settings_manager.save_settings()

    def reset_font_color(self):
        self.font_color = QColor(Qt.GlobalColor.black)
        self.settings_manager.set('font_color', '#000000')
        self.settings_manager.save_settings()

    def reset_font(self):
        QApplication.instance().setFont(QFont())
        self.settings_manager.set('font_family', 'system')
        self.settings_manager.set('font_size', 12)
        self.settings_manager.save_settings()
        
    def enable_tor_proxy(self):
        # Set up Tor proxy
        proxy = QNetworkProxy()
        proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
        proxy.setHostName(self.settings_manager.get('proxy_host', '127.0.0.1'))
        proxy.setPort(9050)  # Standard Tor port
        QNetworkProxy.setApplicationProxy(proxy)
        
        # Update settings
        self.settings_manager.set('proxy_type', 'tor')
        self.settings_manager.save_settings()
        
    def disable_tor_proxy(self):
        # Disable the proxy
        QNetworkProxy.setApplicationProxy(QNetworkProxy())
        
        # Update settings
        self.settings_manager.set('proxy_type', 'none')
        self.settings_manager.save_settings()
        
    def enable_i2p_proxy(self):
        # Set up I2P proxy
        proxy = QNetworkProxy()
        proxy.setType(QNetworkProxy.ProxyType.HttpProxy)
        proxy.setHostName(self.settings_manager.get('proxy_host', '127.0.0.1'))
        proxy.setPort(4444)  # Standard I2P port
        QNetworkProxy.setApplicationProxy(proxy)
        
        # Update settings
        self.settings_manager.set('proxy_type', 'i2p')
        self.settings_manager.save_settings()
        
    def disable_i2p_proxy(self):
        # Disable the proxy
        QNetworkProxy.setApplicationProxy(QNetworkProxy())
        
        # Update settings
        self.settings_manager.set('proxy_type', 'none')
        self.settings_manager.save_settings()
            
    def save_settings(self):
        # Update settings manager with current values
        self.settings_manager.set('homepage', self.homepage_url)
        self.settings_manager.set('background_color', self.background_color.name())
        self.settings_manager.set('font_color', self.font_color.name())
        self.settings_manager.set('font_family', QApplication.instance().font().toString())
        self.settings_manager.save_settings()
        
        # Legacy format for backward compatibility
        settings = {
            'homepage': self.homepage_url,
            'background_color': self.background_color.name(),
            'font_color': self.font_color.name(),
            'font': QApplication.instance().font().toString()
        }
        try:
            with open(os.path.join(self.data_dir, 'settings.json'), 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Failed to save legacy settings: {e}")
            
    def load_settings(self):
        # Try new settings format first
        self.homepage_url = self.settings_manager.get('homepage', 'https://html.duckduckgo.com/html')
        bg_color = self.settings_manager.get('background_color', 'system')
        font_color = self.settings_manager.get('font_color', '#000000')
        
        if bg_color != 'system':
            self.background_color = QColor(bg_color)
        else:
            self.background_color = QColor()  # Invalid color for system theme
        
        if font_color != 'system':
            self.font_color = QColor(font_color)
        else:
            self.font_color = QColor()  # Invalid color for system theme
        
        # Apply styles and font
        self.apply_styles()
        font_family = self.settings_manager.get('font_family', 'system')
        if font_family != 'system':
            font = QFont()
            font.fromString(font_family)
            QApplication.instance().setFont(font)
    
    def _apply_settings_to_browser(self):
        """Apply settings from settings manager to browser components"""
        # Update homepage
        self.homepage_url = self.settings_manager.get('homepage')
        
        # Update colors and theme
        bg_color = self.settings_manager.get('background_color', 'system')
        font_color = self.settings_manager.get('font_color', '#000000')
        
        if bg_color != 'system':
            self.background_color = QColor(bg_color)
        else:
            self.background_color = QColor()  # Invalid color for system theme
        
        if font_color != 'system':
            self.font_color = QColor(font_color)
        else:
            self.font_color = QColor()  # Invalid color for system theme
        self.apply_styles()
        
        # Update font
        font_size = self.settings_manager.get('font_size', 12)
        font_family = self.settings_manager.get('font_family', 'system')
        if font_family != 'system':
            font = QFont(font_family, font_size)
            QApplication.instance().setFont(font)
        
        # Update UI scale
        ui_scale = self.settings_manager.get('ui_scale', 1.0)
        if ui_scale != 1.0:
            # Apply UI scaling (requires restart for full effect)
            pass
        
        # Update proxy settings
        self._apply_proxy_settings()
        
        # Update toolbar visibility
        show_toolbar = self.settings_manager.get('show_toolbar', True)
        for toolbar in self.findChildren(QToolBar):
            toolbar.setVisible(show_toolbar)
        if hasattr(self, 'status_bar'):
            self.status_bar.setVisible(self.settings_manager.get('show_status_bar', True))
        
        # Apply web engine settings to all tabs
        self._apply_web_engine_settings()
        
        # Refresh all tabs to apply changes
        self._refresh_all_tabs()
    
    def _refresh_all_tabs(self):
        """Refresh all tabs to apply new settings"""
        current_index = self.tabs.currentIndex()
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, CustomWebEngineView):
                # Only reload if tab has content
                if tab.url().toString() and tab.url().toString() != 'about:blank':
                    tab.reload()
    
    def _optimize_web_engine_profile(self, profile):
        """Apply performance optimizations to a web engine profile"""
        # Cache optimizations
        cache_path = os.path.expanduser("~/.cache/surfscape")
        os.makedirs(cache_path, exist_ok=True)
        profile.setCachePath(cache_path)
        profile.setHttpCacheMaximumSize(100 * 1024 * 1024)  # 100MB cache
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        
        # Performance settings
        settings = profile.settings()
        if settings:
            # Enable hardware acceleration and optimizations
            accel = True
            settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, accel)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, accel)
            settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
            
            # Optimize loading
            settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, True)
            # Enable HTTP/2 for faster multiplexing
            try:
                settings.setAttribute(QWebEngineSettings.WebAttribute.Http2Enabled, True)
            except AttributeError:
                pass  # Not available in older Qt
            
            # Memory optimizations
            settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, False)
            
        # Custom user agent for better compatibility
        profile.setHttpUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Surfscape/1.0")
    
    def _on_tab_load_started(self, browser):
        """Handle tab loading start with performance optimizations"""
        self.tab_loading_pool.add(browser)
        # Performance: Disable expensive operations during loading
        # Adblock: prefetch domain-specific rule subset early using CPU pool
        try:
            if self.ad_blocker_rules and getattr(self.ad_blocker_rules, 'prefetch_domain', None):
                qurl = browser.url() if hasattr(browser, 'url') else None
                host = qurl.host() if qurl else ''
                if host:
                    self.ad_blocker_rules.prefetch_domain(host)
        except Exception:
            pass
        if browser is self._current_web_view():
            self._set_status_progress(0, browser)
            try:
                qurl = browser.url()
                host = qurl.host() or qurl.toDisplayString()
            except Exception:
                host = ""
            text = f"Loading {host}..." if host else "Loading..."
            self._show_status_message(text, 0)

    def _on_tab_load_progress(self, browser, progress: int):
        """Track page load progress for the active view."""
        if browser not in self.tab_loading_pool:
            self.tab_loading_pool.add(browser)
        if browser is not self._current_web_view():
            return
        self._set_status_progress(progress, browser)
        try:
            qurl = browser.url()
            host = qurl.host() or qurl.toDisplayString()
        except Exception:
            host = ""
        if progress >= 100:
            self._show_status_message("Loaded", 1500)
            self._set_status_progress(None, browser)
        else:
            suffix = f" ({progress}%)" if progress else ""
            text = f"Loading {host}{suffix}" if host else f"Loading{suffix}"
            self._show_status_message(text, 0)

    def _on_tab_load_finished(self, tab_index, browser, success=True):
        """Handle tab loading completion with performance optimizations"""
        # Remove from loading pool
        self.tab_loading_pool.discard(browser)
        
        # Update tab title and favicon efficiently
        self.update_title(browser)
        page = browser.page() if hasattr(browser, 'page') else None
        title = page.title() if page else ""
        if getattr(browser, 'private_mode', False):
            title = f"🔒 {title}" if title else "🔒"
        self.tabs.setTabText(tab_index, title or "New Tab")
        # Update favicon post-load
        try:
            self._update_tab_favicon(tab_index, browser.url())
        except Exception:
            pass
        
        # Add to history (deferred for performance)
        current_url = browser.url()
        page_title = page.title() if page else ""
        QTimer.singleShot(50, lambda url=current_url, title=page_title: self.add_to_history(url, title))
        
        # Re-enable dev tools updates if no tabs are loading
        # Lightweight performance markers (optional) - collect and print key paint metrics
        if getattr(self, 'perf_trace', False):
                try:
                        if browser and hasattr(browser, 'page'):
                                page = browser.page()
                                js = """
                                        (function(){
                                            if(!window.performance){return null;}
                                            let nav = (performance.getEntriesByType && performance.getEntriesByType('navigation')) ? performance.getEntriesByType('navigation')[0] : null;
                                            let paint = (performance.getEntriesByType && performance.getEntriesByType('paint')) ? performance.getEntriesByType('paint') : [];
                                            let fp = null; let fcp = null;
                                            for (const p of paint){ if(p.name==='first-paint') fp = p.startTime; if(p.name==='first-contentful-paint') fcp = p.startTime; }
                                            const t = performance.timing || {};
                                            function clamp(v){return (typeof v==='number' && v>=0 && v<1e8)? v : null;}
                                            let metrics = {};
                                            if(nav){
                                                metrics = {
                                                    dns: clamp(nav.domainLookupEnd - nav.domainLookupStart),
                                                    connect: clamp(nav.connectEnd - nav.connectStart),
                                                    ttfb: clamp(nav.responseStart - nav.startTime),
                                                    response: clamp(nav.responseEnd - nav.responseStart),
                                                    domContentLoaded: clamp(nav.domContentLoadedEventEnd - nav.startTime),
                                                    firstPaint: clamp(fp),
                                                    firstContentfulPaint: clamp(fcp),
                                                    load: clamp(nav.loadEventEnd - nav.startTime)
                                                };
                                            } else if(t.navigationStart){
                                                const ns = t.navigationStart;
                                                metrics = {
                                                    dns: clamp(t.domainLookupEnd - t.domainLookupStart),
                                                    connect: clamp(t.connectEnd - t.connectStart),
                                                    ttfb: clamp(t.responseStart - ns),
                                                    response: clamp(t.responseEnd - t.responseStart),
                                                    domContentLoaded: clamp(t.domContentLoadedEventEnd - ns),
                                                    firstPaint: clamp(fp),
                                                    firstContentfulPaint: clamp(fcp),
                                                    load: clamp(t.loadEventEnd - ns)
                                                };
                                            }
                                            // Gather top slow resources (exclude data: and chrome-extension:)
                                            let slow = [];
                                            if (performance.getEntriesByType){
                                                const resources = performance.getEntriesByType('resource') || [];
                                                for (const r of resources){
                                                    if((r.initiatorType==='img'||r.initiatorType==='script'||r.initiatorType==='css'||r.initiatorType==='fetch'||r.initiatorType==='xmlhttprequest') && r.duration>500){
                                                            if(r.name.startsWith('data:')||r.name.startsWith('chrome-extension')) continue;
                                                            slow.push({name:r.name.slice(0,140), type:r.initiatorType, dur: Math.round(r.duration)});
                                                    }
                                                }
                                                slow.sort((a,b)=>b.dur - a.dur);
                                                metrics.slow = slow.slice(0,5);
                                            }
                                            return metrics;
                                        })();
                                """
                                page.runJavaScript(js,  lambda m: self._log_perf_metrics(m))
                except Exception:
                        pass
        if browser is self._current_web_view():
            self._set_status_progress(None, browser)
            if success:
                self._show_status_message("Loaded", 1500)
            else:
                self._show_status_message("Failed to load page", 3500)
            self._update_status_from_view(browser)

    def _log_perf_metrics(self, metrics):
        try:
            if not metrics:
                return
            slow_str = ''
            slow = metrics.get('slow') or []
            if slow:
                parts = [f"{s['type']}:{s['dur']}ms" for s in slow]
                slow_str = ' slow=[' + ', '.join(parts) + ']'
            print(
                "PagePerf "
                f"dns={metrics.get('dns')}ms connect={metrics.get('connect')}ms ttfb={metrics.get('ttfb')}ms "
                f"resp={metrics.get('response')}ms dcl={metrics.get('domContentLoaded')}ms fp={metrics.get('firstPaint')}ms "
                f"fcp={metrics.get('firstContentfulPaint')}ms load={metrics.get('load')}ms" + slow_str
            )
        except Exception:
            pass
    
    def refresh_current_tab(self):
        """Refresh the current tab safely"""
        view = self._current_web_view()
        if view is not None and hasattr(view, 'reload'):
            view.reload()
    
    def _apply_web_engine_settings(self):
        """Apply privacy and security settings to web engine"""
        # Apply settings to all existing tabs and default profile
        enable_js = self.settings_manager.get('enable_javascript', True)
        enable_plugins = self.settings_manager.get('enable_plugins', True)
        enable_images = self.settings_manager.get('enable_images', True)
        enable_webgl = self.settings_manager.get('enable_webgl', True)
        enable_autoplay = self.settings_manager.get('enable_autoplay', False)
        block_popups = self.settings_manager.get('block_popups', True)
        enable_hw_accel = self.settings_manager.get('enable_hardware_acceleration', True)
        
        # Apply to default profile settings
        default_profile = QWebEngineProfile.defaultProfile()
        default_settings = default_profile.settings()
        
        if default_settings:
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, enable_js)
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, enable_plugins)
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, enable_images)
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, enable_webgl)
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, not enable_autoplay)
            # Allow window.open; pop-up blocking handled in new window handler
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
            default_settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, enable_hw_accel)
        
        # Apply to all existing tabs
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, CustomWebEngineView):
                page_settings = tab.page().settings()
                if page_settings:
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, enable_js)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, enable_plugins)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, enable_images)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, enable_webgl)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, not enable_autoplay)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
                    page_settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, enable_hw_accel)
        
        # Apply custom CSS/JS if provided
        self._apply_custom_styles_and_scripts()
    
    def _apply_custom_styles_and_scripts(self):
        """Apply custom CSS and JavaScript to web pages"""
        custom_css = self.settings_manager.get('custom_css', '')
        custom_js = self.settings_manager.get('custom_js', '')
        
        # Apply to all existing tabs
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, CustomWebEngineView):
                if custom_css:
                    css_script = f"""
                    (function() {{
                        var style = document.createElement('style');
                        style.type = 'text/css';
                        style.innerHTML = `{custom_css}`;
                        document.getElementsByTagName('head')[0].appendChild(style);
                    }})();
                    """
                    tab.page().runJavaScript(css_script)
                
                if custom_js:
                    tab.page().runJavaScript(custom_js)
    
    def apply_settings_to_new_tab(self, tab):
        """Apply current settings to a newly created tab"""
        if isinstance(tab, CustomWebEngineView):
            # Apply custom CSS/JS to new tab after page loads
            custom_css = self.settings_manager.get('custom_css', '')
            custom_js = self.settings_manager.get('custom_js', '')
            
            def inject_custom_code():
                if custom_css:
                    css_script = f"""
                    (function() {{
                        var style = document.createElement('style');
                        style.type = 'text/css';
                        style.innerHTML = `{custom_css}`;
                        document.getElementsByTagName('head')[0].appendChild(style);
                    }})();
                    """
                    tab.page().runJavaScript(css_script)
                
                if custom_js:
                    tab.page().runJavaScript(custom_js)
            
            # Connect to page load finished to inject code
            tab.loadFinished.connect(lambda: inject_custom_code())
        
        # Apply AI assistant settings
        if hasattr(self, 'ai_widget'):
            ai_enabled = self.settings_manager.get('ai_enabled', True)
            if not ai_enabled and self.ai_widget.isVisible():
                self.ai_widget.hide()
    
    def _apply_proxy_settings(self):
        """Apply proxy settings based on current configuration"""
        proxy_type = self.settings_manager.get('proxy_type', 'none')
        
        if proxy_type == 'none':
            self.disable_tor_proxy()
        elif proxy_type == 'tor':
            self.enable_tor_proxy()
        elif proxy_type == 'i2p':
            self.enable_i2p_proxy()
        elif proxy_type in ['http', 'socks5']:
            proxy = QNetworkProxy()
            if proxy_type == 'http':
                proxy.setType(QNetworkProxy.ProxyType.HttpProxy)
            else:
                proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
            
            proxy.setHostName(self.settings_manager.get('proxy_host', '127.0.0.1'))
            proxy.setPort(self.settings_manager.get('proxy_port', 8080))
            
            username = self.settings_manager.get('proxy_username', '')
            password = self.settings_manager.get('proxy_password', '')
            if username:
                proxy.setUser(username)
            if password:
                proxy.setPassword(password)
            
            QNetworkProxy.setApplicationProxy(proxy)

    def handle_download_request(self, download_request):
        download_item = DownloadItem(download_request)
        dm = self._ensure_download_manager()
        dm.add_download(download_item)
        download_request.accept()
    
    def show_download_manager(self):
        dm = self._ensure_download_manager()
        dm.show()
        dm.raise_()
        dm.activateWindow()
    
    def show_find_dialog(self):
        self.find_dialog.show_and_focus()
    
    def zoom_in(self):
        view = self._current_web_view()
        if view is not None:
            current_zoom = view.zoomFactor()
            view.setZoomFactor(min(current_zoom * 1.1, 5.0))
    
    def zoom_out(self):
        view = self._current_web_view()
        if view is not None:
            current_zoom = view.zoomFactor()
            view.setZoomFactor(max(current_zoom * 0.9, 0.1))
    
    def zoom_reset(self):
        view = self._current_web_view()
        if view is not None:
            view.setZoomFactor(1.0)
    
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()
    
    def view_source(self):
        try:
            # Store as instance variable to prevent garbage collection
            self.source_dialog = SourceViewDialog(self)
            self.source_dialog.show()
            self.source_dialog.raise_()
            self.source_dialog.activateWindow()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open View Source: {str(e)}")
    
    def print_page(self):
        view = self._current_web_view()
        if view is not None:
            printer = QPrinter()
            print_dialog = QPrintDialog(printer, self)
            if print_dialog.exec() == QDialog.DialogCode.Accepted:
                page = view.page() if hasattr(view, "page") else None
                if page is not None:
                    page.printToPdf(printer.outputFileName() or "page.pdf")
    
    def save_session(self):
        session_data = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if tab and hasattr(tab, 'url'):
                session_data.append({
                    'url': tab.url().toString(),
                    'title': self.tabs.tabText(i)
                })

        self.save_json(self.session_file, session_data)


    def restore_session(self):
        if not os.path.exists(self.session_file):
            self.add_new_tab(QUrl(self.homepage_url), 'Homepage')
            return

        session_data = self.load_json(self.session_file)
        if not session_data:
            self.add_new_tab(QUrl(self.homepage_url), 'Homepage')
        else:
            for tab_data in session_data:
                url = tab_data.get('url')
                title = tab_data.get('title', 'Tab')
                if url:
                    self.add_new_tab(QUrl(url), title)


    def closeEvent(self, event):
        # Check if we should confirm closing multiple tabs
        if (self.tabs.count() > 1 and 
            self.settings_manager.get('confirm_close_multiple_tabs', True)):
            reply = QMessageBox.question(
                self, "Close Browser",
                f"You have {self.tabs.count()} tabs open. Are you sure you want to close the browser?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        
        # Clear data on exit if enabled
        if self.settings_manager.get('clear_data_on_exit', False):
            self.clear_all_history()
            self.remove_all_cookies()
        
        # Save session if enabled
        if self.settings_manager.get('restore_session', True):
            self.save_session()
        
        # Close background worker pools
        pool = getattr(self, 'background_pool', None)
        if pool is not None:
            pool.shutdown(wait=True)
        io_pool = getattr(self, 'io_pool', None)
        if io_pool is not None and io_pool is not pool:
            io_pool.shutdown(wait=True)

        super().closeEvent(event)

    def _init_adblock_legacy(self):
        """Use the original AdBlockerWorker to build rules, then attach them."""
        async def run():
            # Pass shared thread pool and cache path so subset compilation can reuse cached list
            cache_path = os.path.join(self.data_dir, 'adblock_lists.cache')
            worker = AdBlockerWorker(pool=self.background_pool, cache_path=cache_path)
            await worker.download_adblock_lists()
            # In incremental mode worker.rules may be None intentionally
            if not worker.incremental_enabled and not worker.rules:
                worker._ensure_full_rules_async()
                print("Adblock: fallback rules scheduled build (incremental disabled)")
            # Store compiled engine (worker exposes should_block for incremental mode)
            engine = worker
            self.ad_blocker_rules = engine
            if hasattr(self, 'network_interceptor'):
                self.network_interceptor.ad_blocker_rules = engine
                self.network_interceptor.domain_block_set = set(getattr(engine, 'domain_block_set', set()))
            if hasattr(self, 'private_network_interceptor'):
                self.private_network_interceptor.ad_blocker_rules = engine
                self.private_network_interceptor.domain_block_set = set(getattr(engine, 'domain_block_set', set()))
            total_rules = len(worker._all_rule_lines) if getattr(worker, '_all_rule_lines', None) else 0
            print(f"Ad blocker ready: {total_rules} source rules (incremental={worker.incremental_enabled})")

        def _runner():
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(run())
                loop.close()
            except Exception as e:
                print(f"Adblock init failed: {e}")

        import threading
        threading.Thread(target=_runner, daemon=True).start()

    def show_about_dialog(self):
        license_text = """
        surfscape - Your Own Way to Navigate the Web with Freedom

        Author: André Machado, 2025
        License: GPL 3.0

        This program is free software; you can redistribute it and/or modify
        it under the terms of the GNU General Public License as published by
        the Free Software Foundation; either version 3 of the License, or
        (at your option) any later version.

        This program is distributed in the hope that it will be useful,
        but WITHOUT ANY WARRANTY; without even the implied warranty of
        MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
        GNU General Public License for more details.

        You should have received a copy of the GNU General Public License
        along with this program; if not, write to the Free Software
        Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
        """
        QMessageBox.about(self, "About surfscape", license_text)

# --- Main Application Entry Point ----------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Surfscape Browser")
    default_workers = max(2, os.cpu_count() or 1)
    parser.add_argument("--workers", type=int, default=default_workers,
                        help="Number of worker threads for background tasks (markdown rendering, adblock parsing, file IO).")
    # Fast start control (fast start enabled by default)
    fast_group = parser.add_mutually_exclusive_group()
    fast_group.add_argument("--fast-start", action="store_true", help="Force enable fast start optimizations (default)")
    fast_group.add_argument("--no-fast-start", action="store_true", help="Disable fast start (loads everything eagerly)")
    args, unknown = parser.parse_known_args()

    # Create the shared worker pool before QApplication so threads are ready immediately
    background_pool = IOPool(args.workers)

    # Trim custom args for Qt
    qt_argv = [sys.argv[0]] + [a for a in unknown]
    # Ensure Qt respects our software OpenGL attribute already set above
    app = QApplication(qt_argv)

    # Single-instance guard (prevents multi-window carousel). Set SURFSCAPE_ALLOW_MULTI=1 to allow multiple instances.
    single_instance_server = None
    if os.environ.get("SURFSCAPE_ALLOW_MULTI") not in ("1", "true", "True"):
        instance_key = "surfscape_single_instance"
        sock = QLocalSocket()
        sock.connectToServer(instance_key)
        if sock.waitForConnected(100):
            sock.close()
            sys.exit(0)
        single_instance_server = QLocalServer()
        if not single_instance_server.listen(instance_key):
            try:
                QLocalServer.removeServer(instance_key)
            except Exception:
                pass
            single_instance_server.listen(instance_key)
        # Keep reference so it isn't GC'd
        app._single_instance_server = single_instance_server
    # Determine fast_start flag from CLI (env handled inside Browser if None)
    fast_start_flag = True
    if args.no_fast_start:
        fast_start_flag = False
    elif args.fast_start:
        fast_start_flag = True
    window = Browser(io_pool=background_pool, fast_start=fast_start_flag)
    
    window.show()
    exit_code = app.exec()
    try:
        background_pool.shutdown(wait=True)
    except Exception:
        pass
    try:
        if hasattr(window, 'io_pool') and window.io_pool is not None and window.io_pool is not background_pool:
            window.io_pool.shutdown(wait=True)
    except Exception:
        pass
    sys.exit(exit_code)
    