import 'package:buscontrol/core/recaudo.dart';
import 'package:flutter_test/flutter_test.dart';

/// Liquidación como la devuelve /api/recaudo/propietario: bus 35 con relevo.
final json = <String, dynamic>{
  'id': 7,
  'fecha': '2026-10-09',
  'bus_id': 35,
  'registradora_inicio': 8326,
  'registradora_fin': 8526,
  'pasajeros': 200,
  'tarifa': 3050,
  'producido': 610000,
  'total_gastos': 165000,
  'neto': 445000,
  'recaudado': 445000,
  'diferencia': 0,
  'usuario_nombre': 'Luz Mary Torres',
  'created_at': '2026-10-10T03:53:00Z',
  'conductores': [
    {
      'orden': 1, 'conductor_nombre': 'Bladimir Valencia', 'conductor_cedula': '717356571',
      'ruta_nombre': '110', 'viajes': 6, 'registradora_inicio': 8326, 'registradora_fin': 8426,
      'pasajeros': 100, 'producido': 305000, 'total_gastos': 155000, 'neto': 150000,
      'recaudado': 145000, 'diferencia': -5000,
    },
    {
      'orden': 2, 'conductor_nombre': 'Luis Mejía', 'conductor_cedula': null,
      'ruta_nombre': '110', 'viajes': 4, 'registradora_inicio': 8426, 'registradora_fin': 8526,
      'pasajeros': 100, 'producido': 305000, 'total_gastos': 10000, 'neto': 295000,
      'recaudado': 300000, 'diferencia': 5000,
    },
  ],
  'gastos': [
    {'orden_conductor': 1, 'tipo_nombre': 'ACPM', 'valor': 145000, 'observacion': null},
    {'orden_conductor': 1, 'tipo_nombre': 'Varios', 'valor': 10000, 'observacion': ''},
    {'orden_conductor': 2, 'tipo_nombre': 'Otros', 'valor': 10000, 'observacion': ' Lavado de tapicería '},
  ],
};

void main() {
  test('lee la liquidación con relevo, sus totales y los gastos de cada conductor', () {
    final l = Liquidacion.fromJson(json);
    expect(l.id, 7);
    expect(l.fecha, '2026-10-09');
    expect(l.recaudado, 445000);
    expect(l.neto, l.producido - l.totalGastos);
    expect(l.relevo, isTrue);
    expect(l.nombresConductores, 'Bladimir Valencia, Luis Mejía');
    expect(l.rutas, '110');
    expect(l.viajes, 10);
    expect(l.conductores.last.cedula, '');
    expect(l.gastosDe(1).map((g) => g.tipo), ['ACPM', 'Varios']);
    expect(l.gastosDe(2).single.observacion, 'Lavado de tapicería');
    expect(l.creada, DateTime.utc(2026, 10, 10, 3, 53));
  });

  test('faltante, sobrante o cuadrado según la diferencia', () {
    expect(estadoDiferencia(-5000), ('Faltante \$ 5.000', -1));
    expect(estadoDiferencia(100), ('Sobrante \$ 100', 1));
    expect(estadoDiferencia(0), ('Cuadrado', 0));
  });

  test('el resumen del mes tolera campos vacíos', () {
    final r = ResumenRecaudo.fromJson({'bus_id': 1, 'dias': 2, 'recaudado': 900000, 'total_gastos': null});
    expect(r.dias, 2);
    expect(r.recaudado, 900000);
    expect(r.totalGastos, 0);
  });
}
