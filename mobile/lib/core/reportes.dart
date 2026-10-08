import 'fechas.dart';
import 'modelos.dart';
import 'movilidad.dart';

/// Reporte de movilidad para el propietario, el mismo de "Reporte" en
/// historial-movilidad.html más los días trabajados de cada bus:
///   - Movilidad: filas de `/api/movilidad/rango`.
///   - Estado del día (trabajando / taller / descanso): `/api/despacho/historial`.

/// Rango de fechas del reporte ('YYYY-MM-DD', ambos incluidos).
typedef Rango = ({String desde, String hasta});

/// Periodos rápidos; ninguno pasa de hoy.
enum Periodo {
  semana('Esta semana'),
  mes('Este mes'),
  mesAnterior('Mes anterior'),
  personalizado('Otro rango');

  final String nombre;
  const Periodo(this.nombre);

  Rango rango({DateTime? hoy}) {
    final h = hoy ?? DateTime.parse(Fechas.hoy());
    switch (this) {
      case Periodo.semana:
        return (desde: Fechas.iso(lunesDe(h)), hasta: Fechas.iso(h));
      case Periodo.mes:
      case Periodo.personalizado:
        return (desde: Fechas.iso(DateTime(h.year, h.month, 1)), hasta: Fechas.iso(h));
      case Periodo.mesAnterior:
        return (
          desde: Fechas.iso(DateTime(h.year, h.month - 1, 1)),
          hasta: Fechas.iso(DateTime(h.year, h.month, 0)),
        );
    }
  }
}

enum EstadoDia {
  trabajado('Trabajó'),
  taller('Taller'),
  descanso('Descanso'),
  sinRegistro('Sin registro');

  final String nombre;
  const EstadoDia(this.nombre);
}

/// Conductor y ruta efectivos como en el reporte web: manda el despacho y el
/// registro de movilidad es respaldo.
String conductorReporte(Map<String, dynamic> f) {
  final d = asStr(f['despacho_conductor_nombre']);
  return d.isNotEmpty ? d : asStr(f['conductor_nombre']);
}

String rutaReporte(Map<String, dynamic> f) {
  final d = asStr(f['despacho_ruta_nombre']);
  return d.isNotEmpty ? d : asStr(f['ruta_nombre']);
}

/// Totales de un grupo (bus, ruta o conductor).
class Totales {
  int vueltas = 0;
  int pasajeros = 0;
  double km = 0;
  final Set<String> dias = {};
  final Set<int> buses = {};

  void sumar(Map<String, dynamic> f) {
    vueltas += asInt(f['vueltas']) ?? 0;
    pasajeros += asInt(f['pasajeros']) ?? 0;
    km += asDouble(f['km_recorridos']) ?? 0;
    dias.add(Fechas.normalizar(f['fecha']));
    if (asInt(f['bus_id']) case final b?) buses.add(b);
  }

  int get dinero => dineroLiquidar(pasajeros);
  double get ipkValor => ipk(pasajeros, km);

  /// Pasajeros por vuelta (0 si no hubo vueltas).
  double get pasajerosPorVuelta => vueltas == 0 ? 0 : pasajeros / vueltas;
}

class ReporteBus {
  final int id;
  final String numero;
  final String placa;
  final Totales totales = Totales();

  /// Estado de cada día del rango (fecha → estado).
  final Map<String, EstadoDia> dias = {};

  ReporteBus(this.id, this.numero, this.placa);

  String get nombre => 'Bus $numero${placa.isEmpty ? '' : ' · $placa'}';
  int cuantos(EstadoDia e) => dias.values.where((x) => x == e).length;

  /// Promedio de pasajeros por día trabajado.
  double get pasajerosPorDia {
    final t = cuantos(EstadoDia.trabajado);
    return t == 0 ? 0 : totales.pasajeros / t;
  }
}

class Reporte {
  final Rango rango;

  /// Días del rango (hasta hoy como máximo).
  final List<String> fechas;
  final List<ReporteBus> buses;
  final Totales total;
  final Map<String, Totales> porRuta;
  final Map<String, Totales> porConductor;

  /// Filas de movilidad del rango, de la más reciente a la más antigua.
  final List<Map<String, dynamic>> diario;

  /// false si no se pudo leer el despacho: los días sin movilidad quedan como
  /// "sin registro" porque no se sabe si fueron taller o descanso.
  final bool conDespacho;

  Reporte._(this.rango, this.fechas, this.buses, this.total, this.porRuta, this.porConductor, this.diario,
      this.conDespacho);

  int get diasPeriodo => fechas.length;
  int cuantos(EstadoDia e) => buses.fold(0, (s, b) => s + b.cuantos(e));

  /// Arma el reporte. [buses] son los vehículos visibles (de `/api/buses`),
  /// [movilidad] las filas de `/api/movilidad/rango` y [despacho] las de
  /// `/api/despacho/historial` (null si no se pudo consultar). Con [busId] el
  /// reporte queda de un solo bus.
  factory Reporte.armar({
    required Rango rango,
    required List<Map<String, dynamic>> buses,
    required List<Map<String, dynamic>> movilidad,
    List<Map<String, dynamic>>? despacho,
    int? busId,
    DateTime? hoy,
  }) {
    final hoyIso = Fechas.iso(hoy ?? DateTime.parse(Fechas.hoy()));
    final hasta = rango.hasta.compareTo(hoyIso) > 0 ? hoyIso : rango.hasta;
    final fechas = <String>[];
    for (var d = DateTime.parse(rango.desde); !d.isAfter(DateTime.parse(hasta)); d = d.add(const Duration(days: 1))) {
      fechas.add(Fechas.iso(d));
    }

    final reportes = <ReporteBus>[
      for (final b in buses)
        if (busId == null || asInt(b['id']) == busId) ReporteBus(asInt(b['id']) ?? 0, asStr(b['numero']), asStr(b['placa'])),
    ]..sort((a, b) => (int.tryParse(a.numero) ?? 0).compareTo(int.tryParse(b.numero) ?? 0));
    final porId = {for (final r in reportes) r.id: r};
    final porNumero = {for (final r in reportes) r.numero: r};
    ReporteBus? deFila(Map<String, dynamic> f) => porId[asInt(f['bus_id'])] ?? porNumero[asStr(f['numero'])];

    // Movilidad del rango, solo de los buses del reporte.
    final total = Totales();
    final porRuta = <String, Totales>{};
    final porConductor = <String, Totales>{};
    final diario = <Map<String, dynamic>>[];
    final movilidadDia = <String, Map<String, dynamic>>{}; // 'busId|fecha'
    for (final f in movilidad) {
      final r = deFila(f);
      final fecha = Fechas.normalizar(f['fecha']);
      if (r == null || !fechas.contains(fecha)) continue;
      r.totales.sumar(f);
      total.sumar(f);
      final ruta = rutaReporte(f);
      final conductor = conductorReporte(f);
      porRuta.putIfAbsent(ruta.isEmpty ? 'Sin ruta' : ruta, Totales.new).sumar(f);
      porConductor.putIfAbsent(conductor.isEmpty ? 'Sin conductor' : conductor, Totales.new).sumar(f);
      diario.add(f);
      movilidadDia['${r.id}|$fecha'] = f;
    }
    diario.sort((a, b) {
      final c = Fechas.normalizar(b['fecha']).compareTo(Fechas.normalizar(a['fecha']));
      return c != 0 ? c : (int.tryParse(asStr(a['numero'])) ?? 0).compareTo(int.tryParse(asStr(b['numero'])) ?? 0);
    });

    // Estado del despacho por bus y día.
    final estadoDespacho = <String, String>{};
    for (final d in despacho ?? const <Map<String, dynamic>>[]) {
      final r = deFila(d);
      final estado = asStr(d['estado']);
      if (r == null || estado.isEmpty) continue;
      estadoDespacho['${r.id}|${Fechas.normalizar(d['fecha'])}'] = estado;
    }

    // Un día cuenta como trabajado si tiene movilidad (vueltas o pasajeros) o
    // si el despacho lo marcó "trabajando"; si no, manda el estado del despacho.
    for (final r in reportes) {
      for (final fecha in fechas) {
        final m = movilidadDia['${r.id}|$fecha'];
        final conMovilidad = m != null && ((asInt(m['vueltas']) ?? 0) > 0 || (asInt(m['pasajeros']) ?? 0) > 0);
        r.dias[fecha] = switch (estadoDespacho['${r.id}|$fecha']) {
          _ when conMovilidad => EstadoDia.trabajado,
          'trabajando' => EstadoDia.trabajado,
          'taller' => EstadoDia.taller,
          'descanso' => EstadoDia.descanso,
          _ => EstadoDia.sinRegistro,
        };
      }
    }

    Map<String, Totales> ordenado(Map<String, Totales> m) => Map.fromEntries(
          m.entries.toList()..sort((a, b) => b.value.pasajeros.compareTo(a.value.pasajeros)),
        );

    return Reporte._(
      (desde: rango.desde, hasta: hasta),
      fechas,
      reportes,
      total,
      ordenado(porRuta),
      ordenado(porConductor),
      diario,
      despacho != null,
    );
  }
}
