import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config.dart';
import 'session.dart';

/// true si el servidor exige una versión más nueva que la instalada
/// (`/api/app/version` → `minima`, que se fija con APP_VERSION_MINIMA en
/// Vercel). Sin conexión o en desarrollo no bloquea: mejor dejar entrar que
/// dejar a alguien por fuera por un error de red.
final actualizacionObligatoriaProvider = FutureProvider<bool>((ref) async {
  if (AppConfig.compilacion <= 0) return false;
  try {
    final r = await ref.read(apiClientProvider).get('/app/version');
    return requiereActualizar(AppConfig.compilacion, r is Map ? r['minima'] : null);
  } catch (_) {
    return false;
  }
});

bool requiereActualizar(int instalada, Object? minima) {
  final m = minima is int ? minima : int.tryParse('$minima') ?? 0;
  return instalada > 0 && m > instalada;
}
