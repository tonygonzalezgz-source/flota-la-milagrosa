import 'package:flutter/material.dart';

import '../core/theme.dart';

void mostrarMensaje(BuildContext context, String msg, {bool error = false}) {
  final m = ScaffoldMessenger.of(context);
  m.hideCurrentSnackBar();
  m.showSnackBar(SnackBar(
    content: Text(msg),
    backgroundColor: error ? AppColors.red : const Color(0xFF16A34A),
    behavior: SnackBarBehavior.floating,
  ));
}

/// Estado de carga / error / contenido de una pantalla que trae datos de la API.
class CargaView extends StatelessWidget {
  final bool cargando;
  final String? error;
  final VoidCallback onReintentar;
  final Widget Function() builder;

  const CargaView({
    super.key,
    required this.cargando,
    required this.error,
    required this.onReintentar,
    required this.builder,
  });

  @override
  Widget build(BuildContext context) {
    if (cargando) return const Center(child: CircularProgressIndicator());
    if (error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 48, color: AppColors.muted),
            const SizedBox(height: 12),
            Text(error!, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: onReintentar,
              icon: const Icon(Icons.refresh),
              label: const Text('Reintentar'),
            ),
          ]),
        ),
      );
    }
    return builder();
  }
}

class VacioView extends StatelessWidget {
  final String texto;
  final IconData icono;
  const VacioView(this.texto, {super.key, this.icono = Icons.inbox_outlined});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
        child: Column(children: [
          Icon(icono, size: 44, color: AppColors.muted),
          const SizedBox(height: 10),
          Text(texto, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
        ]),
      );
}

/// Pastilla de color con texto (estado, tipo, categoría…).
class Etiqueta extends StatelessWidget {
  final String texto;
  final Color color;
  const Etiqueta(this.texto, this.color, {super.key});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .12),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(texto,
            style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12)),
      );
}

/// Tarjeta pequeña de indicador (KPI).
class Indicador extends StatelessWidget {
  final String titulo;
  final String valor;
  final Color color;
  final IconData? icono;
  const Indicador(this.titulo, this.valor, this.color, {super.key, this.icono});

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              if (icono != null) ...[Icon(icono, size: 16, color: color), const SizedBox(width: 6)],
              Expanded(
                child: Text(titulo,
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                    overflow: TextOverflow.ellipsis),
              ),
            ]),
            const SizedBox(height: 6),
            Text(valor,
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, color: color)),
          ]),
        ),
      );
}

class TituloSeccion extends StatelessWidget {
  final String texto;
  final Widget? trailing;
  const TituloSeccion(this.texto, {super.key, this.trailing});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 18, 4, 8),
        child: Row(children: [
          Expanded(
            child: Text(texto,
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          ),
          ?trailing,
        ]),
      );
}

Future<bool> confirmar(BuildContext context, String titulo, String mensaje,
    {String si = 'Sí', String no = 'Cancelar'}) async {
  final r = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(titulo),
      content: Text(mensaje),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: Text(no)),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(80, 40)),
          onPressed: () => Navigator.pop(c, true),
          child: Text(si),
        ),
      ],
    ),
  );
  return r ?? false;
}
