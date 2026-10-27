import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/recaudo.dart';
import '../../core/theme.dart';
import '../../widgets/aurora.dart';

/// Pastilla con el resultado de la entrega: cuadrado, faltante o sobrante.
class ChipDiferencia extends StatelessWidget {
  final int diferencia;
  const ChipDiferencia(this.diferencia, {super.key});

  @override
  Widget build(BuildContext context) {
    final (texto, nivel) = estadoDiferencia(diferencia);
    final (fondo, color) = switch (nivel) {
      < 0 => (const Color(0xFFFDECEC), AppColors.red),
      > 0 => (const Color(0xFFFFF4E0), const Color(0xFFB36B00)),
      _ => (const Color(0xFFE7F6EE), AppColors.dinero),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(999)),
      child: Text(texto, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color)),
    );
  }
}

/// "Ver liquidación": cómo se liquidó el bus ese día, igual que la tirilla y
/// que el detalle de la web (con relevo, la parte de cada conductor).
Future<void> verLiquidacion(BuildContext context, Liquidacion l) => showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .88,
        minChildSize: .5,
        maxChildSize: .95,
        builder: (context, scroll) => Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
          ),
          child: ListView(
            controller: scroll,
            padding: const EdgeInsets.fromLTRB(20, 10, 20, 32),
            children: _contenido(l),
          ),
        ),
      ),
    );

String _hora(DateTime utc) =>
    DateFormat("d 'de' MMM, h:mm a", 'es_CO').format(utc.toUtc().subtract(const Duration(hours: 5)));

List<Widget> _contenido(Liquidacion l) {
  final conViajes = l.viajes;
  final cedulas = l.conductores
      .map((c) => c.cedula.isEmpty ? c.conductor : '${c.conductor} (${c.cedula})')
      .join(', ');
  return [
    Center(
      child: Container(
        width: 40,
        height: 4,
        margin: const EdgeInsets.only(bottom: 16),
        decoration: BoxDecoration(color: const Color(0xFFD5DBE8), borderRadius: BorderRadius.circular(2)),
      ),
    ),
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Liquidación del recaudo', style: TextStyle(fontSize: 12, color: AppColors.muted)),
          Text(
            _mayuscula(Fechas.larga(l.fecha)),
            style: const TextStyle(fontFamily: Fuentes.titulo, fontSize: 18, fontWeight: FontWeight.w700),
          ),
        ]),
      ),
      const SizedBox(width: 8),
      ChipDiferencia(l.diferencia),
    ]),
    const SizedBox(height: 10),
    Text(
      '${l.relevo ? 'Conductores' : 'Conductor'}: ${cedulas.isEmpty ? '—' : cedulas}',
      style: const TextStyle(fontSize: 13, color: Color(0xFF3A4666)),
    ),
    if (l.rutas.isNotEmpty || conViajes != null)
      Text(
        [if (l.rutas.isNotEmpty) 'Ruta: ${l.rutas}', if (conViajes != null) '$conViajes viajes'].join(' · '),
        style: const TextStyle(fontSize: 13, color: Color(0xFF3A4666)),
      ),
    const SizedBox(height: 16),
    _Bloque(children: [
      _fila('Registradora', '${miles(l.registradoraInicio)} → ${miles(l.registradoraFin)}'),
      _fila('Pasajeros × tarifa', '${miles(l.pasajeros)} × ${pesos(l.tarifa)}'),
      _fila('Producido', pesos(l.producido), fuerte: true),
      if (!l.relevo) ...[
        _subtitulo('Gastos del día'),
        ..._gastos(l.gastos),
      ],
      _fila('Total gastos', '− ${pesos(l.totalGastos)}', fuerte: true),
      _fila('Por entregar', pesos(l.neto)),
      const Divider(height: 18),
      _fila('Recaudado', pesos(l.recaudado), grande: true),
      _filaDiferencia(l.diferencia),
    ]),
    if (l.relevo) ...[
      const SizedBox(height: 18),
      const Text('Detalle por conductor (relevo)', style: estiloTituloAurora),
      for (final c in l.conductores) ...[
        const SizedBox(height: 10),
        _Bloque(children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Text(
                '${c.orden}. ${c.conductor}',
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
              ),
            ),
            const SizedBox(width: 8),
            ChipDiferencia(c.diferencia),
          ]),
          if (c.ruta.isNotEmpty || c.viajes != null)
            Padding(
              padding: const EdgeInsets.only(top: 2, bottom: 6),
              child: Text(
                [if (c.ruta.isNotEmpty) 'Ruta: ${c.ruta}', if (c.viajes != null) '${c.viajes} viajes'].join(' · '),
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ),
          _fila('Registradora', '${miles(c.registradoraInicio)} → ${miles(c.registradoraFin)}'),
          _fila('Pasajeros × tarifa', '${miles(c.pasajeros)} × ${pesos(l.tarifa)}'),
          _fila('Producido', pesos(c.producido), fuerte: true),
          ..._gastos(l.gastosDe(c.orden)),
          _fila('Por entregar', pesos(c.neto)),
          _fila('Entregó', pesos(c.recaudado), fuerte: true),
          _filaDiferencia(c.diferencia),
        ]),
      ],
    ],
    const SizedBox(height: 14),
    Text(
      [
        'Liquidación N° ${l.id.toString().padLeft(6, '0')}',
        if (l.creada != null) _hora(l.creada!),
        if (l.atendio.isNotEmpty) 'atendió ${l.atendio}',
      ].join(' · '),
      style: const TextStyle(fontSize: 11, color: AppColors.muted),
    ),
  ];
}

String _mayuscula(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

List<Widget> _gastos(List<GastoRecaudo> gastos) => gastos.isEmpty
    ? [_fila('Sin gastos', pesos(0), gasto: true)]
    : [for (final g in gastos) _fila(g.tipo, '− ${pesos(g.valor)}', gasto: true, nota: g.observacion)];

Widget _subtitulo(String t) => Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 2),
      child: Text(
        t.toUpperCase(),
        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: .4, color: AppColors.muted),
      ),
    );

Widget _filaDiferencia(int d) {
  final (_, nivel) = estadoDiferencia(d);
  final titulo = nivel < 0 ? 'Faltante' : nivel > 0 ? 'Sobrante' : 'Diferencia';
  final color = nivel < 0 ? AppColors.red : nivel > 0 ? const Color(0xFFB36B00) : AppColors.dinero;
  return _fila(titulo, pesos(d.abs()), color: color, fuerte: true);
}

Widget _fila(String titulo, String valor,
    {bool fuerte = false, bool grande = false, bool gasto = false, String nota = '', Color? color}) {
  final estilo = TextStyle(
    fontSize: grande ? 17 : 14,
    fontWeight: fuerte || grande ? FontWeight.w700 : FontWeight.w400,
    color: color ?? (grande ? AppColors.dinero : gasto ? const Color(0xFF3A4666) : AppColors.texto),
    fontFeatures: const [FontFeature.tabularFigures()],
  );
  return Padding(
    padding: EdgeInsets.only(top: 4, bottom: 4, left: gasto ? 10 : 0),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(titulo, style: estilo.copyWith(fontFeatures: const [])),
          if (nota.isNotEmpty) Text(nota, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      ),
      const SizedBox(width: 10),
      Text(valor, style: estilo),
    ]),
  );
}

class _Bloque extends StatelessWidget {
  final List<Widget> children;
  const _Bloque({required this.children});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
        decoration: BoxDecoration(color: AppColors.campo, borderRadius: BorderRadius.circular(20)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
      );
}
