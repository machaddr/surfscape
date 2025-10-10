# GeckoView / Gecko engine keep rules to avoid stripping critical classes or JNI-called methods
# (Currently minify is disabled, but future-proof for release builds.)
-keep class org.mozilla.geckoview.** { *; }
-keep class org.mozilla.gecko.** { *; }
# Keep Mozilla service process classes referenced via manifest/IPC
-keep class org.mozilla.gecko.process.** { *; }
# Preserve enums & annotated (might be used reflectively)
-keepclassmembers enum * { *; }
# Avoid warnings for missing optional classes
-dontwarn org.mozilla.**
-dontwarn org.yaml.snakeyaml.**
-dontwarn java.beans.**
-keep class org.yaml.snakeyaml.** { *; }
-keep class java.beans.** { *; }
-keep class com.sun.beans.** { *; }
