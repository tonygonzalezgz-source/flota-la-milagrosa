import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';

/// Usuario autenticado, tal como lo devuelven `/api/login` y `/api/me`.
class Usuario {
  final int id;
  final String username;
  final String nombre;
  final String rol;
  final String iniciales;
  final String? color;
  final List<String> allowedViews;
  final List<int> busIds;
  final bool tratamientoAceptado;

  const Usuario({
    required this.id,
    required this.username,
    required this.nombre,
    required this.rol,
    required this.iniciales,
    this.color,
    required this.allowedViews,
    required this.busIds,
    required this.tratamientoAceptado,
  });

  bool get esAdmin => rol == 'Administrador';
  bool get esPropietario => rol == 'Propietario';

  /// El aviso de la Ley 1581 solo se pide a los propietarios (igual que la web).
  bool get debeAceptarTratamiento => esPropietario && !tratamientoAceptado;

  factory Usuario.fromJson(Map<String, dynamic> j) => Usuario(
        id: j['id'] as int,
        username: (j['username'] ?? '') as String,
        nombre: (j['nombre'] ?? '') as String,
        rol: (j['rol'] ?? '') as String,
        iniciales: (j['iniciales'] ?? '') as String,
        color: j['color'] as String?,
        allowedViews: ((j['allowedViews'] ?? const []) as List).cast<String>(),
        busIds: ((j['bus_ids'] ?? const []) as List).cast<int>(),
        tratamientoAceptado: j['tratamiento_aceptado'] == true,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'username': username,
        'nombre': nombre,
        'rol': rol,
        'iniciales': iniciales,
        'color': color,
        'allowedViews': allowedViews,
        'bus_ids': busIds,
        'tratamiento_aceptado': tratamientoAceptado,
      };

  Usuario copyWith({bool? tratamientoAceptado, List<String>? allowedViews}) => Usuario(
        id: id,
        username: username,
        nombre: nombre,
        rol: rol,
        iniciales: iniciales,
        color: color,
        allowedViews: allowedViews ?? this.allowedViews,
        busIds: busIds,
        tratamientoAceptado: tratamientoAceptado ?? this.tratamientoAceptado,
      );
}

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

final secureStorageProvider =
    Provider<FlutterSecureStorage>((ref) => const FlutterSecureStorage());

final sessionProvider =
    AsyncNotifierProvider<SessionController, Usuario?>(SessionController.new);

/// Maneja login, restauración de sesión al abrir la app y cierre de sesión.
/// El token se guarda en el almacenamiento seguro del sistema
/// (Keychain en iOS, Keystore en Android).
class SessionController extends AsyncNotifier<Usuario?> {
  static const _kToken = 'authToken';
  static const _kUser = 'currentUser';

  ApiClient get _api => ref.read(apiClientProvider);
  FlutterSecureStorage get _storage => ref.read(secureStorageProvider);

  @override
  Future<Usuario?> build() async {
    _api.onUnauthorized = () {
      // Token vencido: se cierra la sesión en todas las pantallas.
      if (state.value != null) logout();
    };

    final token = await _storage.read(key: _kToken);
    if (token == null) return null;
    _api.token = token;

    final cache = await _storage.read(key: _kUser);
    Usuario? guardado;
    if (cache != null) {
      try {
        guardado = Usuario.fromJson(jsonDecode(cache) as Map<String, dynamic>);
      } catch (_) {}
    }

    try {
      final me = await _api.get('/me') as Map<String, dynamic>;
      // /me no trae bus_ids: se conservan los del login.
      me['bus_ids'] = guardado?.busIds ?? const <int>[];
      final u = Usuario.fromJson(me);
      await _storage.write(key: _kUser, value: jsonEncode(u.toJson()));
      return u;
    } on ApiException catch (e) {
      if (e.noAutorizado || e.statusCode == 404) {
        await _limpiar();
        return null;
      }
      // Sin red: se abre con el usuario guardado para no bloquear al operador.
      return guardado;
    }
  }

  Future<void> login(String username, String password) async {
    final data = await _api.post('/login', body: {
      'username': username.trim().toLowerCase(),
      'password': password,
    }) as Map<String, dynamic>;
    final token = data['token'] as String;
    final u = Usuario.fromJson(data);
    _api.token = token;
    await _storage.write(key: _kToken, value: token);
    await _storage.write(key: _kUser, value: jsonEncode(u.toJson()));
    state = AsyncData(u);
  }

  Future<void> aceptarTratamiento() async {
    await _api.post('/tratamiento-datos/aceptar');
    final u = state.value;
    if (u == null) return;
    final nuevo = u.copyWith(tratamientoAceptado: true);
    await _storage.write(key: _kUser, value: jsonEncode(nuevo.toJson()));
    state = AsyncData(nuevo);
  }

  Future<void> logout() async {
    await _limpiar();
    state = const AsyncData(null);
  }

  Future<void> _limpiar() async {
    _api.token = null;
    await _storage.delete(key: _kToken);
    await _storage.delete(key: _kUser);
  }
}
