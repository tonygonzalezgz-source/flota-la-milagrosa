import 'fechas.dart';
import 'modelos.dart';

/// Cálculos de movilidad para el propietario, sobre las filas de
/// `/api/movilidad/rango` (registros_movilidad + despacho del día).

/// Valor bruto del pasaje con el que se liquida a los propietarios (COP).
const tarifaPasaje = 3900;

/// Dinero bruto a liquidar: pasajeros × valor del pasaje.
int dineroLiquidar(int pasajeros) => pasajeros * tarifaPasaje;

/// IPK: índice de pasajeros por kilómetro. 0 si no hay kilómetros.
double ipk(int pasajeros, double km) => km > 0 ? pasajeros / km : 0;

class Resumen {
  final int pasajeros;
  final int vueltas;
  final double km;
  final int dias;
  const Resumen({
    this.pasajeros = 0,
    this.vueltas = 0,
    this.km = 0,
    this.dias = 0,
  });

  double get ipkValor => ipk(pasajeros, km);

  factory Resumen.de(Iterable<Map<String, dynamic>> filas) {
    var p = 0, v = 0;
    var k = 0.0;
    final dias = <String>{};
    for (final f in filas) {
      p += asInt(f['pasajeros']) ?? 0;
      v += asInt(f['vueltas']) ?? 0;
      k += asDouble(f['km_recorridos']) ?? 0;
      dias.add(Fechas.normalizar(f['fecha']));
    }
    return Resumen(pasajeros: p, vueltas: v, km: k, dias: dias.length);
  }
}

/// Variación porcentual de [actual] frente a [anterior]; null si no hay base.
double? variacion(num actual, num anterior) =>
    anterior == 0 ? null : (actual - anterior) / anterior * 100;

DateTime lunesDe(DateTime d) =>
    DateTime(d.year, d.month, d.day).subtract(Duration(days: d.weekday - 1));

class Semana {
  final DateTime lunes;
  final int pasajeros;
  final int vueltas;
  final bool enCurso;
  const Semana(this.lunes, this.pasajeros, this.vueltas, this.enCurso);
}

/// Totales por semana (lunes a domingo) de las últimas [n] semanas,
/// incluida la semana en curso (la última de la lista).
List<Semana> semanas(
  Iterable<Map<String, dynamic>> filas, {
  int n = 8,
  DateTime? hoy,
}) {
  final h = hoy ?? DateTime.parse(Fechas.hoy());
  final lunesActual = lunesDe(h);
  final lunes = [
    for (var i = n - 1; i >= 0; i--)
      lunesActual.subtract(Duration(days: 7 * i)),
  ];
  final pax = {for (final l in lunes) l: 0};
  final vlt = {for (final l in lunes) l: 0};
  for (final f in filas) {
    final d = Fechas.parse(f['fecha']);
    if (d == null) continue;
    final l = lunesDe(d);
    if (!pax.containsKey(l)) continue;
    pax[l] = pax[l]! + (asInt(f['pasajeros']) ?? 0);
    vlt[l] = vlt[l]! + (asInt(f['vueltas']) ?? 0);
  }
  return [for (final l in lunes) Semana(l, pax[l]!, vlt[l]!, l == lunesActual)];
}

/// Semana en curso (lunes → hoy) frente al mismo tramo de la semana pasada,
/// para comparar días equivalentes y no una semana parcial contra una completa.
({Resumen actual, Resumen anterior}) estaSemanaVsAnterior(
  Iterable<Map<String, dynamic>> filas, {
  DateTime? hoy,
}) {
  final h = hoy ?? DateTime.parse(Fechas.hoy());
  final lunes = lunesDe(h);
  final lunesAnt = lunes.subtract(const Duration(days: 7));
  final hoyAnt = h.subtract(const Duration(days: 7));
  bool entre(DateTime d, DateTime a, DateTime b) =>
      !d.isBefore(a) && !d.isAfter(b);
  final act = <Map<String, dynamic>>[], ant = <Map<String, dynamic>>[];
  for (final f in filas) {
    final d = Fechas.parse(f['fecha']);
    if (d == null) continue;
    if (entre(d, lunes, h)) act.add(f);
    if (entre(d, lunesAnt, hoyAnt)) ant.add(f);
  }
  return (actual: Resumen.de(act), anterior: Resumen.de(ant));
}

/// Conductor del día: el de movilidad y, si falta, el del despacho.
String conductorDe(Map<String, dynamic> f) {
  final c = asStr(f['conductor_nombre']);
  return c.isNotEmpty ? c : asStr(f['despacho_conductor_nombre']);
}

String rutaDe(Map<String, dynamic> f) {
  final r = asStr(f['ruta_nombre']);
  return r.isNotEmpty ? r : asStr(f['despacho_ruta_nombre']);
}
