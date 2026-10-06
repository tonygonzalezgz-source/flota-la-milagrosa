import 'package:flutter/material.dart';

/// Catálogo de módulos. La `clave` es la misma vista que usa el backend en
/// `ROLE_VIEWS` (api/app.py): el menú de cada usuario se arma con su
/// `allowedViews`, así los permisos se siguen administrando en un solo lugar.
class Modulo {
  final String clave;
  final String titulo;
  final IconData icono;
  final Color color;

  /// Ruta de la pantalla nativa, o null si el módulo aún solo existe en la web
  /// (Fase 2: se abrirá dentro de la app).
  final String? ruta;

  const Modulo(this.clave, this.titulo, this.icono, this.color, [this.ruta]);

  bool get nativo => ruta != null;
}

const modulos = <Modulo>[
  // ── Fase 1: nativos ──
  Modulo('despacho', 'Despacho', Icons.fact_check_outlined, Color(0xFF22C55E), '/despacho'),
  Modulo('alistamiento', 'Alistamiento', Icons.checklist_rtl, Color(0xFF22C55E), '/alistamiento'),
  Modulo('chequeo', 'Chequeo', Icons.where_to_vote_outlined, Color(0xFF6366F1), '/chequeo'),
  Modulo('mb-mapa', 'Mapa en vivo', Icons.map_outlined, Color(0xFFF87171), '/mapa-vivo'),
  Modulo('propietario', 'Mis Buses', Icons.directions_bus_outlined, Color(0xFF3B82F6), '/propietario'),
  Modulo('gastos', 'Gastos y Facturas', Icons.receipt_long_outlined, Color(0xFFF59E0B), '/gastos'),
  Modulo('tecnologia', 'Disp. Tecnológicos', Icons.videocam_outlined, Color(0xFF8B5CF6), '/tecnologia'),
  Modulo('eds', 'Operador EDS', Icons.local_gas_station_outlined, Color(0xFF0EA5E9), '/eds'),
  Modulo('lavada', 'Lavada Primeriada', Icons.water_drop_outlined, Color(0xFF06B6D4), '/lavada'),
  // ── Fase 2: por ahora solo en la web ──
  Modulo('dashboard', 'Dashboard', Icons.dashboard_outlined, Color(0xFF6366F1)),
  Modulo('historial', 'Historial Movilidad', Icons.calendar_month_outlined, Color(0xFF6366F1)),
  Modulo('historial-despacho', 'Historial Despacho', Icons.event_note_outlined, Color(0xFF22C55E)),
  Modulo('mant', 'Mantenimiento', Icons.build_outlined, Color(0xFFF59E0B)),
  Modulo('catalogo', 'Catálogo', Icons.menu_book_outlined, Color(0xFF64748B)),
  Modulo('mapa', 'Config GPS', Icons.gps_fixed, Color(0xFFF87171)),
  Modulo('relojes', 'Puntos de Control', Icons.timer_outlined, Color(0xFFF87171)),
  Modulo('mb-rutas', 'Rutas Geográficas', Icons.route_outlined, Color(0xFFF87171)),
  Modulo('mb-equipos', 'Equipos GPS', Icons.router_outlined, Color(0xFFF87171)),
];

/// Módulos visibles para un usuario, en el orden del catálogo.
List<Modulo> modulosDe(List<String> allowedViews) =>
    modulos.where((m) => allowedViews.contains(m.clave)).toList();

/// ¿El usuario puede abrir la pantalla nativa en [ruta]?
bool puedeAbrir(List<String> allowedViews, String ruta) {
  final m = modulos.where((m) => m.ruta == ruta);
  if (m.isEmpty) return true;
  return allowedViews.contains(m.first.clave);
}
