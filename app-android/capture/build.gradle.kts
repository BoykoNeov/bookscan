// Pure-JVM module: no Android SDK dependency. The hover/auto-capture scoring
// and gate/burst decision logic lives here (not in :app) specifically so it
// is buildable and unit-testable without a device or the Android Gradle
// Plugin — same rationale as :network. See docs/plans/android-guided-capture.md.
plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}
