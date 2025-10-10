# Preserve WebView clients and Chrome clients invoked by reflection.
-keepclassmembers class * extends android.webkit.WebChromeClient {
    public *;
}

-keepclassmembers class * extends android.webkit.WebViewClient {
    public *;
}

# Allow AndroidX WebKit optional APIs to shrink safely.
-dontwarn androidx.webkit.**
