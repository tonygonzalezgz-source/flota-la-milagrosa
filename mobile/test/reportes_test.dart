import 'package:buscontrol/core/reportes.dart';
import 'package:buscontrol/features/reportes/reporte_excel.dart';
import 'package:excel/excel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';

final _hoy = DateTime(2026, 10, 8); // jueves

const _buses = [
  {'id': 1, 'numero': 12, 'placa': 'TSK929'},
  {'id': 2, 'numero': 15, 'placa': 'TPU831'},
];

Map<String, dynamic> _mov(int bus, String fecha, int vueltas, int pax, double km,
        {String conductor = '', String ruta = '', String despCond = '', String despRuta = ''}) =>
    {
      'bus_id': bus,
      'numero': bus == 1 ? 12 : 15,
      'placa': bus == 1 ? 'TSK929' : 'TPU831',
      'fecha': fecha,
      'vueltas': vueltas,
      'pasajeros': pax,
      'km_recorridos': km,
      'conductor_nombre': conductor,
      'ruta_nombre': ruta,
      'despacho_conductor_nombre': despCond,
      'despacho_ruta_nombre': despRuta,
    };

/// Despacho como lo devuelve /api/despacho/historial (sin bus_id en el backend viejo).
Map<String, dynamic> _desp(int numero, String fecha, String? estado) => {'numero': numero, 'fecha': fecha, 'estado': estado};

Reporte _reporte({List<Map<String, dynamic>>? despacho, int? busId, bool sinDespacho = false}) => Reporte.armar(
      rango: (desde: '2026-10-01', hasta: '2026-10-08'),
      buses: _buses,
      hoy: _hoy,
      busId: busId,
      movilidad: [
        _mov(1, '2026-10-01', 6, 900, 140, despCond: 'Pedro Gómez', despRuta: 'Ruta 1'),
        _mov(1, '2026-10-02', 7, 1000, 150, conductor: 'Pedro Gómez', ruta: 'Ruta 1'),
        _mov(2, '2026-10-01', 5, 600, 100, despCond: 'Luis Martínez', despRuta: 'Ruta 2'),
        // Registro sin vueltas ni pasajeros: no cuenta como trabajado por sí solo.
        _mov(2, '2026-10-03', 0, 0, 0),
        // Fuera del rango: se ignora.
        _mov(1, '2026-09-30', 6, 999, 140),
      ],
      despacho: sinDespacho
          ? null
          : despacho ??
              [
                _desp(12, '2026-10-03', 'taller'),
                _desp(12, '2026-10-04', 'descanso'),
                _desp(12, '2026-10-05', 'trabajando'), // trabajó aunque falte la movilidad
                _desp(15, '2026-10-02', 'descanso'),
                _desp(15, '2026-10-03', 'taller'),
                _desp(99, '2026-10-03', 'trabajando'), // bus de otro propietario: se ignora
              ],
    );

void main() {
  setUpAll(() => initializeDateFormatting('es_CO'));

  test('periodos rápidos', () {
    expect(Periodo.semana.rango(hoy: _hoy), (desde: '2026-10-05', hasta: '2026-10-08'));
    expect(Periodo.mes.rango(hoy: _hoy), (desde: '2026-10-01', hasta: '2026-10-08'));
    expect(Periodo.mesAnterior.rango(hoy: _hoy), (desde: '2026-09-01', hasta: '2026-09-30'));
    expect(Periodo.mesAnterior.rango(hoy: DateTime(2026, 1, 15)), (desde: '2025-12-01', hasta: '2025-12-31'));
  });

  test('el rango no pasa de hoy', () {
    final r = Reporte.armar(
      rango: (desde: '2026-10-06', hasta: '2026-10-31'),
      buses: _buses,
      movilidad: const [],
      hoy: _hoy,
    );
    expect(r.fechas, ['2026-10-06', '2026-10-07', '2026-10-08']);
    expect(r.rango.hasta, '2026-10-08');
  });

  test('días trabajados, taller, descanso y sin registro por bus', () {
    final r = _reporte();
    expect(r.diasPeriodo, 8);
    final b12 = r.buses.firstWhere((b) => b.numero == '12');
    expect(b12.dias['2026-10-01'], EstadoDia.trabajado);
    expect(b12.dias['2026-10-03'], EstadoDia.taller);
    expect(b12.dias['2026-10-04'], EstadoDia.descanso);
    expect(b12.dias['2026-10-05'], EstadoDia.trabajado);
    expect(
      [for (final e in EstadoDia.values) b12.cuantos(e)],
      [3, 1, 1, 3], // trabajó 1, 2 y 5; taller 3; descanso 4; sin registro 6, 7 y 8
    );
    final b15 = r.buses.firstWhere((b) => b.numero == '15');
    expect(b15.dias['2026-10-03'], EstadoDia.taller); // movilidad en cero → manda el despacho
    expect([for (final e in EstadoDia.values) b15.cuantos(e)], [1, 1, 1, 5]);
  });

  test('totales, dinero, IPK y promedios', () {
    final r = _reporte();
    expect(r.total.pasajeros, 2500);
    expect(r.total.vueltas, 18);
    expect(r.total.km, 390);
    expect(r.total.dinero, 2500 * 3900);
    expect(r.total.ipkValor, closeTo(2500 / 390, 1e-9));
    final b12 = r.buses.first;
    expect(b12.totales.pasajeros, 1900);
    expect(b12.pasajerosPorDia, closeTo(1900 / 3, 1e-9));
    expect(b12.totales.pasajerosPorVuelta, closeTo(1900 / 13, 1e-9));
  });

  test('por ruta y por conductor: manda el despacho, ordenados por pasajeros', () {
    final r = _reporte();
    expect(r.porRuta.keys, ['Ruta 1', 'Ruta 2', 'Sin ruta']);
    expect(r.porRuta['Ruta 1']!.pasajeros, 1900);
    expect(r.porRuta['Ruta 1']!.dias, {'2026-10-01', '2026-10-02'});
    expect(r.porConductor.keys.first, 'Pedro Gómez');
    expect(r.porConductor['Luis Martínez']!.vueltas, 5);
  });

  test('reporte de un solo bus', () {
    final r = _reporte(busId: 2);
    expect(r.buses.map((b) => b.numero), ['15']);
    expect(r.total.pasajeros, 600);
    expect(r.diario.every((f) => f['bus_id'] == 2), isTrue);
  });

  test('sin despacho los días sin movilidad quedan sin registro', () {
    final r = _reporte(sinDespacho: true);
    expect(r.conDespacho, isFalse);
    expect(r.buses.first.cuantos(EstadoDia.trabajado), 2);
    expect(r.buses.first.cuantos(EstadoDia.taller), 0);
  });

  test('detalle diario del más reciente al más antiguo', () {
    final fechas = _reporte().diario.map((f) => f['fecha']).toList();
    expect(fechas, ['2026-10-03', '2026-10-02', '2026-10-01', '2026-10-01']);
  });

  test('el Excel se abre y trae resumen, detalle y días', () {
    final r = _reporte();
    final libro = Excel.decodeBytes(excelReporte(r));
    expect(libro.tables.keys, containsAll(['Resumen', 'Detalle', 'Días']));

    String celda(String hoja, int fila, int col) =>
        libro.tables[hoja]!.rows[fila][col]?.value.toString() ?? '';
    final resumen = libro.tables['Resumen']!.rows;
    final filaBus12 = resumen.indexWhere((f) => f.isNotEmpty && f[0]?.value.toString() == '12');
    expect(celda('Resumen', filaBus12, 2), '3'); // días trabajados
    expect(celda('Resumen', filaBus12, 7), '1900'); // pasajeros
    expect(celda('Resumen', filaBus12, 11), '${1900 * 3900}'); // dinero bruto

    expect(libro.tables['Detalle']!.rows.length, 1 + 4);
    expect(celda('Detalle', 1, 0), '01/10/2026'); // más antiguo primero
    expect(celda('Días', 0, 1), 'Bus 12');
    expect(celda('Días', 3, 1), 'Taller'); // 3 de octubre
    expect(nombreExcel(r), 'Reporte BusControl 2026-10-01 a 2026-10-08.xlsx');
  });
}
