import 'package:intl/intl.dart';

/// Utilidades de fecha. La operación es en Colombia (UTC-5, sin horario de
/// verano): el día cambia a la medianoche local, igual que en el backend
/// (`hoy_bogota()` en api/app.py), aunque el celular tenga otra zona horaria.
class Fechas {
  static DateTime ahoraBogota() =>
      DateTime.now().toUtc().subtract(const Duration(hours: 5));

  /// Fecha de hoy en Bogotá como 'YYYY-MM-DD'.
  static String hoy() => iso(ahoraBogota());

  static String iso(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  static String haceDias(int dias) =>
      iso(ahoraBogota().subtract(Duration(days: dias)));

  static String primerDiaMes() {
    final a = ahoraBogota();
    return iso(DateTime(a.year, a.month, 1));
  }

  /// Normaliza lo que manda el backend: SQLite da 'YYYY-MM-DD', Postgres a
  /// veces RFC 2822 ('Fri, 15 Aug 2025 00:00:00 GMT'). Devuelve '' si no se
  /// puede interpretar.
  static String normalizar(dynamic v) {
    if (v == null) return '';
    final s = v.toString();
    final m = RegExp(r'^\d{4}-\d{2}-\d{2}').firstMatch(s);
    if (m != null) return m.group(0)!;
    try {
      final d = HttpDateLike.parse(s);
      return iso(d);
    } catch (_) {
      return '';
    }
  }

  static DateTime? parse(dynamic v) {
    final s = normalizar(v);
    if (s.isEmpty) return null;
    return DateTime.parse(s);
  }

  /// 'lunes, 6 de octubre de 2026'
  static String larga(String isoFecha) {
    final d = parse(isoFecha);
    if (d == null) return isoFecha;
    return DateFormat("EEEE, d 'de' MMMM 'de' y", 'es_CO').format(d);
  }

  /// '06/10/2026'
  static String corta(dynamic v) {
    final d = parse(v);
    if (d == null) return '—';
    return DateFormat('dd/MM/yyyy', 'es_CO').format(d);
  }

  /// Días desde hoy (Bogotá) hasta la fecha; negativo si ya pasó.
  static int? diasHasta(dynamic v) {
    final d = parse(v);
    if (d == null) return null;
    final h = DateTime.parse(hoy());
    return d.difference(h).inDays;
  }
}

/// Parser mínimo de fechas RFC 2822 / HTTP-date ('Fri, 15 Aug 2025 00:00:00 GMT').
class HttpDateLike {
  static const _meses = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
  };

  static DateTime parse(String s) {
    final m = RegExp(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})').firstMatch(s);
    if (m == null) throw FormatException('Fecha no reconocida: $s');
    final mes = _meses[m.group(2)!.toLowerCase()];
    if (mes == null) throw FormatException('Mes no reconocido: $s');
    return DateTime(int.parse(m.group(3)!), mes, int.parse(m.group(1)!));
  }
}
