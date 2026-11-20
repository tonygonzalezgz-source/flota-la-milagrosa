# BusControl — App móvil (Flutter)

App Android / iOS de BusControl. Usa **la misma API Flask** que la web
(`/api/*` en Vercel); no tiene backend propio ni lógica de permisos aparte:
el menú de cada usuario sale de `allowedViews` (`ROLE_VIEWS` en `api/app.py`).

## Módulos

| Fase | Módulo | Roles | Pantalla |
|---|---|---|---|
| 1 | Despacho (+ alistamiento por bus) | Administrador, Despachador, Jefe de Ruta, Analista | `features/despacho` |
| 1 | Alistamiento (30 ítems oficiales) | Conductor, Analista, Jefe de Ruta | `features/alistamiento` |
| 1 | Chequeo con GPS | Despachador, Jefe de Ruta, Administrador | `features/chequeo` |
| 1 | Mapa en vivo | Administrador, Despachador, Jefe de Ruta, Propietario | `features/monitoreo` |
| 1 | Mis Buses | Propietario, Administrador | `features/propietario` |
| 1 | Gastos y Facturas | Propietario, Administrador | `features/gastos` |
| 1 | Disp. Tecnológicos (fotos + firma) | Técnico Cámaras, Jefe Op. Tecnológicas, Administrador; Propietario y Analista en lectura | `features/tecnologia` |
| 1 | Operador EDS | Operador EDS, Administrador | `features/eds` |
| 1 | Lavada Primeriada | Operador Lavada, Administrador, Propietario (lectura) | `features/lavada` |
| 2 | Dashboard, historiales, mantenimiento, catálogo, config GPS… | — | Por ahora solo web (la app los lista como "Disponibles en la versión web") |

## Estructura

```
lib/
  main.dart              arranque, tema y localización es_CO
  core/
    config.dart          URL del backend (--dart-define=API_URL)
    api_client.dart      Dio + token JWT + errores del backend en español
    session.dart         login, sesión guardada (Keychain/Keystore), aviso Ley 1581
    router.dart          rutas y redirecciones por sesión/rol
    modulos.dart         catálogo de módulos ↔ vistas del backend
    fechas.dart          fecha de Bogotá (UTC-5), igual que hoy_bogota() del backend
    gps.dart             permisos y lectura de ubicación
    modelos.dart         lectura tolerante del JSON (SQLite/Postgres), formato de pesos
  widgets/               componentes compartidos (fotos, historial, selectores)
  features/<modulo>/     una carpeta por módulo
test/                    pruebas unitarias
```

## Requisitos

- Flutter 3.50 o superior (`flutter --version`); la versión fija de CI es 3.50.1
- Android: Android Studio con un emulador o un celular con depuración USB
- iOS: una Mac con Xcode (o compilar en la nube, ver más abajo)

## Correr en desarrollo

```bash
cd mobile
flutter pub get

# Contra producción (https://buscontrol.net):
flutter run

# Contra el API local (python3 api/dev_server.py en el puerto 8001).
# En un celular físico usa la IP de tu computador en la red, no "localhost";
# en el emulador de Android la máquina anfitriona es 10.0.2.2.
flutter run --dart-define=API_URL=http://192.168.1.10:8001

# Vista rápida en el navegador (sin cámara nativa ni firma de apps):
flutter run -d chrome --dart-define=API_URL=http://localhost:8001
```

## Pruebas

```bash
flutter analyze
flutter test
```

## Compilar para publicar

```bash
# Android para Play Store: firmado con la clave de subida si existe
# android/key.properties (ver android/app/build.gradle.kts); si no, con la debug.
flutter build appbundle
flutter build apk          # APK para instalar directo en un celular

# iOS (requiere Mac + cuenta Apple Developer)
flutter build ipa
```

El workflow `.github/workflows/mobile.yml` corre el análisis y las pruebas en
cada cambio dentro de `mobile/` y deja en la pestaña *Actions* de GitHub un
**APK de prueba** (`buscontrol-apk`) y el **AAB firmado para Google Play**
(`buscontrol-aab`). La firma sale de los secretos `ANDROID_KEYSTORE_BASE64`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` y `ANDROID_KEY_PASSWORD`; el
número de compilación es el de la ejecución del workflow.

Paquete: `net.buscontrol.app` (Android) / bundle id igual en iOS. El ícono
sale del logo de BusControl; el de 512×512 para la ficha está en `play-store/`.

## Publicar en la App Store (iOS)

El proyecto de Xcode (`ios/`) ya está listo: bundle id `net.buscontrol.app`,
los íconos, la pantalla de carga con el logo, los textos de permiso de cámara,
fotos y ubicación en español, la clave de Google Maps que llega por
`--dart-define` (`Runner/AppDelegate.swift`), el manifiesto de privacidad que
exige Apple (`Runner/PrivacyInfo.xcprivacy`) y la exención del cuestionario de
exportación (`ITSAppUsesNonExemptEncryption` en `Info.plist`).

Compilar y subir, desde la Mac (GitHub Actions corre en Linux y no puede
compilar iOS):

```bash
cd mobile
flutter build ipa \
  --dart-define=GOOGLE_MAPS_API_KEY=… \
  --dart-define=APP_BUILD=<número de compilación> \
  --dart-define=APP_STORE_ID=<id que da App Store Connect> \
  --build-number=<el mismo APP_BUILD>
# luego: abrir build/ios/archive/Runner.xcarchive en Xcode → Distribute App
```

> En el Mac del usuario el repo vive en `~/Documents` (iCloud), y `codesign`
> rechaza las carpetas con `com.apple.FinderInfo` ("resource fork, Finder
> information, or similar detritus not allowed"). Por eso `mobile/build` es un
> enlace a `~/Library/Caches/buscontrol-ios-build`; si se borra, hay que volver
> a crearlo (`ln -s ~/Library/Caches/buscontrol-ios-build build`) o archivar
> desde Xcode, que usa DerivedData y no falla.

Variables del servidor (Vercel) para iOS:

- `APP_VERSION_MINIMA_IOS`: compilación más antigua que puede seguir usándose
  en iPhone. Va aparte de `APP_VERSION_MINIMA` (Android) porque cada tienda
  numera sus compilaciones por su lado; sin la variable, en iPhone no se
  obliga a nadie a actualizar.

Falta por fuera del código:

1. **Apple Developer Program** (99 USD/año). Como empresa piden el número
   D-U-N-S y la verificación tarda semanas; como persona sale en 1–2 días,
   pero el nombre del vendedor es el de la persona.
2. **Ficha en App Store Connect**: nombre, descripción, categoría, precio,
   capturas de iPhone 6.9" y 6.5" (y de iPad 13" si se deja el soporte de
   iPad que hoy declara `Info.plist`), URL de privacidad
   (`https://buscontrol.net/privacidad`) y **URL de soporte** (falta crearla).
3. **Etiquetas de privacidad** de App Store Connect: deben coincidir con
   `PrivacyInfo.xcprivacy` (usuario, nombre, ubicación precisa, fotos y datos
   de operación; nada de rastreo).
4. **Notas para el revisor** con la cuenta demo (`DEMO_USUARIO` /
   `DEMO_CLAVE` de Vercel): Apple rechaza toda app con login que no traiga
   credenciales de prueba.
5. **Clave de Google Maps propia para iOS**, restringida por bundle id (la de
   Android se restringe por paquete + SHA-1).
6. **Riesgo a tener presente**: la guía 4.2 de Apple se usa para rechazar apps
   que solo sirven a los empleados de una empresa; hay que presentar
   BusControl como producto multicliente y dejar que el revisor entre con la
   demo. La alternativa es distribuirla como app personalizada (Apple Business
   Manager).

## Notas

- Las fotos se reducen a 1600 px y JPEG calidad 70 (igual que la web) y viajan
  en base64 dentro del JSON, como espera el backend.
- La firma de Disp. Tecnológicos se envía como PNG con fondo blanco.
- En Android, el tráfico `http://` (sin TLS) solo se permite en compilaciones
  debug, para probar contra el API local.
