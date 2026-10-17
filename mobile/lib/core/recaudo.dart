import 'api_client.dart';
import 'fechas.dart';
import 'modelos.dart';

/// Recaudo real del bus: lo que el conductor liquidó cada día en el módulo
/// Recaudo de la web. El dinero que ve el propietario es siempre lo RECAUDADO:
/// pasajeros × la tarifa de su tipo de vehículo (bus o micro, la que tenía el
/// día de la liquidación) menos los gastos que reportó el conductor. El servidor
/// solo devuelve los buses del propietario; si el recaudo no está habilitado
/// para la cuenta responde 403 y la app no muestra dinero.

class GastoRecaudo {
  final int ordenConductor;
  final String tipo;
  final int valor;
  final String observacion;
  const GastoRecaudo(this.ordenConductor, this.tipo, this.valor, this.observacion);

  factory GastoRecaudo.fromJson(Map<String, dynamic> j) => GastoRecaudo(
        asInt(j['orden_conductor']) ?? 1,
        asStr(j['tipo_nombre']),
        asInt(j['valor']) ?? 0,
        asStr(j['observacion']).trim(),
      );
}

/// La parte de un conductor en la liquidación (con relevo hay hasta 3).
class TramoRecaudo {
  final int orden;
  final String conductor;
  final String cedula;
  final String ruta;
  final int? viajes;
  final int registradoraInicio;
  final int registradoraFin;
  final int pasajeros;
  final int producido;
  final int totalGastos;
  final int neto;
  final int recaudado;
  final int diferencia;

  const TramoRecaudo({
    required this.orden,
    required this.conductor,
    required this.cedula,
    required this.ruta,
    required this.viajes,
    required this.registradoraInicio,
    required this.registradoraFin,
    required this.pasajeros,
    required this.producido,
    required this.totalGastos,
    required this.neto,
    required this.recaudado,
    required this.diferencia,
  });

  factory TramoRecaudo.fromJson(Map<String, dynamic> j) => TramoRecaudo(
        orden: asInt(j['orden']) ?? 1,
        conductor: asStr(j['conductor_nombre']),
        cedula: asStr(j['conductor_cedula']),
        ruta: asStr(j['ruta_nombre']),
        viajes: asInt(j['viajes']),
        registradoraInicio: asInt(j['registradora_inicio']) ?? 0,
        registradoraFin: asInt(j['registradora_fin']) ?? 0,
        pasajeros: asInt(j['pasajeros']) ?? 0,
        producido: asInt(j['producido']) ?? 0,
        totalGastos: asInt(j['total_gastos']) ?? 0,
        neto: asInt(j['neto']) ?? 0,
        recaudado: asInt(j['recaudado']) ?? 0,
        diferencia: asInt(j['diferencia']) ?? 0,
      );
}

class Liquidacion {
  final int id;
  final String fecha;
  final int busId;
  final int registradoraInicio;
  final int registradoraFin;
  final int pasajeros;
  final int tarifa;
  final int producido;
  final int totalGastos;

  /// Por entregar: producido − gastos.
  final int neto;
  final int recaudado;

  /// recaudado − neto: negativo es faltante, positivo sobrante.
  final int diferencia;
  final String atendio;
  final DateTime? creada;
  final List<TramoRecaudo> conductores;
  final List<GastoRecaudo> gastos;

  const Liquidacion({
    required this.id,
    required this.fecha,
    required this.busId,
    required this.registradoraInicio,
    required this.registradoraFin,
    required this.pasajeros,
    required this.tarifa,
    required this.producido,
    required this.totalGastos,
    required this.neto,
    required this.recaudado,
    required this.diferencia,
    required this.atendio,
    required this.creada,
    required this.conductores,
    required this.gastos,
  });

  factory Liquidacion.fromJson(Map<String, dynamic> j) => Liquidacion(
        id: asInt(j['id']) ?? 0,
        fecha: Fechas.normalizar(j['fecha']),
        busId: asInt(j['bus_id']) ?? 0,
        registradoraInicio: asInt(j['registradora_inicio']) ?? 0,
        registradoraFin: asInt(j['registradora_fin']) ?? 0,
        pasajeros: asInt(j['pasajeros']) ?? 0,
        tarifa: asInt(j['tarifa']) ?? 0,
        producido: asInt(j['producido']) ?? 0,
        totalGastos: asInt(j['total_gastos']) ?? 0,
        neto: asInt(j['neto']) ?? 0,
        recaudado: asInt(j['recaudado']) ?? 0,
        diferencia: asInt(j['diferencia']) ?? 0,
        atendio: asStr(j['usuario_nombre']),
        // El servidor manda la hora en UTC ('…Z').
        creada: DateTime.tryParse(asStr(j['created_at'])),
        conductores: asLista(j['conductores']).map(TramoRecaudo.fromJson).toList(),
        gastos: asLista(j['gastos']).map(GastoRecaudo.fromJson).toList(),
      );

  bool get relevo => conductores.length > 1;

  String get nombresConductores =>
      conductores.map((c) => c.conductor).where((n) => n.isNotEmpty).join(', ');

  /// Rutas sin repetir (con relevo pueden ser varias).
  String get rutas => conductores.map((c) => c.ruta).where((r) => r.isNotEmpty).toSet().join(', ');

  /// Viajes del bus (suma de los conductores); null si nadie los anotó.
  int? get viajes {
    final v = conductores.map((c) => c.viajes).whereType<int>();
    return v.isEmpty ? null : v.reduce((a, b) => a + b);
  }

  List<GastoRecaudo> gastosDe(int orden) => gastos.where((g) => g.ordenConductor == orden).toList();
}

/// Recaudo de un conductor en un día (fila de /api/recaudo/propietario/diario).
/// Con relevo hay varias filas para el mismo bus y día.
class TramoDiario {
  final int recaudoId;
  final int busId;
  final String fecha;
  final int orden;
  final String conductor;
  final String ruta;
  final int? viajes;
  final int pasajeros;
  final int producido;
  final int totalGastos;
  final int recaudado;
  final int diferencia;

  const TramoDiario({
    required this.recaudoId,
    required this.busId,
    required this.fecha,
    required this.orden,
    required this.conductor,
    required this.ruta,
    required this.viajes,
    required this.pasajeros,
    required this.producido,
    required this.totalGastos,
    required this.recaudado,
    required this.diferencia,
  });

  factory TramoDiario.fromJson(Map<String, dynamic> j) => TramoDiario(
        recaudoId: asInt(j['recaudo_id']) ?? 0,
        busId: asInt(j['bus_id']) ?? 0,
        fecha: Fechas.normalizar(j['fecha']),
        orden: asInt(j['orden']) ?? 1,
        conductor: asStr(j['conductor_nombre']),
        ruta: asStr(j['ruta_nombre']),
        viajes: asInt(j['viajes']),
        pasajeros: asInt(j['pasajeros']) ?? 0,
        producido: asInt(j['producido']) ?? 0,
        totalGastos: asInt(j['total_gastos']) ?? 0,
        recaudado: asInt(j['recaudado']) ?? 0,
        diferencia: asInt(j['diferencia']) ?? 0,
      );
}

/// Totales de recaudo (de un bus, una semana, un mes…).
class ResumenRecaudo {
  final int dias;
  final int producido;
  final int totalGastos;
  final int recaudado;
  final int diferencia;
  const ResumenRecaudo({
    this.dias = 0,
    this.producido = 0,
    this.totalGastos = 0,
    this.recaudado = 0,
    this.diferencia = 0,
  });

  /// Suma las filas; [dias] cuenta los días liquidados (bus + fecha) distintos.
  factory ResumenRecaudo.de(Iterable<TramoDiario> filas) {
    var producido = 0, gastos = 0, recaudado = 0, diferencia = 0;
    final dias = <String>{};
    for (final t in filas) {
      producido += t.producido;
      gastos += t.totalGastos;
      recaudado += t.recaudado;
      diferencia += t.diferencia;
      dias.add('${t.busId}|${t.fecha}');
    }
    return ResumenRecaudo(
      dias: dias.length,
      producido: producido,
      totalGastos: gastos,
      recaudado: recaudado,
      diferencia: diferencia,
    );
  }
}

/// Filas de [filas] entre [desde] y [hasta] (fechas ISO, ambas incluidas).
Iterable<TramoDiario> entreFechas(Iterable<TramoDiario> filas, String desde, String hasta) =>
    filas.where((t) => t.fecha.compareTo(desde) >= 0 && t.fecha.compareTo(hasta) <= 0);

/// Cómo quedó la entrega: (texto, nivel) con nivel -1 faltante, 0 cuadrado, 1 sobrante.
(String, int) estadoDiferencia(int diferencia) {
  if (diferencia < 0) return ('Faltante ${pesos(-diferencia)}', -1);
  if (diferencia > 0) return ('Sobrante ${pesos(diferencia)}', 1);
  return ('Cuadrado', 0);
}

/// Recaudo por bus, día y conductor de los buses de la cuenta (hasta 366 días).
/// null = recaudo no habilitado (403).
Future<List<TramoDiario>?> recaudoDiario(ApiClient api, String desde, String hasta) async {
  try {
    final j = await api.get('/recaudo/propietario/diario', query: {'desde': desde, 'hasta': hasta});
    return asLista(j is Map ? j['filas'] : null).map(TramoDiario.fromJson).toList();
  } on ApiException catch (e) {
    if (e.statusCode == 403) return null;
    rethrow;
  }
}

/// Liquidaciones vigentes de un bus entre dos fechas (máximo 92 días), por fecha.
/// null = recaudo no habilitado (403).
Future<Map<String, Liquidacion>?> liquidacionesBus(ApiClient api, int busId, String desde, String hasta) async {
  try {
    final j = await api.get('/recaudo/propietario', query: {'bus_id': busId, 'desde': desde, 'hasta': hasta});
    return {
      for (final l in asLista(j is Map ? j['liquidaciones'] : null).map(Liquidacion.fromJson)) l.fecha: l,
    };
  } on ApiException catch (e) {
    if (e.statusCode == 403) return null;
    rethrow;
  }
}
