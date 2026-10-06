import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/modulos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';

/// Menú principal: un acceso por cada módulo que el rol tiene permitido.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(sessionProvider).value;
    if (user == null) return const SizedBox.shrink();
    final lista = modulosDe(user.allowedViews);
    final nativos = lista.where((m) => m.nativo).toList();
    final web = lista.where((m) => !m.nativo).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('BusControl'),
        actions: [
          IconButton(
            tooltip: 'Cerrar sesión',
            icon: const Icon(Icons.logout),
            onPressed: () async {
              if (await confirmar(context, 'Cerrar sesión', '¿Deseas salir de BusControl?',
                  si: 'Salir')) {
                ref.read(sessionProvider.notifier).logout();
              }
            },
          ),
        ],
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Card(
          child: ListTile(
            leading: CircleAvatar(
              backgroundColor: _color(user.color),
              child: Text(user.iniciales,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
            ),
            title: Text(user.nombre, style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text(user.rol),
          ),
        ),
        if (nativos.isEmpty && web.isEmpty)
          const VacioView('Tu usuario no tiene módulos asignados. Contacta al administrador.'),
        if (nativos.isNotEmpty) ...[
          const TituloSeccion('Módulos'),
          GridView.count(
            crossAxisCount: MediaQuery.sizeOf(context).width > 600 ? 3 : 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.45,
            children: [for (final m in nativos) _Tile(m)],
          ),
        ],
        if (web.isNotEmpty) ...[
          const TituloSeccion('Disponibles en la versión web'),
          Card(
            child: Column(children: [
              for (final m in web)
                ListTile(
                  leading: Icon(m.icono, color: m.color),
                  title: Text(m.titulo),
                  trailing: const Icon(Icons.desktop_windows_outlined, size: 18, color: AppColors.muted),
                  onTap: () => mostrarMensaje(
                      context, '${m.titulo} llegará a la app en la siguiente fase. Por ahora úsalo desde la web.'),
                ),
            ]),
          ),
        ],
      ]),
    );
  }

  Color _color(String? hex) {
    if (hex == null || !hex.startsWith('#') || hex.length != 7) return AppColors.primary;
    return Color(int.parse('FF${hex.substring(1)}', radix: 16));
  }
}

class _Tile extends StatelessWidget {
  final Modulo m;
  const _Tile(this.m);

  @override
  Widget build(BuildContext context) => Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => context.push(m.ruta!),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: m.color.withValues(alpha: .12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(m.icono, color: m.color, size: 26),
              ),
              const Spacer(),
              Text(m.titulo, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
            ]),
          ),
        ),
      );
}
