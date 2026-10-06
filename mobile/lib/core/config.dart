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

  /// Base de todos los endpoints: `<apiUrl>/api`.
  static String get apiBase {
    final base = apiUrl.endsWith('/') ? apiUrl.substring(0, apiUrl.length - 1) : apiUrl;
    return '$base/api';
  }
}
