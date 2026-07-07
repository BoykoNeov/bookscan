// Android shell module: Compose UI, CameraX (from M2 on), manifest.
// UNVERIFIED IN THIS ENVIRONMENT — no Android SDK / compileSdk is installed
// here (see docs/plans/android-guided-capture.md's M1 note). Written against
// current (2026) AGP/Compose-BOM versions but not yet built; first compile
// must happen on an SDK-equipped machine before this is trusted.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.bookscan.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bookscan.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(project(":network"))

    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.1")
    implementation("androidx.core:core-ktx:1.13.1")
}
