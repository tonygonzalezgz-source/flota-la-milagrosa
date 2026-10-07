import 'dart:convert';

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

  /// POST cuya respuesta llega por partes como Server-Sent Events
  /// (`data: {...}`), p. ej. el asistente `/api/chat`. Entrega cada evento
  /// apenas llega, así la respuesta se va viendo mientras se escribe.
  Stream<Map<String, dynamic>> postEventos(String path, {Object? body}) async* {
    try {
      final res = await _dio.post<ResponseBody>(
        path,
        data: body,
        // El modelo puede pensar o consultar la BD un rato antes del primer dato.
        options: Options(responseType: ResponseType.stream, receiveTimeout: const Duration(seconds: 90)),
      );
      yield* eventosSse(res.data!.stream.cast<List<int>>().transform(utf8.decoder));
    } on DioException catch (e) {
      final status = e.response?.statusCode;
      if (status == 401) onUnauthorized?.call();
      throw ApiException(await _mensajeStream(e), status);
    }
  }

  /// Con `ResponseType.stream` el cuerpo del error también llega como stream.
  Future<String> _mensajeStream(DioException e) async {
    final data = e.response?.data;
    if (data is ResponseBody) {
      try {
        final texto = await data.stream.cast<List<int>>().transform(utf8.decoder).join();
        final j = jsonDecode(texto);
        if (j is Map && j['error'] is String) return j['error'] as String;
      } catch (_) {}
    }
    return _mensaje(e);
  }

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

/// Convierte texto Server-Sent Events en sus eventos JSON. Los trozos pueden
/// cortar un evento por la mitad: se acumula hasta la línea en blanco que lo
/// cierra.
Stream<Map<String, dynamic>> eventosSse(Stream<String> trozos) async* {
  var buf = '';
  await for (final t in trozos) {
    buf += t.replaceAll('\r\n', '\n');
    int fin;
    while ((fin = buf.indexOf('\n\n')) >= 0) {
      final bloque = buf.substring(0, fin);
      buf = buf.substring(fin + 2);
      for (final linea in bloque.split('\n')) {
        if (!linea.startsWith('data:')) continue;
        try {
          final ev = jsonDecode(linea.substring(5).trim());
          if (ev is Map<String, dynamic>) yield ev;
        } catch (_) {
          // Un evento malformado no corta la conversación.
        }
      }
    }
  }
}
