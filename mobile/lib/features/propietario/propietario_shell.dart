import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/modulos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../features/gastos/gastos_screen.dart';
import '../../features/monitoreo/mapa_vivo_screen.dart';
import '../../widgets/aurora.dart';
import '../../widgets/comunes.dart';
import 'propietario_screen.dart';

class _Pestana {
  final String clave;
  final String titulo;
  final IconData icono;
  final Widget Function() pantalla;
  const _Pestana(this.clave, this.titulo, this.icono, this.pantalla);
}

/// Inicio del propietario (estilo Aurora Clara): barra inferior flotante con
/// Mis Buses, Mapa y Gastos; el resto de sus módulos queda en "Más". Las
/// pestañas salen de `allowedViews`, igual que el menú general.
class PropietarioShell extends ConsumerStatefulWidget {
  const PropietarioShell({super.key});

  @override
  ConsumerState<PropietarioShell> createState() => _PropietarioShellState();
}

class _PropietarioShellState extends ConsumerState<PropietarioShell> {
  static final _fijas = [
    _Pestana('propietario', 'Mis Buses', Icons.directions_bus_outlined, () => const PropietarioScreen()),
    _Pestana('mb-mapa', 'Mapa', Icons.map_outlined, () => const MapaVivoScreen()),
    _Pestana('gastos', 'Gastos', Icons.receipt_long_outlined, () => const GastosScreen()),
  ];

  int _actual = 0;

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(sessionProvider).value;
    if (user == null) return const SizedBox.shrink();
    final pestanas = [
      for (final p in _fijas)
        if (user.allowedViews.contains(p.clave)) p,
      _Pestana('mas', 'Más', Icons.more_horiz, () => const _MasScreen()),
    ];
    final actual = _actual.clamp(0, pestanas.length - 1);

    return PopScope(
      // "Atrás" en otra pestaña vuelve a Mis Buses antes de salir de la app.
      canPop: actual == 0,
      onPopInvokedWithResult: (hecho, _) {
        if (!hecho) setState(() => _actual = 0);
      },
      child: Scaffold(
        backgroundColor: AppColors.bgLight,
        // Mis Buses se mantiene viva para no recargarla en cada cambio; las
        // demás se crean al abrirlas (así el mapa deja de consultar al salir).
        body: IndexedStack(index: actual, children: [
          for (var i = 0; i < pestanas.length; i++)
            if (i == 0 || i == actual) pestanas[i].pantalla() else const SizedBox.shrink(),
        ]),
        bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(18, 6, 18, 12),
            child: Container(
              height: 66,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(999),
                boxShadow: const [BoxShadow(color: Color(0x2E0F1A33), blurRadius: 34, offset: Offset(0, 14))],
              ),
              child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                for (var i = 0; i < pestanas.length; i++)
                  _BotonPestana(
                    pestana: pestanas[i],
                    activa: i == actual,
                    onTap: () => setState(() => _actual = i),
                  ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Activa: pastilla azul con icono y nombre. Inactiva: solo el icono.
class _BotonPestana extends StatelessWidget {
  final _Pestana pestana;
  final bool activa;
  final VoidCallback onTap;
  const _BotonPestana({required this.pestana, required this.activa, required this.onTap});

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        selected: activa,
        label: pestana.titulo,
        excludeSemantics: true,
        child: Tooltip(
          message: pestana.titulo,
          child: Material(
            color: activa ? AppColors.primary : Colors.transparent,
            shape: const StadiumBorder(),
            child: InkWell(
              customBorder: const StadiumBorder(),
              onTap: onTap,
              child: AnimatedSize(
                duration: const Duration(milliseconds: 220),
                curve: Curves.easeOutCubic,
                child: Container(
                  height: 50,
                  constraints: const BoxConstraints(minWidth: 50),
                  padding: EdgeInsets.symmetric(horizontal: activa ? 16 : 0),
                  alignment: Alignment.center,
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(pestana.icono, size: 22, color: activa ? Colors.white : AppColors.muted),
                    if (activa) ...[
                      const SizedBox(width: 8),
                      Text(
                        pestana.titulo,
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: Colors.white),
                      ),
                    ],
                  ]),
                ),
              ),
            ),
          ),
        ),
      );
}

/// "Más": los demás módulos del propietario y cerrar sesión.
class _MasScreen extends ConsumerWidget {
  const _MasScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(sessionProvider).value;
    if (user == null) return const SizedBox.shrink();
    final enBarra = _PropietarioShellState._fijas.map((p) => p.clave).toSet();
    final otros = modulosDe(user.allowedViews).where((m) => !enBarra.contains(m.clave)).toList();
    final nativos = otros.where((m) => m.nativo).toList();
    final web = otros.where((m) => !m.nativo).toList();

    return ListView(padding: EdgeInsets.zero, children: [
      CabeceraAurora(
        traslape: 28,
        child: Row(children: [
          CircleAvatar(
            radius: 24,
            backgroundColor: Colors.white,
            child: Text(
              user.iniciales,
              style: const TextStyle(fontFamily: Fuentes.titulo, fontWeight: FontWeight.w700, color: AppColors.navy),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                user.nombre,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontFamily: Fuentes.titulo,
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              Text(user.rol, style: const TextStyle(fontSize: 13, color: Color(0xFF9FB2E8))),
            ]),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(18, 20, 18, 24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (nativos.isNotEmpty) ...[
            const Text('Más módulos', style: estiloTituloAurora),
            const SizedBox(height: 10),
            for (final m in nativos) ...[
              _opcion(m.icono, m.color, m.titulo, () => context.push(m.ruta!)),
              const SizedBox(height: 10),
            ],
          ],
          for (final m in web) ...[
            _opcion(
              m.icono,
              m.color,
              m.titulo,
              () => mostrarMensaje(context, '${m.titulo} llegará a la app en la siguiente fase. Por ahora úsalo desde la web.'),
              detalle: 'Disponible en la versión web',
            ),
            const SizedBox(height: 10),
          ],
          const SizedBox(height: 10),
          _opcion(Icons.logout, AppColors.red, 'Cerrar sesión', () async {
            if (await confirmar(context, 'Cerrar sesión', '¿Deseas salir de BusControl?', si: 'Salir')) {
              ref.read(sessionProvider.notifier).logout();
            }
          }),
        ]),
      ),
    ]);
  }

  Widget _opcion(IconData icono, Color color, String titulo, VoidCallback onTap, {String? detalle}) => TarjetaAurora(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        onTap: onTap,
        child: Row(children: [
          IconoSuave(icono, color: color, fondo: color.withValues(alpha: .12), tamano: 42),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(titulo, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
              if (detalle != null) Text(detalle, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          const Icon(Icons.chevron_right, color: AppColors.muted),
        ]),
      );
}
