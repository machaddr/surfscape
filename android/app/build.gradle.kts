plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.surfscape.browser"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.surfscape.browser"
        minSdk = 24
    targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        viewBinding = true
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}" // typical exclusions
        }
    }
}

val geckoviewVersion: String by rootProject.extra

// Automatically copy root icon/icon.png into launcher mipmap folders if present.
val surfscapeIcon: File = rootProject.file("icon/icon.png")
if (surfscapeIcon.exists()) {
    val densities = listOf("mdpi" to 48, "hdpi" to 72, "xhdpi" to 96, "xxhdpi" to 144, "xxxhdpi" to 192)
    densities.forEach { (density, _) ->
        tasks.register<Copy>("copyLauncherIcon_${density}") {
            from(surfscapeIcon)
            into(layout.projectDirectory.dir("src/main/res/mipmap-${density}"))
            rename { "ic_launcher.png" }
        }
    }
    // Adaptive foreground (same base image; ideally provide a 432x432 asset for best quality)
    tasks.register<Copy>("copyAdaptiveForeground") {
        from(surfscapeIcon)
        into(layout.projectDirectory.dir("src/main/res/mipmap-anydpi-v26"))
        rename { "ic_launcher_foreground.png" }
    }
    // Ensure copy tasks run before resource merging
    tasks.matching { it.name == "preBuild" }.configureEach {
        dependsOn(tasks.withType<Copy>().matching { it.name.startsWith("copyLauncherIcon_") })
        dependsOn("copyAdaptiveForeground")
    }
}

dependencies {
    implementation(platform("org.jetbrains.kotlin:kotlin-bom:2.0.21"))
    implementation("org.mozilla.geckoview:geckoview:$geckoviewVersion")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
