import java.io.FileInputStream
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Valores de --dart-define (Flutter los pasa en base64 separados por comas).
// La clave de Google Maps llega así, no se guarda en el repositorio.
val dartDefines: Map<String, String> =
    (project.findProperty("dart-defines") as String?)
        ?.split(",")
        ?.mapNotNull { def ->
            val par = String(Base64.getDecoder().decode(def)).split("=", limit = 2)
            if (par.size == 2) par[0] to par[1] else null
        }
        ?.toMap()
        ?: emptyMap()

// Firma de subida a Google Play. En GitHub Actions llega por variables de
// entorno (secretos del repo); en un computador, por android/key.properties
// (ignorado por git). Sin ninguna de las dos, release se firma con la clave
// debug: sirve para instalar el APK de prueba, no para la Play Store.
val firmaLocal = Properties().apply {
    val archivo = rootProject.file("key.properties")
    if (archivo.exists()) FileInputStream(archivo).use { load(it) }
}
fun datoFirma(propiedad: String, variable: String): String? =
    firmaLocal.getProperty(propiedad) ?: System.getenv(variable)?.takeIf { it.isNotBlank() }
val almacenFirma = datoFirma("storeFile", "ANDROID_KEYSTORE_PATH")
val hayFirmaPropia = almacenFirma != null && file(almacenFirma).exists()

android {
    namespace = "net.buscontrol.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Identificador en Google Play: no se puede cambiar después de publicar.
        applicationId = "net.buscontrol.app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // Mapa en vivo con Google Maps (sin clave, la app usa el mapa alterno de Esri).
        manifestPlaceholders["googleMapsKey"] = dartDefines["GOOGLE_MAPS_API_KEY"] ?: ""
    }

    signingConfigs {
        if (hayFirmaPropia) {
            create("subida") {
                storeFile = file(almacenFirma!!)
                storePassword = datoFirma("storePassword", "ANDROID_KEYSTORE_PASSWORD")
                keyAlias = datoFirma("keyAlias", "ANDROID_KEY_ALIAS")
                keyPassword = datoFirma("keyPassword", "ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName(if (hayFirmaPropia) "subida" else "debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
