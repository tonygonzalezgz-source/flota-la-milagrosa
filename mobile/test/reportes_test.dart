import 'package:buscontrol/core/recaudo.dart';
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

/// Recaudo de un conductor en una liquidación (fila de /api/recaudo/propietario/diario).
TramoDiario _tramo(int bus, String fecha, int orden, String conductor, String ruta, int recaudado, int gastos) =>
    TramoDiario.fromJson({
      'recaudo_id': 1, 'bus_id': bus, 'fecha': fecha, 'orden': orden, 'conductor_nombre': conductor,
      'ruta_nombre': ruta, 'viajes': 3, 'pasajeros': 100, 'producido': recaudado + gastos,
      'total_gastos': gastos, 'recaudado': recaudado, 'diferencia': 0,
    });

final _recaudo = [
  // Bus 12 el 1 de octubre con relevo: Pedro en la Ruta 1 y Ana en la Ruta 2.
  _tramo(1, '2026-10-01', 1, 'Pedro Gómez', 'Ruta 1', 1000000, 100000),
  _tramo(1, '2026-10-01', 2, 'Ana Ruiz', 'Ruta 2', 500000, 0),
  _tramo(1, '2026-10-02', 1, 'Pedro Gómez', 'Ruta 1', 900000, 50000),
  _tramo(2, '2026-10-01', 1, 'Luis Martínez', 'Ruta 2', 400000, 20000),
  _tramo(1, '2026-09-30', 1, 'Pedro Gómez', 'Ruta 1', 999, 0), // fuera del rango
  _tramo(99, '2026-10-01', 1, 'Otro', 'Ruta 1', 777, 0), // bus de otro propietario
];

Reporte _reporte({List<Map<String, dynamic>>? despacho, int? busId, bool sinDespacho = false, bool sinRecaudo = false}) =>
    Reporte.armar(
      rango: (desde: '2026-10-01', hasta: '2026-10-08'),
      buses: _buses,
      hoy: _hoy,
      busId: busId,
      recaudo: sinRecaudo ? null : _recaudo,
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

  test('el dinero es lo recaudado en las liquidaciones, por bus, ruta, conductor y día', () {
    final r = _reporte();
    expect(r.conRecaudo, isTrue);
    expect(r.total.recaudo, 2800000);
    expect(r.total.gastos, 170000);
    expect(r.buses.first.totales.recaudo, 2400000);
    // Con relevo, cada conductor suma a su ruta.
    expect(r.porRuta['Ruta 1']!.recaudo, 1900000);
    expect(r.porRuta['Ruta 2']!.recaudo, 900000);
    expect(r.porConductor['Ana Ruiz']!.recaudo, 500000);
    final dia1Bus12 = r.diario.firstWhere((f) => f['bus_id'] == 1 && f['fecha'] == '2026-10-01');
    expect(r.recaudoDe(dia1Bus12), 1500000);
    final dia3Bus15 = r.diario.firstWhere((f) => f['bus_id'] == 2 && f['fecha'] == '2026-10-03');
    expect(r.recaudoDe(dia3Bus15), isNull);

    final sin = _reporte(sinRecaudo: true);
    expect(sin.conRecaudo, isFalse);
    expect(sin.total.recaudo, 0);
  });

  test('totales, IPK y promedios', () {
    final r = _reporte();
    expect(r.total.pasajeros, 2500);
    expect(r.total.vueltas, 18);
    expect(r.total.km, 390);
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
    expect(celda('Resumen', filaBus12, 11), '150000'); // gastos
    expect(celda('Resumen', filaBus12, 12), '2400000'); // recaudo

    expect(libro.tables['Detalle']!.rows.length, 1 + 4);
    expect(celda('Detalle', 1, 0), '01/10/2026'); // más antiguo primero
    final filaDia = libro.tables['Detalle']!.rows.indexWhere((f) => f.length > 1 && f[1]?.value.toString() == '12');
    expect(celda('Detalle', filaDia, 9), '1500000'); // recaudo del 1 de octubre del bus 12
    expect(celda('Días', 0, 1), 'Bus 12');
    expect(celda('Días', 3, 1), 'Taller'); // 3 de octubre
    expect(nombreExcel(r), 'Reporte BusControl 2026-10-01 a 2026-10-08.xlsx');
  });
}
