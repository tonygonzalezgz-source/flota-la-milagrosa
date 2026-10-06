import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:latlong2/latlong.dart';

import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';

/// Estados del bus que calcula /api/monitoreo/vivo (mismos colores que monitoreo-mapa.html).
const estadosGps = {
  'movimiento': ('En movimiento', Color(0xFF16A34A)),
  'detenido': ('Detenido', Color(0xFFD97706)),
  'sin_fix': ('Sin fix GPS', Color(0xFF9333EA)),
  'sin_senal': ('Sin señal', Color(0xFF6B7280)),
  'encierro': ('En encierro', Color(0xFF92400E)),
  'alarma': ('En alarma', Color(0xFFDC2626)),
};

/// Capas gratuitas de Esri, las mismas de la web (sin API key).
const _esri = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const _capas = {
  'Calles': '$_esri/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
  'Satélite': '$_esri/World_Imagery/MapServer/tile/{z}/{y}/{x}',
};

const _refresco = Duration(seconds: 15); // el equipo reporta cada 30 s
const _centroDefecto = LatLng(4.6097, -74.0817);

Color _hex(String? h, Color def) {
  if (h == null || !h.startsWith('#') || h.length != 7) return def;
  return Color(int.parse('FF${h.substring(1)}', radix: 16));
}

/// Mapa en vivo: última posición de cada bus con GPS y el trazado de sus rutas.
class MapaVivoScreen extends ConsumerStatefulWidget {
  const MapaVivoScreen({super.key});

  @override
  ConsumerState<MapaVivoScreen> createState() => _MapaVivoScreenState();
}

class _MapaVivoScreenState extends ConsumerState<MapaVivoScreen> {
  final _map = MapController();
  Timer? _timer;
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<Map<String, dynamic>> _rutas = [];
  String _capa = 'Calles';
  bool _encuadrado = false;
  DateTime? _actualizado;

  @override
  void initState() {
    super.initState();
    _cargarTodo();
    _timer = Timer.periodic(_refresco, (_) => _cargarVivo());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _cargarTodo() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      _rutas = asLista(await ref.read(apiClientProvider).get('/monitoreo/rutas/geometria'));
    } catch (_) {
      _rutas = []; // sin trazados el mapa sigue siendo útil
    }
    await _cargarVivo();
    if (mounted) setState(() => _cargando = false);
  }

  Future<void> _cargarVivo() async {
    try {
      final d = await ref.read(apiClientProvider).get('/monitoreo/vivo') as Map<String, dynamic>;
      _buses = asLista(d['buses']);
      _actualizado = DateTime.now();
      _error = null;
      if (!_encuadrado && !_cargando) _encuadrar();
    } catch (e) {
      // Si ya hay datos, se conservan; el error solo bloquea la primera carga.
      if (_buses.isEmpty) _error = e.toString();
    }
    if (mounted) setState(() {});
  }

  List<LatLng> get _posiciones => [
        for (final b in _buses)
          if (b['lat'] != null && b['lon'] != null) LatLng(asDouble(b['lat'])!, asDouble(b['lon'])!),
      ];

  /// Encuadra buses y trazados juntos (igual que el mapa web).
  void _encuadrar() {
    final pts = <LatLng>[..._posiciones];
    for (final r in _rutas) {
      for (final t in ((r['trazados'] as Map?) ?? {}).values) {
        for (final p in ((t as Map)['puntos'] as List? ?? [])) {
          pts.add(LatLng(asDouble(p[0])!, asDouble(p[1])!));
        }
      }
    }
    if (pts.isEmpty) return;
    _encuadrado = true;
    if (pts.length == 1) {
      _map.move(pts.first, 15);
      return;
    }
    _map.fitCamera(CameraFit.bounds(
      bounds: LatLngBounds.fromPoints(pts),
      padding: const EdgeInsets.all(40),
      maxZoom: 16,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final conteo = <String, int>{};
    for (final b in _buses) {
      conteo[asStr(b['estado'])] = (conteo[asStr(b['estado'])] ?? 0) + 1;
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mapa en vivo'),
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.layers_outlined),
            onSelected: (v) => setState(() => _capa = v),
            itemBuilder: (_) => [
              for (final c in _capas.keys) CheckedPopupMenuItem(value: c, checked: c == _capa, child: Text(c)),
            ],
          ),
          IconButton(icon: const Icon(Icons.list), tooltip: 'Lista de buses', onPressed: _lista),
        ],
      ),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargarTodo,
        builder: () => Stack(children: [
          FlutterMap(
            mapController: _map,
            options: MapOptions(
              initialCenter: _posiciones.isNotEmpty ? _posiciones.first : _centroDefecto,
              initialZoom: 13,
              maxZoom: 20,
              onMapReady: _encuadrar,
            ),
            children: [
              TileLayer(
                urlTemplate: _capas[_capa],
                maxNativeZoom: 19,
                userAgentPackageName: 'co.lamilagrosa.buscontrol',
              ),
              PolylineLayer(polylines: [
                for (final r in _rutas)
                  for (final e in ((r['trazados'] as Map?) ?? {}).entries)
                    Polyline(
                      points: [
                        for (final p in ((e.value as Map)['puntos'] as List? ?? []))
                          LatLng(asDouble(p[0])!, asDouble(p[1])!),
                      ],
                      color: _hex(r['color'] as String?, AppColors.primary)
                          .withValues(alpha: e.key == 'regreso' ? .55 : .9),
                      strokeWidth: 4,
                    ),
              ]),
              MarkerLayer(markers: [
                for (final b in _buses)
                  if (b['lat'] != null && b['lon'] != null)
                    Marker(
                      point: LatLng(asDouble(b['lat'])!, asDouble(b['lon'])!),
                      width: 56,
                      height: 34,
                      child: GestureDetector(onTap: () => _detalle(b), child: _MarcadorBus(b)),
                    ),
              ]),
              const RichAttributionWidget(attributions: [
                TextSourceAttribution('© Esri, HERE, Garmin, OpenStreetMap'),
              ]),
            ],
          ),
          Positioned(
            left: 10,
            right: 10,
            top: 10,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final e in estadosGps.entries)
                    if ((conteo[e.key] ?? 0) > 0) Etiqueta('${e.value.$1}: ${conteo[e.key]}', e.value.$2),
                  if (_buses.isEmpty) const Text('Ningún bus con GPS activo'),
                ]),
              ),
            ),
          ),
          Positioned(
            right: 12,
            bottom: 56,
            child: FloatingActionButton.small(
              heroTag: 'encuadrar',
              tooltip: 'Encuadrar',
              onPressed: _encuadrar,
              child: const Icon(Icons.center_focus_strong),
            ),
          ),
          if (_actualizado != null)
            Positioned(
              left: 12,
              bottom: 28,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(color: Colors.white70, borderRadius: BorderRadius.circular(8)),
                child: Text(
                    'Actualizado ${_actualizado!.hour.toString().padLeft(2, '0')}:${_actualizado!.minute.toString().padLeft(2, '0')}:${_actualizado!.second.toString().padLeft(2, '0')}',
                    style: const TextStyle(fontSize: 11)),
              ),
            ),
        ]),
      ),
    );
  }

  void _detalle(Map<String, dynamic> b) {
    final est = estadosGps[b['estado']];
    showModalBottomSheet(
      context: context,
      builder: (_) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text('Bus ${b['numero']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const SizedBox(width: 8),
            Text(asStr(b['placa']), style: const TextStyle(color: AppColors.muted)),
            const Spacer(),
            if (est != null) Etiqueta(est.$1, est.$2),
          ]),
          const SizedBox(height: 12),
          _dato('Ruta', asStr(b['ruta_nombre']).isEmpty ? 'Sin ruta asignada hoy' : asStr(b['ruta_nombre'])),
          _dato('Velocidad', '${(asDouble(b['velocidad_kmh']) ?? 0).round()} km/h'),
          if (b['encierro'] != null) _dato('Encierro', asStr(b['encierro'])),
          _dato('Último reporte', _haceCuanto(b['ultimo_reporte_at'])),
          if (b['satelites'] != null) _dato('Satélites', asStr(b['satelites'])),
        ]),
      ),
    );
  }

  Widget _dato(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          SizedBox(width: 120, child: Text(k, style: const TextStyle(color: AppColors.muted))),
          Expanded(child: Text(v, style: const TextStyle(fontWeight: FontWeight.w600))),
        ]),
      );

  String _haceCuanto(dynamic iso) {
    final d = DateTime.tryParse(asStr(iso));
    if (d == null) return '—';
    final s = DateTime.now().toUtc().difference(d.toUtc()).inSeconds;
    if (s < 60) return 'hace $s s';
    if (s < 3600) return 'hace ${s ~/ 60} min';
    if (s < 86400) return 'hace ${s ~/ 3600} h';
    return 'hace ${s ~/ 86400} días';
  }

  void _lista() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => SizedBox(
        height: MediaQuery.sizeOf(context).height * .6,
        child: _buses.isEmpty
            ? const VacioView('Ningún bus con GPS activo.')
            : ListView(children: [
                for (final b in _buses)
                  ListTile(
                    leading: CircleAvatar(
                      radius: 8,
                      backgroundColor: estadosGps[b['estado']]?.$2 ?? AppColors.muted,
                    ),
                    title: Text('Bus ${b['numero']} · ${asStr(b['placa'])}'),
                    subtitle: Text(
                        '${estadosGps[b['estado']]?.$1 ?? b['estado']} · ${asStr(b['ruta_nombre']).isEmpty ? 'Sin ruta' : b['ruta_nombre']}'),
                    onTap: b['lat'] == null
                        ? null
                        : () {
                            Navigator.pop(context);
                            _map.move(LatLng(asDouble(b['lat'])!, asDouble(b['lon'])!), 17);
                          },
                  ),
              ]),
      ),
    );
  }
}

class _MarcadorBus extends StatelessWidget {
  final Map<String, dynamic> b;
  const _MarcadorBus(this.b);

  @override
  Widget build(BuildContext context) {
    final color = estadosGps[b['estado']]?.$2 ?? AppColors.muted;
    return Container(
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white, width: 2),
        boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 4)],
      ),
      child: Text('${b['numero']}',
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
    );
  }
}
