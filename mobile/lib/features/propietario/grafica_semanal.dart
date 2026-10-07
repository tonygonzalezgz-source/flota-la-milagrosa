import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/modelos.dart';
import '../../core/movilidad.dart';
import '../../core/theme.dart';
import '../../widgets/aurora.dart';

/// Barras de pasajeros o vueltas por semana (estilo Aurora Clara). La semana
/// con el valor más alto va en azul oscuro y la semana en curso en azul
/// claro, porque todavía no termina.
class GraficaSemanal extends StatefulWidget {
  final List<Semana> semanas;
  final String titulo;
  const GraficaSemanal({super.key, required this.semanas, this.titulo = 'Últimas 8 semanas'});

  @override
  State<GraficaSemanal> createState() => _GraficaSemanalState();
}

class _GraficaSemanalState extends State<GraficaSemanal> {
  bool _vueltas = false;

  Widget _opcion(String texto, bool valor) {
    final activo = _vueltas == valor;
    return Material(
      color: activo ? AppColors.primary : Colors.transparent,
      shape: const StadiumBorder(),
      child: InkWell(
        customBorder: const StadiumBorder(),
        onTap: () => setState(() => _vueltas = valor),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          child: Text(texto,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: activo ? Colors.white : AppColors.muted,
              )),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final valores = [
      for (final s in widget.semanas) (_vueltas ? s.vueltas : s.pasajeros).toDouble(),
    ];
    final maximo = valores.fold<double>(0, (m, v) => v > m ? v : m);
    final tope = maximo == 0 ? 10.0 : maximo * 1.12;
    final fmtSemana = DateFormat('d MMM', 'es_CO');

    Color colorDe(int i) {
      if (widget.semanas[i].enCurso) return const Color(0xFFC9D6FF);
      if (valores[i] == maximo && maximo > 0) return AppColors.primaryDark;
      return AppColors.primary;
    }

    return TarjetaAurora(
      radio: 24,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: Text(widget.titulo, style: estiloTituloAurora.copyWith(fontSize: 15))),
          Container(
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(color: AppColors.campo, borderRadius: BorderRadius.circular(999)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              _opcion('Pasajeros', false),
              _opcion('Vueltas', true),
            ]),
          ),
        ]),
        const SizedBox(height: 18),
        SizedBox(
          height: 170,
          child: BarChart(
            BarChartData(
              maxY: tope,
              alignment: BarChartAlignment.spaceAround,
              gridData: const FlGridData(show: false),
              borderData: FlBorderData(show: false),
              titlesData: FlTitlesData(
                leftTitles: const AxisTitles(),
                rightTitles: const AxisTitles(),
                topTitles: const AxisTitles(),
                bottomTitles: AxisTitles(
                  sideTitles: SideTitles(
                    showTitles: true,
                    reservedSize: 24,
                    getTitlesWidget: (v, meta) {
                      final i = v.toInt();
                      if (i < 0 || i >= widget.semanas.length) {
                        return const SizedBox.shrink();
                      }
                      final s = widget.semanas[i];
                      return SideTitleWidget(
                        meta: meta,
                        space: 6,
                        child: Text(
                          s.enCurso ? 'Hoy' : fmtSemana.format(s.lunes).replaceAll('.', ''),
                          style: TextStyle(
                            fontSize: 10,
                            color: s.enCurso ? AppColors.primary : AppColors.muted,
                            fontWeight: s.enCurso ? FontWeight.w700 : FontWeight.w400,
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
              barTouchData: BarTouchData(
                touchTooltipData: BarTouchTooltipData(
                  getTooltipColor: (_) => AppColors.navy,
                  tooltipBorderRadius: BorderRadius.circular(12),
                  getTooltipItem: (group, _, rod, _) {
                    final s = widget.semanas[group.x];
                    return BarTooltipItem(
                      '${s.enCurso ? 'Semana en curso' : 'Semana del ${fmtSemana.format(s.lunes)}'}\n',
                      const TextStyle(color: Colors.white70, fontSize: 11),
                      children: [
                        TextSpan(
                          text: '${miles(rod.toY)} ${_vueltas ? 'vueltas' : 'pasajeros'}',
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 13),
                        ),
                      ],
                    );
                  },
                ),
              ),
              barGroups: [
                for (var i = 0; i < valores.length; i++)
                  BarChartGroupData(x: i, barRods: [
                    BarChartRodData(
                      toY: valores[i],
                      width: 22,
                      color: colorDe(i),
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ]),
              ],
            ),
          ),
        ),
      ]),
    );
  }
}
