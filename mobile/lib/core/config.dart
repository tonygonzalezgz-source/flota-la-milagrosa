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

  /// Base de todos los endpoints: `<apiUrl>/api`.
  static String get apiBase {
    final base = apiUrl.endsWith('/') ? apiUrl.substring(0, apiUrl.length - 1) : apiUrl;
    return '$base/api';
  }
}
