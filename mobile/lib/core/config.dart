import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform;

/// Configuración de compilación de la app.
///
/// La URL del backend se fija al compilar:
///   flutter run --dart-define=API_URL=http://192.168.1.10:8001
/// Sin la variable se usa producción (buscontrol.net).
class AppConfig {
  static const String apiUrl = String.fromEnvironment('API_URL', defaultValue: 'https://buscontrol.net');

  /// Clave de Google Maps para el mapa en vivo (Android/iOS), igual que la web:
  ///   flutter build apk --dart-define=GOOGLE_MAPS_API_KEY=…
  /// Sin clave se usa el mapa alterno de Esri.
  static const String googleMapsKey = String.fromEnvironment('GOOGLE_MAPS_API_KEY');

  /// Número de compilación (en CI, el número de ejecución del workflow, el
  /// mismo versionCode de Android y el build number de iOS). 0 en desarrollo:
  /// nunca pide actualizar.
  static const int compilacion = int.fromEnvironment('APP_BUILD');

  /// Id numérico de la app en la App Store, que Apple asigna al crear la ficha
  /// en App Store Connect:
  ///   flutter build ipa --dart-define=APP_STORE_ID=1234567890
  /// Sin él, el aviso de actualizar no muestra el botón a la tienda.
  static const String appStoreId = String.fromEnvironment('APP_STORE_ID');

  /// Política de privacidad pública (la misma que se declara en Google Play).
  static const String urlPrivacidad = 'https://buscontrol.net/privacidad';

  /// Ficha de la app en Google Play (para el aviso de actualizar).
  static const String urlPlayStore = 'https://play.google.com/store/apps/details?id=net.buscontrol.app';

  static bool get esIOS => defaultTargetPlatform == TargetPlatform.iOS;

  /// Plataforma que se le informa al servidor: la versión mínima se fija por
  /// tienda, porque los números de compilación de cada una van por su lado.
  static String get plataforma => esIOS ? 'ios' : 'android';

  /// Nombre de la tienda del celular, para los avisos de la app.
  static String get nombreTienda => esIOS ? 'App Store' : 'Play Store';

  /// Ficha de la app en la tienda del celular. En iOS queda vacía mientras no
  /// se compile con APP_STORE_ID (Apple lo da al crear la ficha).
  static String get urlTienda =>
      esIOS ? (appStoreId.isEmpty ? '' : 'https://apps.apple.com/app/id$appStoreId') : urlPlayStore;

  /// Base de todos los endpoints: `<apiUrl>/api`.
  static String get apiBase {
    final base = apiUrl.endsWith('/') ? apiUrl.substring(0, apiUrl.length - 1) : apiUrl;
    return '$base/api';
  }
}
