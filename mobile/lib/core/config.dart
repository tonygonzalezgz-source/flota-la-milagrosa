/// Configuración de compilación de la app.
///
/// La URL del backend se fija al compilar:
///   flutter run --dart-define=API_URL=http://192.168.1.10:8001
/// Sin la variable se usa producción (buscontrol.net).
class AppConfig {
  static const String apiUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: 'https://buscontrol.net',
  );

  /// Clave de Google Maps para el mapa en vivo (Android/iOS), igual que la web:
  ///   flutter build apk --dart-define=GOOGLE_MAPS_API_KEY=…
  /// Sin clave se usa el mapa alterno de Esri.
  static const String googleMapsKey = String.fromEnvironment('GOOGLE_MAPS_API_KEY');

  /// Número de compilación (en CI, el número de ejecución del workflow, el
  /// mismo versionCode de Android). 0 en desarrollo: nunca pide actualizar.
  static const int compilacion = int.fromEnvironment('APP_BUILD');

  /// Política de privacidad pública (la misma que se declara en Google Play).
  static const String urlPrivacidad = 'https://buscontrol.net/privacidad';

  /// Ficha de la app en Google Play (para el aviso de actualizar).
  static const String urlPlayStore = 'https://play.google.com/store/apps/details?id=net.buscontrol.app';

  /// Base de todos los endpoints: `<apiUrl>/api`.
  static String get apiBase {
    final base = apiUrl.endsWith('/') ? apiUrl.substring(0, apiUrl.length - 1) : apiUrl;
    return '$base/api';
  }
}
