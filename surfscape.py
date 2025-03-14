#!/usr/bin/env python3

import os, sys, json, asyncio, aiohttp, re, pyaudio, speech_recognition as sr, anthropic, markdown
from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import QUrl, Qt , QDateTime, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QTabWidget, QToolBar, QMessageBox, QMenu, QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout, QColorDialog, QFontDialog
from PyQt6.QtGui import QIcon, QPixmap, QAction, QKeySequence, QShortcut, QColor, QFont
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtNetwork import QNetworkCookie, QNetworkProxy
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineProfile
from adblockparser import AdblockRules

class ClaudeAIWorker(QtCore.QThread):
    response_received = QtCore.pyqtSignal(str)

    def __init__(self, user_input, parent=None):
        super().__init__(parent)
        self.user_input = user_input

    def run(self):
        api_key = "YOUR-CLAUDE-API"  # Store securely

        client = anthropic.Anthropic(api_key=api_key)

        try:
            response = client.messages.create(
                model="claude-3-7-sonnet-20250219",
                messages=[
                    {"role": "user", "content": self.user_input}
                ],
                max_tokens=4096,
                temperature=0.7
            )
            self.response_received.emit(response.content[0].text)
        except Exception as e:
            self.response_received.emit(f"Error: {e}")

class ClaudeAIWidget(QtWidgets.QWidget):
    def closeEvent(self, event):
            if hasattr(self, 'worker') and self.worker.isRunning():
                self.worker.quit()
                if not self.worker.wait(1000):  # Wait up to 1 second
                    self.worker.terminate()  # Force terminate if not quitting cleanly
                    self.worker.wait()  # Wait for termination
            event.accept()
        
    def __init__(self):
        super().__init__()

        # Set up the layout
        self.layout = QtWidgets.QVBoxLayout(self)

        # Output window (read-only)
        self.output_window = QtWidgets.QTextEdit(self)
        self.output_window.setStyleSheet("background-color: #FDF6E3; color: #657B83;")
        
        # Set font size and type
        font = QtGui.QFont("Monospace")
        font.setPointSize(11)
        self.output_window.setFont(font)
        
        self.output_window.setReadOnly(True)        
        self.layout.addWidget(self.output_window)

        # Input field and send button layout
        input_layout = QtWidgets.QHBoxLayout()

        self.input_field = QtWidgets.QLineEdit(self)
        input_layout.addWidget(self.input_field)
        
        # Add language selector for speech recognition
        self.language_selector = QtWidgets.QComboBox(self)
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
        self.language_selector.setMaximumWidth(120)
        input_layout.addWidget(self.language_selector)
        
        # Add a microphone button to trigger voice input
        self.microphone_button = QtWidgets.QPushButton("Mic", self)
        self.microphone_button.setToolTip("Start/Stop Voice Input")
        self.microphone_button.clicked.connect(self.toggle_voice_input)
        self.is_listening = False  # Flag to track voice input state
        input_layout.addWidget(self.microphone_button)
        
        # Add a send button to send the input
        self.send_button = QtWidgets.QPushButton("Send", self)
        self.send_button.setToolTip("Send the input to Claude")
        self.send_button.clicked.connect(self.send_request)
        input_layout.addWidget(self.send_button)

        self.layout.addLayout(input_layout)
        
        # Add a loading spinner while getting the response from Claude
        self.loading_spinner = QtWidgets.QProgressBar(self)
        self.loading_spinner.setRange(0, 0)  # Indeterminate progress
        self.layout.addWidget(self.loading_spinner)
        self.loading_spinner.hide()  # Hide initially

        # Initialize worker
        self.worker = ClaudeAIWorker("")
        self.worker.response_received.connect(self.update_output)

        # Connect signals to show and hide the loading spinner
        self.worker.started.connect(self.loading_spinner.show)
        self.worker.finished.connect(self.loading_spinner.hide)

        # Send request on pressing Enter
        self.input_field.returnPressed.connect(self.send_request)
        
        # Set size of AI prompt widget
        self.setFixedWidth(int(0.25 * QtWidgets.QApplication.primaryScreen().size().width()))
        
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
        self.silence_timer = QtCore.QTimer(self)
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
        QtCore.QThread.msleep(100)
        
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
            # Get the selected language code from the combobox
            selected_language = self.language_selector.currentText()
            language_code = selected_language.split('(')[1].strip(')')
            
            user_input = recognizer.recognize_google(audio, language=language_code)
            if user_input:
                self.input_field.setText(user_input)
                # Only send if we detected actual text
                if len(user_input.strip()) > 0:
                    self.send_request()
                    # After sending, wait a bit before stopping
                    QtCore.QTimer.singleShot(500, self.stop_listening)
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
            QtCore.QTimer.singleShot(2000, self.stop_listening)
        except Exception as e:
            # Generic error handler
            self.input_field.setPlaceholderText(f"Error: {str(e)[:20]}")
            QtCore.QTimer.singleShot(2000, self.stop_listening)            
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
        if self.markdown_module:
            try:
                # Convert markdown to HTML with code highlighting
                html = self.markdown_module.markdown(text, extensions=['fenced_code'])
                return html
            except:
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

class AdBlocker(QWebEngineUrlRequestInterceptor):
    def __init__(self, rules):
        super().__init__()
        self.thread = QThread()
        self.worker = AdBlockerWorker(rules)
        self.worker.moveToThread(self.thread)
        self.thread.start()

    def interceptRequest(self, info):
        url = info.requestUrl().toString()
        self.worker.check_url.emit(url, info)

class AdBlockerWorker(QObject):
    check_url = pyqtSignal(str, object)

    def __init__(self, rules):
        super().__init__()
        self.rules = rules
        self.check_url.connect(self.handle_check_url)

    async def download_adblock_lists(self):
        easylist_url = "https://easylist.to/easylist/easylist.txt"

        async with aiohttp.ClientSession() as session:
            async with session.get(easylist_url) as easylist_response:
                easylist_text = await easylist_response.text()

        raw_rules = easylist_text.splitlines()
        self.rules = AdblockRules(raw_rules)

    async def should_block(self, url):
        if self.rules is None:
            await self.download_adblock_lists()
        return self.rules.should_block(url)
    
    def handle_check_url(self, url, info):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        if loop.run_until_complete(self.should_block(url)):
            info.block(True)

class Browser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("surfscape")
        self.setMinimumSize(800, 640)
        
        # Use a transparent pixmap
        transparent_pixmap = QPixmap(1, 1)
        transparent_pixmap.fill()
        self.setWindowIcon(QIcon(transparent_pixmap))
        
        self.showMaximized()

        # Paths for the data files
        self.data_dir = os.path.expanduser("~/.surfscape") if os.name != 'nt' else os.path.join(os.getenv("USERPROFILE"), ".surfscape")
        os.makedirs(self.data_dir, exist_ok=True)
        self.bookmarks_file = os.path.join(self.data_dir, "bookmarks.json")
        self.history_file = os.path.join(self.data_dir, "history.json")
        self.cookies_file = os.path.join(self.data_dir, "cookies.json")
        self.settings_file = os.path.join(self.data_dir, "settings.json")
        
        self.background_color = QColor()  # Initialize background_color
        self.font_color = QColor()  # Initialize font_color
        self.font = QFont()  # Initialize font

        self.bookmarks = self.load_json(self.bookmarks_file)
        self.history = self.load_json(self.history_file)
        self.cookies = self.load_json(self.cookies_file)
        self.settings = self.load_json(self.settings_file)
        
        self.homepage_url = self.settings.get('homepage') if self.settings else "https://html.duckduckgo.com/html"
        
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Enter URL or Search Query")

        # Set up ad blocker
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        worker = AdBlockerWorker(None)
        loop.run_until_complete(worker.download_adblock_lists())
        self.ad_blocker = AdBlocker(worker.rules)
        QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(self.ad_blocker)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBarDoubleClicked.connect(self.tab_open_doubleclick)
        self.tabs.currentChanged.connect(self.current_tab_changed)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_current_tab)
        self.setCentralWidget(self.tabs)

        self.add_new_tab(QUrl(self.homepage_url), "Homepage")
        
        self.create_menu_bar()
        self.create_shortcuts()

        # Populate history and bookmarks menus
        self.update_history_menu()
        self.update_bookmarks_menu()
        self.update_cookies_menu()  # Update cookies menu
        
        self.load_cookies_to_web_engine()  # Load cookies into the web engine
        
        if os.path.exists(self.settings_file):
            self.load_settings()  # Load settings

    def load_json(self, file_path):
        """Load data from a JSON file, or return an empty list if the file doesn't exist."""
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        return []

    def save_json(self, file_path, data):
        """Save data to a JSON file."""
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    def add_new_tab(self, qurl=None, label="Homepage"):
        if qurl is None:
            qurl = QUrl(self.homepage_url)

        browser = QWebEngineView()
        browser.setUrl(qurl)

        i = self.tabs.addTab(browser, label)
        self.tabs.setCurrentIndex(i)

        browser.urlChanged.connect(lambda qurl, browser=browser: self.update_urlbar(qurl, browser))
        browser.loadFinished.connect(lambda _, i=i, browser=browser: self.update_title(browser))
        browser.loadFinished.connect(lambda _, i=i, browser=browser: self.tabs.setTabText(i, browser.page().title()))
        browser.loadFinished.connect(lambda: self.add_to_history(qurl, browser.page().title()))  # Add to history
        browser.page().profile().cookieStore().cookieAdded.connect(self.add_cookie)  # Add cookie

    def tab_open_doubleclick(self, i):
        if i == -1:
            self.add_new_tab()

    def current_tab_changed(self, i):
        qurl = self.tabs.currentWidget().url()
        self.update_urlbar(qurl, self.tabs.currentWidget())
        self.update_title(self.tabs.currentWidget())

    def close_current_tab(self, i):
        if self.tabs.count() < 2:
            return

        self.tabs.removeTab(i)

    def update_title(self, browser):
        if browser != self.tabs.currentWidget():
            return

        current_widget = self.tabs.currentWidget()
        if current_widget is not None and current_widget.page() is not None:
            title = current_widget.page().title()
            self.setWindowTitle(f"surfscape - {title}")

    def navigate_home(self):
        self.tabs.currentWidget().setUrl(QUrl(self.homepage_url))

    def update_urlbar(self, q, browser=None):
        if browser != self.tabs.currentWidget():
            return

        # Set full URL including the scheme
        self.url_bar.setText(q.toString(QUrl.ComponentFormattingOption.FullyEncoded))
        self.url_bar.setCursorPosition(0)

    def navigate_to_url(self):
        url = self.url_bar.text()
        if not url.startswith("http://") and not url.startswith("https://"):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                url = f"https://html.duckduckgo.com/html?q={url}"
        self.tabs.currentWidget().setUrl(QUrl(url))

    def create_menu_bar(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("File")
        new_tab_action = QAction("New Tab", self)
        new_tab_action.triggered.connect(lambda _: self.add_new_tab())
        file_menu.addAction(new_tab_action)
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

        # History menu (before Bookmarks)
        self.history_menu = menu_bar.addMenu("History")
        self.update_history_menu()

        # Bookmarks menu
        self.bookmarks_menu = menu_bar.addMenu("Bookmarks")
        self.update_bookmarks_menu()

        # Cookies menu
        self.cookies_menu = menu_bar.addMenu("Cookies")
        self.update_cookies_menu()

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
        self.back_button.triggered.connect(lambda: self.tabs.currentWidget().back())
        navtb.addAction(self.back_button)

        self.forward_button = QAction("→", self)
        self.forward_button.triggered.connect(lambda: self.tabs.currentWidget().forward())
        navtb.addAction(self.forward_button)

        self.reload_button = QAction("⟳", self)
        self.reload_button.triggered.connect(lambda: self.tabs.currentWidget().reload())
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
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(lambda: self.add_new_tab())
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(lambda: self.close_current_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(lambda: self.tabs.currentWidget().reload())
        QShortcut(QKeySequence("Alt+Home"), self).activated.connect(self.navigate_home)
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(lambda: self.tabs.currentWidget().back())
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(lambda: self.tabs.currentWidget().forward())
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.toggle_bookmark)

    def toggle_bookmark(self):
        url = self.url_bar.text()
        if url in [bookmark[1] for bookmark in self.bookmarks]:
            self.bookmarks = [bookmark for bookmark in self.bookmarks if bookmark[1] != url]
            for action in self.bookmarks_menu.actions():
                if action.data() == url:
                    self.bookmarks_menu.removeAction(action)
            self.bookmark_button.setIconText("☆")  # Set to unpressed state
        else:
            current_widget = self.tabs.currentWidget()
            if current_widget is not None and current_widget.page() is not None:
                title = current_widget.page().title()
                self.bookmarks.append([title, url])
                bookmark_action = QAction(title, self)
                bookmark_action.setData(url)
                bookmark_action.triggered.connect(lambda _, url=url: self.tabs.currentWidget().setUrl(QUrl(url)))
                self.bookmarks_menu.addAction(bookmark_action)
            self.bookmark_button.setIconText("★")  # Change to pressed state
        self.save_json(self.bookmarks_file, self.bookmarks)  # Save bookmarks

        # Reset the bookmark button state when the URL changes
        self.url_bar.textChanged.connect(self.reset_bookmark_button)

    def reset_bookmark_button(self):
        url = self.url_bar.text()
        if url not in [bookmark[1] for bookmark in self.bookmarks]:
            self.bookmark_button.setIconText("☆")  # Set to unpressed state
            
    def show_ai_widget(self):
        # Check if we already have a splitter and AI widget
        if not hasattr(self, 'splitter'):
            # Create a splitter to hold both the tabs and the AI widget
            self.splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
            
            # Move the tabs to the splitter
            self.tabs.setParent(self.splitter)
            self.splitter.addWidget(self.tabs)
            
            # Create the AI widget and add it to the splitter
            self.ai_widget = ClaudeAIWidget()
            self.splitter.addWidget(self.ai_widget)
            
            # Set reasonable sizes for the splitter (browser takes more space than AI panel)
            self.splitter.setSizes([int(self.width() * 0.7), int(self.width() * 0.3)])
            
            # Make the splitter the central widget
            self.setCentralWidget(self.splitter)
        else:
            # Toggle visibility of the AI panel
            if self.ai_widget.isVisible():
                self.ai_widget.hide()
            else:
                self.ai_widget.show()
                # Restore reasonable proportions
                self.splitter.setSizes([int(self.width() * 0.7), int(self.width() * 0.3)])

    def select_all_text(self):
        widget = self.focusWidget()
        if isinstance(widget, QLineEdit):
            widget.selectAll()
        elif isinstance(self.tabs.currentWidget(), QWebEngineView):
            self.tabs.currentWidget().page().runJavaScript("document.execCommand('selectAll');")

    def cut_text(self):
        widget = self.focusWidget()
        if isinstance(widget, QLineEdit):
            widget.cut()
        elif isinstance(self.tabs.currentWidget(), QWebEngineView):
            self.tabs.currentWidget().page().runJavaScript("document.execCommand('cut');")

    def copy_text(self):
        widget = self.focusWidget()
        if isinstance(widget, QLineEdit):
            widget.copy()
        elif isinstance(self.tabs.currentWidget(), QWebEngineView):
            self.tabs.currentWidget().page().runJavaScript("document.execCommand('copy');")

    def paste_text(self):
        widget = self.focusWidget()
        if isinstance(widget, QLineEdit):
            widget.paste()
        elif isinstance(self.tabs.currentWidget(), QWebEngineView):
            self.tabs.currentWidget().page().runJavaScript("document.execCommand('paste');")
            
    def add_to_history(self, qurl, title):
        """ Add a page to the history """
        url = self.url_bar.text()
        if url != "about:blank":
            self.history.append((title, url))
            self.update_history_menu()
            self.save_json(self.history_file, self.history)  # Save history

    def update_history_menu(self):
        """ Update the History menu with the latest entries """
        self.history_menu.clear()
        for title, url in reversed(self.history[-50:]):  # Limit to the last 50 entries
            history_action = QAction(title, self)
            history_action.triggered.connect(lambda _, url=url: self.tabs.currentWidget().setUrl(QUrl(url)))
            self.history_menu.addAction(history_action)

    def update_bookmarks_menu(self):
        """ Update the Bookmarks menu with the loaded bookmarks """
        self.bookmarks_menu.clear()
        for title, url in self.bookmarks:
            bookmark_action = QAction(title, self)
            bookmark_action.triggered.connect(lambda _, url=url: self.tabs.currentWidget().setUrl(QUrl(url)))
            self.bookmarks_menu.addAction(bookmark_action)

    def update_cookies_menu(self):
        """ Update the Cookies menu with the loaded cookies """
        self.cookies_menu.clear()
        for cookie in self.cookies:
            cookie_action = QAction(f"{cookie['name']} - {cookie['domain']}", self)
            self.cookies_menu.addAction(cookie_action)

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

        self.save_json(self.cookies_file, self.cookies)
        self.update_cookies_menu()
        
    def load_cookies_to_web_engine(self):
        """ Load cookies into the web engine """
        profile = self.tabs.currentWidget().page().profile()
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

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")

        layout = QVBoxLayout()
        
        # Homepage section
        homepage_label = QLabel("Homepage:")
        layout.addWidget(homepage_label)
        
        homepage_edit = QLineEdit()
        homepage_edit.setText(self.homepage_url)
        layout.addWidget(homepage_edit)
        
        # Button to set homepage
        set_homepage_button = QPushButton("Set Homepage")
        set_homepage_button.clicked.connect(lambda: self.set_homepage(homepage_edit.text()))
        set_homepage_button.clicked.connect(lambda: homepage_edit.setText(homepage_edit.text()))
        set_homepage_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Homepage set successfully"))
        layout.addWidget(set_homepage_button)
        
        # Separator
        layout.addStretch()

        # Bookmarks section
        bookmarks_label = QLabel("Bookmarks:")
        layout.addWidget(bookmarks_label)

        bookmarks_list = QListWidget()
        for title, url in self.bookmarks:
            bookmarks_list.addItem(f"{title} - {url}")
        layout.addWidget(bookmarks_list)

        # Add bookmark section
        add_layout = QHBoxLayout()
        add_title_edit = QLineEdit()
        add_title_edit.setPlaceholderText("Title")
        add_url_edit = QLineEdit()
        add_url_edit.setPlaceholderText("URL")
        add_button = QPushButton("Add")
        add_button.clicked.connect(lambda: self.add_bookmark(add_title_edit.text(), add_url_edit.text(), bookmarks_list))
        add_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Bookmark added successfully"))
        add_layout.addWidget(add_title_edit)
        add_layout.addWidget(add_url_edit)
        add_layout.addWidget(add_button)
        layout.addLayout(add_layout)

        # Remove bookmark button
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(lambda: self.remove_selected_bookmark(bookmarks_list))
        remove_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Selected bookmark(s) removed successfully"))
        layout.addWidget(remove_button)

        # History section
        history_label = QLabel("History:")
        layout.addWidget(history_label)

        history_list = QListWidget()
        for title, url in self.history:
            item = QListWidgetItem(f"{title} - {url}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            history_list.addItem(item)
        layout.addWidget(history_list)

        # Clear all history button
        clear_history_button = QPushButton("Clear All History")
        clear_history_button.clicked.connect(self.clear_all_history)
        clear_history_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "All history cleared successfully"))
        layout.addWidget(clear_history_button)

        # Connect to update history when checkbox state changes
        history_list.itemChanged.connect(lambda item: self.update_history_on_uncheck(item, history_list))

        # Cookies section
        cookies_label = QLabel("Cookies:")
        layout.addWidget(cookies_label)

        cookies_list = QListWidget()
        for cookie in self.cookies:
            cookies_list.addItem(f"{cookie['name']} - {cookie['value']}")
        layout.addWidget(cookies_list)

        # Remove all cookies button
        remove_all_cookies_button = QPushButton("Remove All Cookies")
        remove_all_cookies_button.clicked.connect(self.remove_all_cookies)
        remove_all_cookies_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "All cookies removed successfully"))
        layout.addWidget(remove_all_cookies_button)
        
        # Enable/Disable Tor Buttons
        tor_buttons_layout = QHBoxLayout()

        enable_tor_button = QPushButton("Enable Tor")
        enable_tor_button.clicked.connect(self.enable_tor_proxy)
        enable_tor_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Tor proxy enabled"))
        tor_buttons_layout.addWidget(enable_tor_button)

        disable_tor_button = QPushButton("Disable Tor")
        disable_tor_button.clicked.connect(self.disable_tor_proxy)
        disable_tor_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Tor proxy disabled"))
        tor_buttons_layout.addWidget(disable_tor_button)

        layout.addLayout(tor_buttons_layout)
        
        # Enable/Disable I2P Buttons
        i2p_buttons_layout = QHBoxLayout()
        
        enable_i2p_button = QPushButton("Enable I2P")
        enable_i2p_button.clicked.connect(self.enable_i2p_proxy)
        enable_i2p_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "I2P proxy enabled"))
        i2p_buttons_layout.addWidget(enable_i2p_button)
        
        disable_i2p_button = QPushButton("Disable I2P")
        disable_i2p_button.clicked.connect(self.disable_i2p_proxy)
        disable_i2p_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "I2P proxy disabled"))
        i2p_buttons_layout.addWidget(disable_i2p_button)
        
        layout.addLayout(i2p_buttons_layout)
        
        # User defined theme, font, and font color
        theme_font_layout = QHBoxLayout()

        # Theme
        theme_label = QLabel("Theme:")
        theme_font_layout.addWidget(theme_label)
        theme_button = QPushButton("Choose Color")
        theme_button.clicked.connect(self.choose_background_color)
        theme_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Background color set successfully"))
        theme_font_layout.addWidget(theme_button)
        
        # Font Color
        font_color_label = QLabel("Font Color:")
        theme_font_layout.addWidget(font_color_label)
        font_color_button = QPushButton("Choose Font Color")
        font_color_button.clicked.connect(self.choose_font_color)
        font_color_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Font color set successfully"))
        theme_font_layout.addWidget(font_color_button)

        # Font
        font_label = QLabel("Font:")
        theme_font_layout.addWidget(font_label)
        font_button = QPushButton("Choose Font")
        font_button.clicked.connect(self.choose_font)
        font_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Font set successfully"))
        theme_font_layout.addWidget(font_button)

        layout.addLayout(theme_font_layout)
        
        # Separator
        layout.addStretch()
        
        # Reset Theme, Font Color, and Font
        reset_theme_font_layout = QHBoxLayout()
        reset_theme_button = QPushButton("Reset Colors")
        reset_theme_button.clicked.connect(lambda: self.setStyleSheet(""))
        reset_theme_button.clicked.connect(self.reset_background_color)
        reset_theme_button.clicked.connect(self.reset_font_color)
        reset_theme_button.clicked.connect(self.reset_font)
        reset_theme_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Colors and font reset successfully"))
        reset_theme_font_layout.addWidget(reset_theme_button)
        layout.addLayout(reset_theme_font_layout)
        
        # Save settings button
        save_settings_button = QPushButton("Save Settings")
        save_settings_button.clicked.connect(self.save_settings)
        save_settings_button.clicked.connect(lambda: QMessageBox.information(self, "Success", "Settings saved successfully"))
        layout.addWidget(save_settings_button)

        dialog.setLayout(layout)
        dialog.exec()
        
    def set_homepage(self, homepage_url):
        self.homepage_url = homepage_url
        self.save_settings()

    def add_bookmark(self, title, url, bookmarks_list):
        if title and url:
            self.bookmarks.append([title, url])
            self.save_json(self.bookmarks_file, self.bookmarks)
            bookmarks_list.addItem(f"{title} - {url}")
            self.update_bookmarks_menu()

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
        self.update_bookmarks_menu()

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
        profile = self.tabs.currentWidget().page().profile()
        cookie_store = profile.cookieStore()
        cookie_store.deleteAllCookies()
        for cookie in self.cookies:
            qcookie = QNetworkCookie(
            cookie['name'].encode('utf-8'),
            cookie['value'].encode('utf-8')
            )
            qcookie.setDomain(cookie['domain'])
            qcookie.setPath(cookie['path'])
            qcookie.setExpirationDate(QDateTime.fromString(cookie['expiry'], Qt.DateFormat.ISODate))
            cookie_store.setCookie(qcookie)
        self.update_cookies_menu()
        
    def choose_background_color(self):
        self.background_color = QColorDialog.getColor()
        if self.background_color.isValid():
            self.apply_styles()
            
    def choose_font(self):
        font, ok = QFontDialog.getFont()
        if ok:
            QApplication.instance().setFont(font)
        
    def choose_font_color(self):
        self.font_color = QColorDialog.getColor()
        if self.font_color.isValid():
            self.apply_styles()
            
    def apply_styles(self):
        style = ""
        if hasattr(self, 'background_color') and self.background_color.isValid():
            style += f"background-color: {self.background_color.name()};"
        if hasattr(self, 'font_color') and self.font_color.isValid():
            style += f" color: {self.font_color.name()};"
        self.setStyleSheet(style)
        
    def reset_background_color(self):
        self.background_color = QColor(Qt.GlobalColor.white)

    def reset_font_color(self):
        self.font_color = QColor(Qt.GlobalColor.black)

    def reset_font(self):
        QApplication.instance().setFont(QFont())
        
    def enable_tor_proxy(self):
        # Set up Tor proxy
        proxy = QNetworkProxy()
        proxy.setType(QNetworkProxy.ProxyType.Socks5Proxy)
        proxy.setHostName("127.0.0.1")
        proxy.setPort(9050)
        QNetworkProxy.setApplicationProxy(proxy)
        
    def disable_tor_proxy(self):
        # Disable the proxy
        QNetworkProxy.setApplicationProxy(QNetworkProxy())
        
    def enable_i2p_proxy(self):
        # Set up I2P proxy
        proxy = QNetworkProxy()
        proxy.setType(QNetworkProxy.ProxyType.HttpProxy)
        proxy.setHostName("127.0.0.1")
        proxy.setPort(4444)
        QNetworkProxy.setApplicationProxy(proxy)
        
    def disable_i2p_proxy(self):
        # Disable the proxy
        QNetworkProxy.setApplicationProxy(QNetworkProxy())
            
    def save_settings(self):
        settings = {
            'homepage': self.homepage_url,
            'background_color': self.background_color.name(),
            'font_color': self.font_color.name(),
            'font': QApplication.instance().font().toString()
        }
        with open(os.path.join(self.data_dir, 'settings.json'), 'w') as f:
            json.dump(settings, f, indent=4)
            
    def load_settings(self):
        with open(os.path.join(self.data_dir, 'settings.json'), 'r') as f:
            settings = json.load(f)
        self.homepage_url = settings['homepage']
        self.background_color = QColor(settings['background_color'])
        self.font_color = QColor(settings['font_color'])
        self.apply_styles()
        font = QFont()
        font.fromString(settings['font'])
        QApplication.instance().setFont(font)

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Browser()
    window.show()
    sys.exit(app.exec())
    