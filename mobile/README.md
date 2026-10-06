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

- Flutter 3.47 o superior (`flutter --version`)
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
# Android (para Play Store se necesita firmar: ver android/app/build.gradle.kts)
flutter build appbundle
flutter build apk          # APK para instalar directo en un celular

# iOS (requiere Mac + cuenta Apple Developer)
flutter build ipa
```

El workflow `.github/workflows/mobile.yml` corre el análisis y las pruebas en
cada cambio dentro de `mobile/` y deja un **APK de prueba descargable** en la
pestaña *Actions* de GitHub.

## Notas

- Las fotos se reducen a 1600 px y JPEG calidad 70 (igual que la web) y viajan
  en base64 dentro del JSON, como espera el backend.
- La firma de Disp. Tecnológicos se envía como PNG con fondo blanco.
- En Android, el tráfico `http://` (sin TLS) solo se permite en compilaciones
  debug, para probar contra el API local.
