import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebView

ApplicationWindow {
    id: window
    visible: true
    width: 400
    height: 720
    title: qsTr("Surfscape")

    // Settings and state
    property var settings: ({
        homepage: initialUrl || "https://html.duckduckgo.com/html",
        searchEngine: "duckduckgo"
    })
    property string homeUrl: settings.homepage
    property string searchEngine: settings.searchEngine

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            spacing: 6

            ToolButton { text: "☰"; onClicked: drawer.open() }

            ToolButton { text: "<"; enabled: currentView.canGoBack; onClicked: currentView.goBack() }
            ToolButton { text: ">"; enabled: currentView.canGoForward; onClicked: currentView.goForward() }
            ToolButton { text: "⟳"; onClicked: currentView.reload() }

            TextField {
                id: urlEdit
                Layout.fillWidth: true
                placeholderText: qsTr("Enter URL or search…")
                text: currentView ? currentView.url : ""
                onAccepted: navigateTo(text)
            }

            ToolButton { text: "🏠"; onClicked: navigateTo(homeUrl) }
            ToolButton { text: "☆"; onClicked: addBookmark(currentView.title, currentView.url) }
        }
    }

    // Simple tab model
    ListModel { id: tabs }

    function isLikelyUrl(text) {
        return text.match(/^https?:\/\//) || text.indexOf('.') > 0
    }

    function searchUrl(q) {
        switch (searchEngine) {
        case "google": return "https://www.google.com/search?q=" + encodeURIComponent(q)
        case "bing": return "https://www.bing.com/search?q=" + encodeURIComponent(q)
        case "startpage": return "https://www.startpage.com/do/search?q=" + encodeURIComponent(q)
        case "searx": return "https://searx.be/search?q=" + encodeURIComponent(q)
        default: return "https://duckduckgo.com/?q=" + encodeURIComponent(q)
        }
    }

    function navigateTo(text) {
        var u = text
        if (!isLikelyUrl(text)) u = searchUrl(text)
        currentView.url = u
    }

    function addTab(url, isPrivate) {
        tabs.append({ url: url || homeUrl, title: "New Tab", private: !!isPrivate })
        tabView.currentIndex = tabs.count - 1
        saveSession()
    }

    function closeTab(index) {
        if (tabs.count <= 1) return
    tabs.remove(index)
        tabView.currentIndex = Math.max(0, index - 1)
    saveSession()
    }

    function addBookmark(title, url) {
        if (!url) return
        var data = loadJsonList("bookmarks.json")
        data.push({ title: title || url, url: url })
        saveJsonList("bookmarks.json", data)
    }

    function addHistory(title, url) {
        if (!url) return
        var data = loadJsonList("history.json")
        data.unshift({ title: title || url, url: url, ts: Date.now() })
        if (data.length > 500) data.pop()
        saveJsonList("history.json", data)
    }

    function loadJsonList(name) {
        try {
            var raw = Bridge.loadJson(name)
            return raw && raw.length ? JSON.parse(raw) : []
        } catch (e) { return [] }
    }

    function saveJsonList(name, list) {
        try { Bridge.saveJson(name, JSON.stringify(list)) } catch (e) { }
    }

    TabBar {
        id: tabbar
        width: parent.width
        contentItem: RowLayout { spacing: 6 }
        Repeater {
            model: tabs
            TabButton {
                text: (model.title || "Tab")
                checked: index === tabView.currentIndex
                onClicked: tabView.currentIndex = index
                ToolTip.visible: hovered
                ToolTip.text: model.url
                contentItem: RowLayout {
                    spacing: 6
                    Label { text: (model.title || "Tab"); elide: Label.ElideRight }
                    ToolButton { text: "×"; onClicked: closeTab(index) }
                }
            }
        }
    TabButton { text: "+"; onClicked: addTab(homeUrl, false) }
    TabButton { text: "⊕"; onClicked: addTab(homeUrl, true); ToolTip.text: "New Private Tab"; ToolTip.visible: hovered }
    }

    StackLayout {
        id: tabView
        anchors.top: tabbar.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        currentIndex: Math.min(currentIndex, tabs.count - 1)

        Repeater {
            model: tabs
            WebView {
                id: webview
                url: model.url
                onUrlChanged: { model.url = url; urlEdit.text = url }
                onTitleChanged: model.title = title
                onLoadingChanged: function(loadRequest) {
                    if (loadRequest.status === WebView.LoadSucceededStatus) {
                        if (!model.private)
                            addHistory(title, url)
                        saveSession()
                    }
                }
                Component.onCompleted: {
                    // Ensure a title exists
                    if (!model.title) model.title = url
                }
            }
        }
    }

    readonly property alias currentView: tabView.currentItem

    Drawer {
        id: drawer
        width: Math.min(parent.width * 0.8, 360)
        height: parent.height

        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            padding: 10

            Label { text: "Surfscape"; font.bold: true; font.pointSize: 14 }

            Button { text: "New Tab"; onClicked: addTab(homeUrl, false) }
            Button { text: "New Private Tab"; onClicked: addTab(homeUrl, true) }
            Button { text: "Home"; onClicked: { navigateTo(homeUrl); drawer.close() } }
            Button { text: "Close Tab"; enabled: tabs.count > 1; onClicked: closeTab(tabView.currentIndex) }

            GroupBox {
                title: "Bookmarks"
                Layout.fillWidth: true
                Layout.fillHeight: true
                ListView {
                    id: bookmarksList
                    anchors.fill: parent
                    model: ListModel { id: bookmarksModel }
                    delegate: ItemDelegate {
                        width: parent.width
                        text: model.title
                        onClicked: { navigateTo(model.url); drawer.close() }
                        contentItem: RowLayout {
                            spacing: 6
                            Label { text: model.title; Layout.fillWidth: true; elide: Label.ElideRight }
                            ToolButton {
                                text: "−"
                                onClicked: {
                                    bookmarksModel.remove(index)
                                    saveJsonList("bookmarks.json", listModelToArray(bookmarksModel))
                                }
                            }
                        }
                    }
                    Component.onCompleted: {
                        var data = loadJsonList("bookmarks.json")
                        for (var i=0;i<data.length;i++) bookmarksModel.append(data[i])
                    }
                }
            }

            GroupBox {
                title: "History"
                Layout.fillWidth: true
                Layout.fillHeight: true
                ListView {
                    id: historyList
                    anchors.fill: parent
                    model: ListModel { id: historyModel }
                    delegate: ItemDelegate {
                        width: parent.width
                        text: model.title
                        onClicked: { navigateTo(model.url); drawer.close() }
                    }
                    Component.onCompleted: {
                        var data = loadJsonList("history.json")
                        for (var i=0;i<Math.min(50, data.length);i++) historyModel.append(data[i])
                    }
                }
            }

            GroupBox {
                title: "Settings"
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 6
                    TextField {
                        id: homeField
                        Layout.fillWidth: true
                        text: homeUrl
                        placeholderText: "Homepage URL"
                        onEditingFinished: { homeUrl = text; settings.homepage = text; saveSettings() }
                    }
                    ComboBox {
                        id: searchCombo
                        Layout.fillWidth: true
                        model: ["DuckDuckGo", "Google", "Bing", "Startpage", "Searx"]
                        currentIndex: ({duckduckgo:0, google:1, bing:2, startpage:3, searx:4}[searchEngine] || 0)
                        onActivated: {
                            var v = ["duckduckgo","google","bing","startpage","searx"][currentIndex]
                            searchEngine = v
                            settings.searchEngine = v
                            saveSettings()
                        }
                    }
                    Button { text: "Clear History"; onClicked: { saveJsonList("history.json", []); historyModel.clear() } }
                }
            }
        }
    }

    BusyIndicator {
        id: busy
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.top: parent.top
        anchors.topMargin: 10
        running: false
        visible: running
    }

    // Helpers
    function listModelToArray(m) {
        var arr = []
        for (var i = 0; i < m.count; i++) arr.push(m.get(i))
        return arr
    }

    function saveSession() {
        // Persist only non-private tabs
        var session = { currentIndex: tabView.currentIndex, tabs: [] }
        for (var i=0;i<tabs.count;i++) {
            var t = tabs.get(i)
            if (!t.private) session.tabs.push({ url: t.url, title: t.title })
        }
        Bridge.saveJson("session.json", JSON.stringify(session))
    }

    function loadSession() {
        try {
            var raw = Bridge.loadJson("session.json")
            if (!raw) return false
            var sess = JSON.parse(raw)
            if (sess.tabs && sess.tabs.length) {
                tabs.clear()
                for (var i=0;i<sess.tabs.length;i++) tabs.append({ url: sess.tabs[i].url, title: sess.tabs[i].title, private: false })
                tabView.currentIndex = Math.min(sess.currentIndex || 0, tabs.count-1)
                return true
            }
            return false
        } catch (e) { return false }
    }

    function loadSettings() {
        try {
            var raw = Bridge.loadJson("settings.json")
            if (raw && raw.length) settings = JSON.parse(raw)
        } catch (e) {}
    }

    function saveSettings() {
        try { Bridge.saveJson("settings.json", JSON.stringify(settings)) } catch (e) {}
    }

    Component.onCompleted: {
        loadSettings()
        if (!loadSession()) {
            tabs.append({ url: homeUrl, title: "Home", private: false })
            tabView.currentIndex = 0
        }
    }
}
