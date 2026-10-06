import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/alistamiento/alistamiento_screen.dart';
import '../features/auth/login_screen.dart';
import '../features/auth/splash_screen.dart';
import '../features/auth/tratamiento_screen.dart';
import '../features/chequeo/chequeo_screen.dart';
import '../features/despacho/despacho_screen.dart';
import '../features/eds/eds_screen.dart';
import '../features/gastos/gastos_screen.dart';
import '../features/home/home_screen.dart';
import '../features/lavada/lavada_screen.dart';
import '../features/monitoreo/mapa_vivo_screen.dart';
import '../features/propietario/propietario_screen.dart';
import '../features/tecnologia/tecnologia_screen.dart';
import 'modulos.dart';
import 'session.dart';

final routerProvider = Provider<GoRouter>((ref) {
  // Avisa al router cada vez que cambia la sesión para re-evaluar `redirect`.
  final refresh = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refresh.value++);
  ref.listen(introTerminadaProvider, (_, _) => refresh.value++);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: refresh,
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final loc = state.matchedLocation;
      // La intro de apertura se ve completa aunque la sesión cargue antes.
      if (session.isLoading || !ref.read(introTerminadaProvider)) {
        return loc == '/splash' ? null : '/splash';
      }
      final user = session.value;
      if (user == null) return loc == '/login' ? null : '/login';
      if (user.debeAceptarTratamiento) {
        return loc == '/tratamiento' ? null : '/tratamiento';
      }
      if (loc == '/splash' || loc == '/login' || loc == '/tratamiento') return '/';
      if (!puedeAbrir(user.allowedViews, loc)) return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/splash', pageBuilder: (_, s) => _fundido(s, const SplashScreen())),
      GoRoute(path: '/login', pageBuilder: (_, s) => _fundido(s, const LoginScreen())),
      GoRoute(path: '/tratamiento', pageBuilder: (_, s) => _fundido(s, const TratamientoScreen())),
      GoRoute(path: '/', pageBuilder: (_, s) => _fundido(s, const HomeScreen())),
      GoRoute(path: '/despacho', builder: (_, _) => const DespachoScreen()),
      GoRoute(path: '/alistamiento', builder: (_, _) => const AlistamientoScreen()),
      GoRoute(path: '/chequeo', builder: (_, _) => const ChequeoScreen()),
      GoRoute(path: '/mapa-vivo', builder: (_, _) => const MapaVivoScreen()),
      GoRoute(path: '/propietario', builder: (_, _) => const PropietarioScreen()),
      GoRoute(path: '/gastos', builder: (_, _) => const GastosScreen()),
      GoRoute(path: '/tecnologia', builder: (_, _) => const TecnologiaScreen()),
      GoRoute(path: '/eds', builder: (_, _) => const EdsScreen()),
      GoRoute(path: '/lavada', builder: (_, _) => const LavadaScreen()),
    ],
  );
});

/// Transición de fundido para el paso splash → login → inicio (en vez del
/// deslizamiento lateral, que se ve brusco al salir de la intro).
CustomTransitionPage<void> _fundido(GoRouterState state, Widget child) => CustomTransitionPage(
      key: state.pageKey,
      child: child,
      transitionDuration: const Duration(milliseconds: 450),
      transitionsBuilder: (_, animation, _, child) =>
          FadeTransition(opacity: CurvedAnimation(parent: animation, curve: Curves.easeOut), child: child),
    );
