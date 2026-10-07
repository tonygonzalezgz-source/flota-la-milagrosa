import 'package:buscontrol/core/movilidad.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> fila(String fecha, int pax, int vueltas, double km) => {
  'fecha': fecha,
  'pasajeros': pax,
  'vueltas': vueltas,
  'km_recorridos': km,
};

void main() {
  test('el dinero bruto se liquida a \$3.900 por pasajero', () {
    expect(tarifaPasaje, 3900);
    expect(dineroLiquidar(100), 390000);
    expect(dineroLiquidar(0), 0);
  });

  test('IPK = pasajeros / km, 0 sin kilómetros', () {
    expect(ipk(300, 120), 2.5);
    expect(ipk(300, 0), 0);
    final r = Resumen.de([
      fila('2026-10-05', 200, 4, 80),
      fila('2026-10-06', 100, 2, 40),
    ]);
    expect(r.pasajeros, 300);
    expect(r.vueltas, 6);
    expect(r.dias, 2);
    expect(r.ipkValor, 2.5);
  });

  test('semanas agrupa de lunes a domingo y marca la semana en curso', () {
    final hoy = DateTime(2026, 10, 7); // miércoles
    final s = semanas(
      [
        fila('2026-10-05', 100, 2, 0), // lunes de esta semana
        fila('2026-10-07', 50, 1, 0), // hoy
        fila('2026-10-04', 70, 1, 0), // domingo de la semana pasada
        fila('2026-09-28', 30, 1, 0), // lunes de la semana pasada
        fila('2026-01-01', 999, 9, 0), // fuera del rango
      ],
      n: 3,
      hoy: hoy,
    );
    expect(s.length, 3);
    expect(s.last.lunes, DateTime(2026, 10, 5));
    expect(s.last.enCurso, isTrue);
    expect(s.last.pasajeros, 150);
    expect(s[1].lunes, DateTime(2026, 9, 28));
    expect(s[1].pasajeros, 100);
    expect(s[1].vueltas, 2);
    expect(s.first.pasajeros, 0);
  });

  test('la comparación usa los mismos días de la semana pasada', () {
    final hoy = DateTime(2026, 10, 7); // miércoles
    final c = estaSemanaVsAnterior([
      fila('2026-10-06', 100, 2, 0),
      fila('2026-09-30', 80, 2, 0), // miércoles pasado: cuenta
      fila('2026-10-02', 500, 9, 0), // viernes pasado: no cuenta
    ], hoy: hoy);
    expect(c.actual.pasajeros, 100);
    expect(c.anterior.pasajeros, 80);
    expect(variacion(100, 80), 25);
    expect(variacion(10, 0), isNull);
  });

  test('conductor y ruta caen al despacho si movilidad no los tiene', () {
    expect(
      conductorDe({
        'conductor_nombre': null,
        'despacho_conductor_nombre': 'Pedro',
      }),
      'Pedro',
    );
    expect(
      conductorDe({
        'conductor_nombre': 'Luis',
        'despacho_conductor_nombre': 'Pedro',
      }),
      'Luis',
    );
    expect(rutaDe({'ruta_nombre': '', 'despacho_ruta_nombre': 'R1'}), 'R1');
  });
}
