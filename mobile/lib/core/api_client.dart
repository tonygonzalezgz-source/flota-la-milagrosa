import 'package:dio/dio.dart';

import 'config.dart';

/// Error de la API con el mensaje que devuelve el backend en `{"error": ...}`.
class ApiException implements Exception {
  final String message;
  final int? statusCode;
  ApiException(this.message, [this.statusCode]);

  bool get noAutorizado => statusCode == 401;

  @override
  String toString() => message;
}

/// Cliente HTTP único de la app. Agrega el token JWT en cada petición y
/// traduce los errores del backend a [ApiException] con su mensaje en español.
class ApiClient {
  final Dio _dio;
  String? _token;

  /// Se invoca cuando el backend responde 401 (token vencido o inválido).
  void Function()? onUnauthorized;

  ApiClient({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: AppConfig.apiBase,
              connectTimeout: const Duration(seconds: 15),
              receiveTimeout: const Duration(seconds: 45),
              // Las fotos van en base64 dentro del JSON: el envío puede tardar
              // con señal móvil débil.
              sendTimeout: const Duration(seconds: 90),
              contentType: Headers.jsonContentType,
            )) {
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        if (_token != null) {
          options.headers['Authorization'] = 'Bearer $_token';
        }
        handler.next(options);
      },
    ));
  }

  set token(String? value) => _token = value;
  bool get tieneToken => _token != null;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _run(() => _dio.get(path, queryParameters: _limpiar(query)));

  Future<dynamic> post(String path, {Object? body}) =>
      _run(() => _dio.post(path, data: body));

  Future<dynamic> put(String path, {Object? body}) =>
      _run(() => _dio.put(path, data: body));

  Future<dynamic> delete(String path) => _run(() => _dio.delete(path));

  Map<String, dynamic>? _limpiar(Map<String, dynamic>? q) {
    if (q == null) return null;
    final out = <String, dynamic>{};
    q.forEach((k, v) {
      if (v != null && v.toString().isNotEmpty) out[k] = v;
    });
    return out;
  }

  Future<dynamic> _run(Future<Response<dynamic>> Function() call) async {
    try {
      final res = await call();
      return res.data;
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401) onUnauthorized?.call();
      throw ApiException(_mensaje(e), status);
    }
  }

  String _mensaje(DioException e) {
    final data = e.response?.data;
    if (data is Map && data['error'] is String) return data['error'] as String;
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'La conexión tardó demasiado. Revisa tu señal e intenta de nuevo.';
      case DioExceptionType.connectionError:
        return 'Sin conexión con el servidor. Revisa tu internet.';
      default:
        final s = e.response?.statusCode;
        return s != null ? 'Error del servidor ($s)' : 'Error de red';
    }
  }
}
