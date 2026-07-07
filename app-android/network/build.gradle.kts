// Pure-JVM module: no Android SDK dependency. Retrofit/OkHttp/kotlinx.serialization
// are all plain-JVM libraries, so the real network client lives here and :app
// depends on it — the client is buildable and unit-testable without a device
// or the Android Gradle Plugin. See docs/plans/android-guided-capture.md.
plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    api("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    api("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")
    api("com.squareup.retrofit2:retrofit:2.11.0")
    api("com.squareup.retrofit2:converter-kotlinx-serialization:2.11.0")
    api("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation(kotlin("test"))
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.0")
}

tasks.test {
    useJUnitPlatform()
}
