plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Kernel pieces that are generated, not committed (see tools/android/build_apk.py):
//   kernel/bindings/kotlin   UniFFI Kotlin binding
//   app/build/kernel-libs    libreva_kernel.so for arm64-v8a and x86_64
val kernelBindings = rootProject.file("../kernel/bindings/kotlin")
val kernelLibs = layout.buildDirectory.dir("kernel-libs")

android {
    namespace = "app.reva"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.reva.android"
        minSdk = 31
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    buildTypes {
        debug { applicationIdSuffix = "" }
        release { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    sourceSets {
        getByName("main") {
            java.srcDir(kernelBindings)
            jniLibs.srcDir(kernelLibs)
        }
        // Test doubles shared by unit tests and Compose/instrumented tests.
        getByName("test").java.srcDir("src/sharedTest/java")
        getByName("androidTest") {
            java.srcDir("src/sharedTest/java")
            // The same Finance conformance fixture the Rust, Python and JVM runners use.
            assets.srcDir(rootProject.file("../kernel/tests/conformance"))
        }
    }

    packaging {
        // Uncompressed, page-aligned native libraries (16 KB pages on Android 15+).
        jniLibs { useLegacyPackaging = false }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.all {
            // The manifest check reads the merged manifest (library permissions included), not just ours.
            it.systemProperty(
                "reva.mergedManifest",
                layout.buildDirectory.file("intermediates/merged_manifest/debug/processDebugMainManifest/AndroidManifest.xml")
                    .get().asFile.absolutePath,
            )
            it.systemProperty("reva.sourceManifest", file("src/main/AndroidManifest.xml").absolutePath)
            it.systemProperty("reva.resDir", file("src/main/res").absolutePath)
            it.systemProperty("reva.fixtures", rootProject.file("../tests/fixtures").absolutePath)
            it.systemProperty("reva.contracts", rootProject.file("../contracts").absolutePath)
            it.systemProperty("reva.avatarFixtures", rootProject.file("../avatar/test/fixtures").absolutePath)
            it.systemProperty("reva.uiTestsBuild", providers.gradleProperty("reva.uiTests").isPresent.toString())
            it.dependsOn("processDebugMainManifest")
        }
    }
}

// Files the app carries that are built or shared elsewhere in the repo: the avatar page (avatar/dist, built by
// `npm run build`; absent in unit-test lanes, where the Talk screen shows no avatar) and the mood rules, the same
// contracts/mood-rules.v1.json the PC reads.
val stageRevaAssets = tasks.register<Copy>("stageRevaAssets") {
    from(rootProject.file("../avatar/dist")) {
        into("avatar")
        include("index.html", "avatar.js", "placeholder.vrm")
    }
    from(rootProject.file("../contracts")) {
        into("contracts")
        include("mood-rules.v1.json", "capability-registry.v2.json")
    }
    into(layout.buildDirectory.dir("generated/revaAssets"))
}
android.sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/revaAssets"))
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach { dependsOn(stageRevaAssets) }

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.text)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.kotlinx.coroutines.android)
    // QR scan for pairing: CameraX (Apache-2.0) shows the preview, ZXing core (Apache-2.0, plain Java, no Google
    // Play services) decodes frames on the device. See docs/architecture/android-sync.md.
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)
    implementation(libs.zxing.core)
    // WebViewAssetLoader serves the avatar page and model from the APK without file:// access.
    implementation(libs.androidx.webkit)
    // Health Connect (Apache-2.0): READ-ONLY daily steps and heart-rate aggregates, asked for per data type. No write
    // permission is declared or requested; see docs/android/health-connect.md.
    implementation(libs.androidx.health.connect)
    // Health Connect already brings Guava (Apache-2.0) at runtime; that replaces CameraX's ListenableFuture-only artifact
    // with an empty stub, so the same Guava version is declared here for compilation too. Nothing new is packaged.
    implementation(libs.guava)
    // UniFFI's Kotlin binding loads libreva_kernel.so through JNA; the AAR carries JNA's own native stub.
    implementation("net.java.dev.jna:jna:${libs.versions.jna.get()}@aar")

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation("org.json:json:20250517")
    testImplementation("net.java.dev.jna:jna:${libs.versions.jna.get()}") // class definitions only; no native load in unit tests

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.rules)
    // Compose tests need this empty exported activity in the debug manifest. It is added only for test runs
    // (-Preva.uiTests=true) so the APK you sideload does not carry it.
    if (providers.gradleProperty("reva.uiTests").isPresent) {
        debugImplementation(libs.androidx.compose.ui.test.manifest)
    }
}
