/// Lectura tolerante de los JSON del backend: SQLite y Postgres no siempre
/// devuelven los mismos tipos (enteros como string, 0/1 como bool, etc.).
int? asInt(dynamic v) {
  if (v == null) return null;
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is bool) return v ? 1 : 0;
  return int.tryParse(v.toString());
}

double? asDouble(dynamic v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

bool asBool(dynamic v) {
  if (v == null) return false;
  if (v is bool) return v;
  if (v is num) return v != 0;
  return v.toString() == 'true' || v.toString() == '1';
}

String asStr(dynamic v) => v?.toString() ?? '';

List<Map<String, dynamic>> asLista(dynamic v) =>
    (v as List? ?? const []).cast<Map<String, dynamic>>();

/// Bus tal como lo devuelve `/api/buses`.
class Bus {
  final int id;
  final String numero;
  final String placa;
  final String modelo;
  final String grupo; // 'A' = buses, 'B' = micros

  const Bus({
    required this.id,
    required this.numero,
    required this.placa,
    required this.modelo,
    required this.grupo,
  });

  factory Bus.fromJson(Map<String, dynamic> j) => Bus(
        id: asInt(j['id'])!,
        numero: asStr(j['numero']),
        placa: asStr(j['placa']),
        modelo: asStr(j['modelo']),
        grupo: asStr(j['grupo']).isEmpty ? 'A' : asStr(j['grupo']),
      );

  String get etiqueta => placa.isEmpty ? 'Bus $numero' : 'Bus $numero · $placa';
}

String grupoLabel(String g) => g == 'B' ? 'Micros' : 'Buses';

/// Formato de pesos colombianos: $ 1.234.567
String pesos(num? v) {
  if (v == null) return '—';
  final s = v.round().abs().toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write('.');
    b.write(s[i]);
  }
  return '${v < 0 ? '-' : ''}\$ $b';
}

/// Entero con separador de miles: 12.345
String miles(num? v) => v == null ? '—' : pesos(v).replaceFirst('\$ ', '');
