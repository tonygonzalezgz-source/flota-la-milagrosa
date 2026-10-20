import 'dart:ui';

import '../../core/modelos.dart';

/// Rutas del mapa en vivo con las mismas reglas de monitoreo-mapa.html.

typedef Punto = ({double lat, double lon});

/// Paleta de respaldo cuando una ruta no tiene color o lo repite otra.
const paletaRutas = [
  Color(0xFFE11D48),
  Color(0xFF2563EB),
  Color(0xFF16A34A),
  Color(0xFFD97706),
  Color(0xFF7C3AED),
  Color(0xFF0891B2),
  Color(0xFFDB2777),
  Color(0xFF65A30D),
];

/// Con una sola ruta en pantalla se pinta por sentido (igual que Rutas Geográficas).
const colorIda = Color(0xFF2563EB);
const colorRegreso = Color(0xFFEA580C);
const colorAmbos = Color(0xFF7C3AED);
const nombreSentido = {'ida': 'Ida', 'regreso': 'Regreso', 'ambos': 'Ida y regreso'};

Color? colorHex(String? h) {
  if (h == null || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(h)) return null;
  return Color(int.parse('FF${h.substring(1)}', radix: 16));
}

/// Mezcla [c] con blanco (f = 0..1): el regreso va en el tono claro de la ruta.
Color aclarar(Color c, double f) {
  int mezcla(double v) => ((v * 255) + (255 - v * 255) * f).round().clamp(0, 255);
  return Color.fromARGB(255, mezcla(c.r), mezcla(c.g), mezcla(c.b));
}

class RutaMapa {
  final int id;
  final String nombre;
  final String? color;

  /// 'ida' / 'regreso' → puntos del trazado.
  final Map<String, List<Punto>> trazados;

  /// Puntos de control (orden, nombre, alias, lat, lon, radio_m, sentido, tipo…).
  final List<Map<String, dynamic>> puntos;

  const RutaMapa(this.id, this.nombre, this.color, this.trazados, this.puntos);

  bool get tieneTrazado => trazados.isNotEmpty;

  /// Une `/api/monitoreo/rutas` (todas las rutas activas) con
  /// `/api/monitoreo/rutas/geometria` (trazados y puntos de las que los tienen).
  static List<RutaMapa> desde(List<Map<String, dynamic>> lista, List<Map<String, dynamic>> geometria) {
    final geo = {for (final g in geometria) asInt(g['ruta_id']): g};
    final base = lista.isNotEmpty
        ? lista
        : [for (final g in geometria) {'id': g['ruta_id'], 'nombre': g['nombre'], 'color': g['color']}];
    return [
      for (final r in base)
        if (asInt(r['id']) case final id?)
          RutaMapa(
            id,
            asStr(r['nombre']),
            r['color'] as String?,
            {
              for (final e in ((geo[id]?['trazados'] as Map?) ?? {}).entries)
                e.key as String: [
                  for (final p in ((e.value as Map)['puntos'] as List? ?? []))
                    (lat: asDouble(p[0])!, lon: asDouble(p[1])!),
                ],
            },
            [for (final p in (geo[id]?['puntos'] as List? ?? [])) Map<String, dynamic>.from(p as Map)],
          ),
    ];
  }
}

/// Color de cada ruta: el suyo si es válido y nadie más lo usa; si no, el
/// primero libre de la paleta.
Map<int, Color> coloresRutas(List<RutaMapa> rutas) {
  final out = <int, Color>{};
  final usados = <Color>{};
  for (final (i, r) in rutas.indexed) {
    var c = colorHex(r.color);
    if (c == null || usados.contains(c)) {
      c = paletaRutas.firstWhere((p) => !usados.contains(p), orElse: () => paletaRutas[i % paletaRutas.length]);
    }
    usados.add(c);
    out[r.id] = c;
  }
  return out;
}

/// Buses que se ven con la ruta elegida (null = todas): los despachados hoy en ella.
List<Map<String, dynamic>> busesDeRuta(List<Map<String, dynamic>> buses, int? ruta) =>
    ruta == null ? buses : [for (final b in buses) if (asInt(b['ruta_id']) == ruta) b];

/// Buses activos hoy por ruta (para el selector).
Map<int, int> busesPorRuta(List<Map<String, dynamic>> buses) {
  final out = <int, int>{};
  for (final b in buses) {
    if (asInt(b['ruta_id']) case final r?) out[r] = (out[r] ?? 0) + 1;
  }
  return out;
}
