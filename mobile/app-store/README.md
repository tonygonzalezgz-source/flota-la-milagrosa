# Material para la ficha de la App Store

## Capturas (`capturas/`)

Siete capturas en dos tamaños:

- `capturas/` — **1320 × 2868 px**, iPhone 6,9" (iPhone 17 Pro Max).
- `capturas-6-3/` — **1206 × 2622 px**, iPhone 6,3" (iPhone 16 Pro), que es el
  tamaño que pide el espacio "iPhone con Dynamic Island (pantalla mediana)" de
  la ficha; las de 6,9" las rechaza ahí por dimensiones. Salen de las otras con
  `sips -z 2622 1206`.

- `capturas-ipad/` — **2064 × 2752 px**, iPad de 13" (iPad Pro 13"). Apple las
  exige mientras el `Info.plist` declare compatibilidad con iPad, y las usa
  para todos los tamaños de iPad. Se tomaron en el simulador del iPad Pro 13".

Se pueden subir hasta 10 por tamaño.

| Archivo | Pantalla | Para qué sirve |
|---|---|---|
| `00-login.png` | Ingreso | Marca y "Conexión cifrada con buscontrol.net" |
| `01-mis-buses.png` | Mis Buses | Recaudo de la semana, pasajeros, vueltas, IPK y las últimas 8 semanas |
| `02-mis-vehiculos.png` | Mis Buses (abajo) | Avisos de SOAT y tecnomecánica, y la lista de buses |
| `03-detalle-bus.png` | Detalle del bus | Recaudo del día, conductor, ruta e indicadores |
| `04-liquidacion.png` | Liquidación | La tirilla del día: registradora, producido, gastos y por entregar |
| `05-gastos.png` | Gastos y Facturas | Historial de gastos con comprobante |
| `06-reportes.png` | Reportes | Recaudo del periodo, días trabajados y rendimiento por bus |

Todas salen de la **cuenta demo** (empresa, buses y conductores inventados,
`api/demo_semilla.py`), así que no muestran datos reales de ninguna empresa.
Se tomaron en el simulador de iOS con la barra de estado fija en 9:41 y la
señal completa (`xcrun simctl status_bar … override`).

Falta una captura del **mapa en vivo**: necesita la clave de Google Maps para
iOS, que todavía no existe. Sin clave el mapa sale gris.

### Cómo volver a tomarlas

```bash
# 1. API local con los datos de la demo (puerto libre, p. ej. 8011)
PORT=8011 DEMO_USUARIO=demo DEMO_CLAVE=<clave de prueba local> \
  SECRET_KEY=desarrollo-local python3 api/dev_server.py

# 2. App del simulador apuntando ahí
cd mobile && flutter build ios --simulator --debug \
  --dart-define=API_URL=http://localhost:8011 --dart-define=APP_BUILD=0

# 3. Simulador: instalar, barra de estado limpia y capturar
UDID=$(xcrun simctl list devices available | grep "iPhone 17 Pro Max" | grep -o "[0-9A-F-]\{36\}")
xcrun simctl install  $UDID build/ios/iphonesimulator/Runner.app
xcrun simctl launch   $UDID net.buscontrol.app
xcrun simctl status_bar $UDID override --time "9:41" --batteryState charged \
  --batteryLevel 100 --cellularBars 4 --wifiBars 3 --dataNetwork wifi
xcrun simctl io $UDID screenshot app-store/capturas/01-mis-buses.png
```

La captura del login se toma con la app compilada **sin** `API_URL`, para que
diga "buscontrol.net" y no "localhost".

## Lo que falta para la ficha

- Texto: nombre, subtítulo, descripción y palabras clave.
- URL de soporte: `https://buscontrol.net/soporte`.
- URL de privacidad: `https://buscontrol.net/privacidad`.
- Etiquetas de privacidad: deben coincidir con `mobile/ios/Runner/PrivacyInfo.xcprivacy`.
- Notas para el revisor con la cuenta demo.
- Si se deja el soporte de iPad que declara `Info.plist`, hacen falta también
  capturas de iPad 13".
