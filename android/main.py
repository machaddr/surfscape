#!/usr/bin/env python3

import os
import sys

from PySide6.QtCore import QUrl, QObject, Slot, Signal, QStandardPaths
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent


class Bridge(QObject):
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        try:
            os.makedirs(self._app_data, exist_ok=True)
        except Exception as e:
            self.error.emit(f"Failed to create app data dir: {e}")

    @Slot(result=str)
    def appDataPath(self):
        return self._app_data

    @Slot(str, result=str)
    def loadJson(self, name):
        try:
            path = os.path.join(self._app_data, name)
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            self.error.emit(str(e))
            return ""

    @Slot(str, str, result=bool)
    def saveJson(self, name, content):
        try:
            path = os.path.join(self._app_data, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            self.error.emit(str(e))
            return False


def main():
    # Minimal Android entrypoint using Qt WebView (QML)
    # Note: This is an Android-friendly preview of Surfscape, not feature-parity.
    QGuiApplication.setApplicationName("Surfscape")
    QGuiApplication.setOrganizationName("Surfscape")

    app = QGuiApplication(sys.argv)

    # Qt WebView: Python initialize call removed; QML import triggers loading on Android.

    engine = QQmlApplicationEngine()

    # Collect and print QML warnings (helps diagnose early exit on Android)
    try:
        def _on_warnings(warnings):  # type: ignore
            for w in warnings:
                try:
                    msg = w.toString() if hasattr(w, 'toString') else str(w)
                except Exception:  # pragma: no cover
                    msg = str(w)
                print("[QML WARNING]", msg, flush=True)
        engine.warnings.connect(_on_warnings)  # type: ignore[attr-defined]
    except Exception as e:  # pragma: no cover
        print(f"[WARN] Could not hook QML warnings: {e}", flush=True)

    # Bridge for simple JSON persistence
    bridge = Bridge()

    # Pass initial URL from env or use project default
    initial_url = os.environ.get(
        "SURFSCAPE_HOME",
        "https://html.duckduckgo.com/html",
    )
    engine.rootContext().setContextProperty("initialUrl", initial_url)
    engine.rootContext().setContextProperty("Bridge", bridge)

    qml_path = os.path.join(os.path.dirname(__file__), "App.qml")
    if os.path.exists(qml_path):
        engine.load(QUrl.fromLocalFile(qml_path))
    else:
        # Fallback inline QML with simple WebView
        qml = """
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtWebView

ApplicationWindow {
    visible: true
    width: 400
    height: 720
    title: qsTr("Surfscape")

    WebView { anchors.fill: parent; url: initialUrl }
}
"""
        component = QQmlComponent(engine)
        component.setData(bytes(qml, "utf-8"), QUrl("qrc:/Inline.qml"))
        component.create()

    if not engine.rootObjects():
        print("[ERROR] No root QML objects loaded", flush=True)
        return 1
    code = app.exec()
    if code != 0:
        print(f"[INFO] App exited with code {code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
