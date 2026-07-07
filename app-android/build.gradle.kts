// Root build file — plugin versions declared once here (apply false), each
// module applies only the plugins it needs. :network applies only the
// Kotlin/JVM + serialization plugins (no Android SDK required); :app additionally
// applies the Android application + Kotlin Android plugins.
plugins {
    id("com.android.application") version "8.4.1" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    id("org.jetbrains.kotlin.jvm") version "1.9.24" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "1.9.24" apply false
}
