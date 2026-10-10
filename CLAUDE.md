# BusControl — memoria del proyecto

Plataforma de gestión de flota de Flota La Milagrosa: web (HTML por módulo +
API Flask en `api/app.py`, desplegada en Vercel en https://buscontrol.net) y app
móvil Flutter en `mobile/` (detalle técnico en `mobile/README.md`). La app usa la
misma API; los permisos salen de `ROLE_VIEWS` → `allowedViews`.

## Cómo trabajamos (reglas del usuario)

- Hablar en español, claro y sin tecnicismos innecesarios.
- **Nunca commit ni push sin aprobación explícita** ("súbelo", "dale", "ok",
  "aprobado"…). Los avisos automáticos del stop-hook no son aprobación. Si el
  usuario dice "aún no lo subas", esperar.
- Antes de pedir aprobación: implementar, validar (`flutter analyze`,
  `flutter test`, prueba de punta a punta con capturas) y mostrar el resultado.
- Avisar antes de agregar dependencias nuevas.
- Commits separados por tema, mensaje en español con prefijo (`feat:`, `fix:`…).
  Detectar la rama actual; nunca `push --force`, `reset --hard` ni `clean`.
- Después de subir cambios de `mobile/`: revisar el workflow "App móvil
  (Flutter)" y darle al usuario el enlace directo del artefacto `buscontrol-apk`
  (`github.com/tonygonzalezgz-source/flota-la-milagrosa/actions/runs/<run>/artifacts/<id>`).
  Si falla, leer el log, corregir, validar y pedir aprobación antes de resubir.
- Cambios en `api/` se despliegan con Vercel: decirlo al pedir aprobación.
- Proponer opciones visuales (mockups) antes de rediseñar, y que el usuario elija.

## Decisiones de la app móvil

- **Diseño:** login y apertura con estilo "Cabina Neón" (`widgets/marca.dart`);
  Mis Buses, Detalle del bus y Reportes con "Aurora Clara" (`widgets/aurora.dart`,
  paleta en `core/theme.dart`, que aplica a toda la app). Fuentes: Sora/DM Sans
  y Chakra Petch/Manrope (`assets/fonts`, licencia OFL).
- **Propietario:** entra a una barra inferior (Mis Buses · Mapa · Gastos · Más).
  Sin alertas de mantenimiento.
- **Dinero bruto = pasajeros × $3.900** (`tarifaPasaje` en `core/movilidad.dart`).
  IPK = pasajeros ÷ km. La comparación semanal usa los mismos días de la semana pasada.
- **Reportes del propietario** (`features/reportes`, `core/reportes.dart`):
  periodo y bus; días trabajados (con movilidad o despacho "trabajando"; taller
  y descanso salen del despacho); totales por bus, ruta y conductor; Excel con
  hojas Resumen, Detalle y Días. No lleva "compartir por WhatsApp": el usuario
  lo pidió quitar.
- **Asistente** (`features/chat`): mismo `/api/chat` de la web. Historial solo
  en el celular (almacenamiento seguro), caduca a la medianoche de Bogotá,
  máximo 40 mensajes guardados y 8 enviados al modelo. El servidor además corta
  en 10 mensajes de hasta 2.000 caracteres.
- **Mapa en vivo** (`features/monitoreo`): Google Maps nativo con la clave de
  `--dart-define=GOOGLE_MAPS_API_KEY`. En CI sale del secreto
  `GOOGLE_MAPS_API_KEY` de este repo. Sin clave usa Esri. Estilos Calles, Claro,
  Satélite y Oscuro, como la web. Selector de ruta como la web: con una ruta
  solo se ven sus buses despachados hoy, ida azul, regreso naranja punteado y
  puntos de control (estos solo con una ruta elegida).

## Seguridad de la API (ya aplicada)

- `_usuario_consultado()`: Propietario y Técnico Mant. siempre se filtran por
  el usuario del token, nunca por el `user_id` que mande la petición.
- Endpoints con `require_role` según las pantallas que los usan; el autor de
  los registros de mantenimiento sale de la sesión.
- `/api/despacho/historial`: el propietario lo ve solo con sus buses.

## Pendientes e ideas

- La rama `claude/clever-knuth-p6se92` aún no está fusionada a `main`, así que
  buscontrol.net todavía no tiene la seguridad ni los cambios del servidor.
- Verificar que `CRON_SECRET` exista en Vercel (protege `/api/cron/*`).
- Conductor: limitar despacho y alistamiento a su propio bus.
- Consumo de combustible por vuelta, cuando exista el valor del tanqueo del día.
- Mapa: flechas de sentido sobre el trazado.
- Firma release de Android para Play Store; luego restringir la clave de Maps
  por paquete (`co.lamilagrosa.buscontrol`) y SHA-1.
- El chatbot de la web no guarda historial.
- Excel directo a Descargas (hoy abre el menú de compartir).

## Entorno y pruebas (sesiones en la nube)

- Flutter: `export PATH=/opt/sdk/flutter/bin:$PATH`. No hay Android SDK aquí
  (dl.google.com bloqueado): el APK solo se arma en GitHub Actions.
- Backend local: `python3 api/setup_db.py && python3 api/dev_server.py`
  (puerto 8001, SQLite `api/flota.db`, ignorado por git; borrarlo al terminar).
  Usuarios de prueba en `api/setup_db.py`.
- App en el navegador: `flutter build web --dart-define=API_URL=http://localhost:8001
  --no-web-resources-cdn`, servir `mobile/build/web` con `python3 -m http.server 3040`
  y recorrer con Playwright (Chromium en `/opt/pw-browsers`).
- Las imágenes de los mapas (Google y Esri) están bloqueadas aquí: en las
  pruebas el fondo sale gris, pero rutas y buses sí se dibujan.
- Para detener servidores usar patrones anclados (`pkill -f "^python3 api/dev_server.py"`);
  sin `^` el patrón coincide con la propia shell y la mata.

## Errores ya resueltos (no repetir)

- Un comentario XML no puede contener `--` (rompió el AndroidManifest).
- En `build.gradle.kts`, `java.util…` choca con la extensión `java` de Gradle:
  importar `java.util.Base64` arriba.
- En Flutter, una `Row` con `Expanded(ColoredBox)` dentro de un `SizedBox` de
  alto fijo necesita `crossAxisAlignment: stretch` o queda de alto cero.
- `package:intl` también exporta `TextDirection`: importar `show DateFormat`
  donde se dibuja texto con `TextPainter`.
- No correr `dart format` sobre todo `lib/` (reformatea archivos ajenos al cambio).
