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

// Generate properly sized launcher icons from root icon/icon.png (must be square >= 512px recommended)
val surfscapeIcon: File = rootProject.file("icon/icon.png")
if (surfscapeIcon.exists()) {
    val densitySizes = listOf(
        "mdpi" to 48,
        "hdpi" to 72,
        "xhdpi" to 96,
        "xxhdpi" to 144,
        "xxxhdpi" to 192,
    )

    // Single task to (re)generate all launcher icons only when source changes
    val generateLauncherIcons = tasks.register("generateLauncherIcons") {
        inputs.file(surfscapeIcon)
        outputs.upToDateWhen {
            densitySizes.all { (d, size) ->
                project.file("src/main/res/mipmap-$d/ic_launcher.png").exists() &&
                project.file("src/main/res/mipmap-anydpi-v26/ic_launcher_foreground.png").exists()
            }
        }
        doLast {
            val srcImage = javax.imageio.ImageIO.read(surfscapeIcon)
            require(srcImage != null) { "Could not read base icon at ${surfscapeIcon}" }
            densitySizes.forEach { (density, size) ->
                val outDir = project.file("src/main/res/mipmap-$density")
                outDir.mkdirs()
                val scaled = java.awt.image.BufferedImage(size, size, java.awt.image.BufferedImage.TYPE_INT_ARGB)
                val g = scaled.createGraphics()
                g.drawImage(srcImage.getScaledInstance(size, size, java.awt.Image.SCALE_SMOOTH), 0, 0, null)
                g.dispose()
                val outFile = File(outDir, "ic_launcher.png")
                javax.imageio.ImageIO.write(scaled, "PNG", outFile)
            }
            // Adaptive foreground: use largest (432x432 recommended). If base larger, scale; else upscale (quality loss acceptable for placeholder).
            val fgDir = project.file("src/main/res/mipmap-anydpi-v26")
            fgDir.mkdirs()
            val fgSize = 432
            val fgImg = java.awt.image.BufferedImage(fgSize, fgSize, java.awt.image.BufferedImage.TYPE_INT_ARGB)
            val g2 = fgImg.createGraphics()
            g2.drawImage(srcImage.getScaledInstance(fgSize, fgSize, java.awt.Image.SCALE_SMOOTH), 0, 0, null)
            g2.dispose()
            javax.imageio.ImageIO.write(fgImg, "PNG", File(fgDir, "ic_launcher_foreground.png"))
        }
    }

    // Hook before resource processing
    tasks.matching { it.name == "preBuild" }.configureEach { dependsOn(generateLauncherIcons) }
}

dependencies {
    implementation(platform("org.jetbrains.kotlin:kotlin-bom:2.2.0"))
    implementation("org.mozilla.geckoview:geckoview:$geckoviewVersion")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
