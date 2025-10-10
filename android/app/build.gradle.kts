plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.surfscape.browser"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.surfscape.browser"
        minSdk = 21
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
    }

    signingConfigs {
        create("release") {
            val ksPath = System.getenv("SURFSCAPE_KEYSTORE_PATH")
            if (ksPath != null) {
                val f = File(ksPath)
                if (f.exists()) {
                    storeFile = file(ksPath)
                    storePassword = System.getenv("SURFSCAPE_KEYSTORE_PASSWORD")
                    keyAlias = System.getenv("SURFSCAPE_KEY_ALIAS")
                    keyPassword = System.getenv("SURFSCAPE_KEY_PASSWORD")
                }
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val ksPath = System.getenv("SURFSCAPE_KEYSTORE_PATH")
            if (ksPath != null) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                println("[Surfscape] Release signing variables not set. Provide SURFSCAPE_KEYSTORE_PATH, SURFSCAPE_KEYSTORE_PASSWORD, SURFSCAPE_KEY_ALIAS, SURFSCAPE_KEY_PASSWORD for signed build.")
            }
        }
        // Optional: keep debug definition but disable packaging task by shrinking variant
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            // Avoid accidental distribution: mark debuggable (default) and lower version code impact if desired
            isMinifyEnabled = false
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
        buildConfig = true
    }
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a")
            isUniversalApk = false
        }
    }
    bundle {
        language {
            enableSplit = false
        }
    }
    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}" // typical exclusions
            excludes += "/META-INF/{DEPENDENCIES,LICENSE,LICENSE.txt,license.txt,NOTICE,NOTICE.txt,notice.txt}"
        }
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = true
    }
}

val geckoviewVersion: String by rootProject.extra

dependencies {
    implementation(platform("org.jetbrains.kotlin:kotlin-bom:2.0.20"))
    implementation("org.mozilla.geckoview:geckoview:$geckoviewVersion")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("com.googlecode.openbeans:openbeans:1.0.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
