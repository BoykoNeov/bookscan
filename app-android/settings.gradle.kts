pluginManagement {
    repositories {
        google()
        gradlePluginPortal()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "bookscan-android"

// :network is pure-JVM (no Android SDK needed) — DTOs, response parsing,
// retry/backoff. Buildable and testable in any environment with a JDK.
// :capture is pure-JVM too — the hover/auto-capture sharpness+stability
// scoring and gate/burst state machine (M3), same rationale.
// :app is the Android shell (Compose UI, CameraX, manifest) and requires
// compileSdk / the Android Gradle Plugin — see docs/plans/android-guided-capture.md
// for why the split exists.
include(":network")
include(":capture")
include(":app")
