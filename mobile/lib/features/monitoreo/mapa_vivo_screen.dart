import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart' as gm;
import 'package:latlong2/latlong.dart';

import '../../core/config.dart';
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

/// Estilos del mapa, los mismos de la web. Con clave de Google (ver
/// [AppConfig.googleMapsKey]) se dibujan con Google Maps; sin ella, con las
/// capas gratuitas de Esri que la web usa de respaldo.
enum EstiloMapa {
  calles('Calles'),
  claro('Claro'),
  satelite('Satélite'),
  oscuro('Oscuro');

  final String nombre;
  const EstiloMapa(this.nombre);
}

// ── Google Maps: mismos estilos que GOOGLE_ESTILOS de monitoreo-mapa.html ──
const _googleClaro = '[{"stylers":[{"saturation":-100},{"lightness":30}]},'
    '{"featureType":"poi","stylers":[{"visibility":"off"}]}]';
const _googleOscuro = '['
    '{"elementType":"geometry","stylers":[{"color":"#242f3e"}]},'
    '{"elementType":"labels.text.stroke","stylers":[{"color":"#242f3e"}]},'
    '{"elementType":"labels.text.fill","stylers":[{"color":"#8a8f98"}]},'
    '{"featureType":"road","elementType":"geometry","stylers":[{"color":"#38414e"}]},'
    '{"featureType":"road","elementType":"geometry.stroke","stylers":[{"color":"#212a37"}]},'
    '{"featureType":"road","elementType":"labels.text.fill","stylers":[{"color":"#9ca5b3"}]},'
    '{"featureType":"water","elementType":"geometry","stylers":[{"color":"#17263c"}]},'
    '{"featureType":"poi","stylers":[{"visibility":"off"}]}'
    ']';

// ── Esri: mismas capas que MAP_STYLES de monitoreo-mapa.html ──
const _esri = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const _atribEsri = '© Esri, HERE, Garmin, OpenStreetMap';
const _capasEsri = {
  EstiloMapa.calles: (url: '$_esri/World_Street_Map/MapServer/tile/{z}/{y}/{x}', etiquetas: null, maxNativo: 19, atrib: _atribEsri),
  EstiloMapa.claro: (
    url: '$_esri/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    etiquetas: '$_esri/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    maxNativo: 16,
    atrib: _atribEsri,
  ),
  EstiloMapa.satelite: (
    url: '$_esri/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    etiquetas: null,
    maxNativo: 19,
    atrib: '© Esri, Maxar, Earthstar Geographics',
  ),
  EstiloMapa.oscuro: (
    url: '$_esri/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    etiquetas: '$_esri/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    maxNativo: 16,
    atrib: _atribEsri,
  ),
};

const _refresco = Duration(seconds: 15); // el equipo reporta cada 30 s
const _centroDefecto = (lat: 4.6097, lon: -74.0817);

typedef Punto = ({double lat, double lon});

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
  /// Estilo elegido; se recuerda mientras la app esté abierta.
  static EstiloMapa _estiloRecordado = EstiloMapa.calles;
  static bool _alternoRecordado = false;

  final _esriCtl = MapController();
  gm.GoogleMapController? _googleCtl;
  bool _esriListo = false;

  Timer? _timer;
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<Map<String, dynamic>> _rutas = [];
  EstiloMapa _estilo = _estiloRecordado;

  /// Forzar Esri aunque haya clave (por si Google rechaza la clave).
  bool _alterno = _alternoRecordado;
  bool _encuadrado = false;
  DateTime? _actualizado;

  /// Íconos de bus ya dibujados para Google Maps (número + color).
  final Map<String, gm.BitmapDescriptor> _iconos = {};

  bool get _usarGoogle => AppConfig.googleMapsKey.isNotEmpty && !_alterno;

  @override
  void initState() {
    super.initState();
    _cargarTodo();
    _timer = Timer.periodic(_refresco, (_) => _cargarVivo());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _googleCtl?.dispose();
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
      if (_usarGoogle) await _prepararIconos();
      if (!_encuadrado) _encuadrar();
    } catch (e) {
      // Si ya hay datos, se conservan; el error solo bloquea la primera carga.
      if (_buses.isEmpty) _error = e.toString();
    }
    if (mounted) setState(() {});
  }

  Punto? _posicion(Map<String, dynamic> b) {
    final lat = asDouble(b['lat']), lon = asDouble(b['lon']);
    return lat == null || lon == null ? null : (lat: lat, lon: lon);
  }

  List<Punto> get _posiciones => [for (final b in _buses) ?_posicion(b)];

  /// Trazados de las rutas: (id, color, puntos) por ida y regreso.
  Iterable<({String id, Color color, List<Punto> puntos})> get _trazados sync* {
    for (final r in _rutas) {
      for (final e in ((r['trazados'] as Map?) ?? {}).entries) {
        yield (
          id: '${r['ruta_id']}-${e.key}',
          color: _hex(r['color'] as String?, AppColors.primary).withValues(alpha: e.key == 'regreso' ? .55 : .9),
          puntos: [
            for (final p in ((e.value as Map)['puntos'] as List? ?? []))
              (lat: asDouble(p[0])!, lon: asDouble(p[1])!),
          ],
        );
      }
    }
  }

  /// Encuadra buses y trazados juntos (igual que el mapa web).
  void _encuadrar() {
    final pts = <Punto>[..._posiciones, for (final t in _trazados) ...t.puntos];
    if (pts.isEmpty) return;
    if (_usarGoogle) {
      final ctl = _googleCtl;
      if (ctl == null) return; // se encuadra en onMapCreated
      _encuadrado = true;
      _encuadrarGoogle(ctl, pts);
      return;
    }
    if (!_esriListo) return; // se encuadra en onMapReady
    _encuadrado = true;
    if (pts.length == 1) {
      _esriCtl.move(LatLng(pts.first.lat, pts.first.lon), 15);
      return;
    }
    _esriCtl.fitCamera(CameraFit.bounds(
      bounds: LatLngBounds.fromPoints([for (final p in pts) LatLng(p.lat, p.lon)]),
      padding: const EdgeInsets.all(40),
      maxZoom: 16,
    ));
  }

  Future<void> _encuadrarGoogle(gm.GoogleMapController ctl, List<Punto> pts) async {
    var s = pts.first.lat, n = s, o = pts.first.lon, e = o;
    for (final p in pts) {
      if (p.lat < s) s = p.lat;
      if (p.lat > n) n = p.lat;
      if (p.lon < o) o = p.lon;
      if (p.lon > e) e = p.lon;
    }
    // Margen mínimo (~1 km) para no acercar más que el zoom 16 de la web.
    const minimo = 0.01;
    if (n - s < minimo) {
      final c = (n + s) / 2;
      s = c - minimo / 2;
      n = c + minimo / 2;
    }
    if (e - o < minimo) {
      final c = (e + o) / 2;
      o = c - minimo / 2;
      e = c + minimo / 2;
    }
    final destino = gm.CameraUpdate.newLatLngBounds(
      gm.LatLngBounds(southwest: gm.LatLng(s, o), northeast: gm.LatLng(n, e)),
      48,
    );
    try {
      await ctl.animateCamera(destino);
    } catch (_) {
      // En Android el mapa puede no tener tamaño aún al crearse: se reintenta.
      await Future<void>.delayed(const Duration(milliseconds: 400));
      if (mounted) await ctl.moveCamera(destino);
    }
  }

  void _irA(Punto p) {
    if (_usarGoogle) {
      _googleCtl?.animateCamera(gm.CameraUpdate.newLatLngZoom(gm.LatLng(p.lat, p.lon), 17));
    } else if (_esriListo) {
      _esriCtl.move(LatLng(p.lat, p.lon), 17);
    }
  }

  void _cambiarEstilo(EstiloMapa e, {bool? alterno}) {
    final cambiaMotor = alterno != null && alterno != _alterno;
    setState(() {
      _estilo = _estiloRecordado = e;
      if (alterno != null) _alterno = _alternoRecordado = alterno;
      if (cambiaMotor) {
        // El otro mapa se crea de cero: se vuelve a encuadrar cuando esté listo.
        _encuadrado = false;
        _googleCtl = null;
        _esriListo = false;
      }
    });
    if (cambiaMotor && _usarGoogle) _prepararIconos().then((_) => mounted ? setState(() {}) : null);
  }

  // ── Íconos de bus para Google Maps (mismo diseño que el marcador de Esri) ──

  Future<void> _prepararIconos() async {
    final dpr = MediaQuery.maybeDevicePixelRatioOf(context) ?? 2;
    for (final b in _buses) {
      final color = estadosGps[b['estado']]?.$2 ?? AppColors.muted;
      final clave = '${b['numero']}|${color.toARGB32()}';
      if (!_iconos.containsKey(clave)) _iconos[clave] = await _dibujarIcono('${b['numero']}', color, dpr);
    }
  }

  gm.BitmapDescriptor _icono(Map<String, dynamic> b) {
    final color = estadosGps[b['estado']]?.$2 ?? AppColors.muted;
    return _iconos['${b['numero']}|${color.toARGB32()}'] ?? gm.BitmapDescriptor.defaultMarker;
  }

  static Future<gm.BitmapDescriptor> _dibujarIcono(String numero, Color color, double dpr) async {
    const ancho = 56.0, alto = 34.0;
    final grabadora = ui.PictureRecorder();
    final c = Canvas(grabadora)..scale(dpr);
    final caja = RRect.fromRectAndRadius(const Rect.fromLTWH(3, 3, ancho - 6, alto - 7), const Radius.circular(10));
    c.drawRRect(
      caja.shift(const Offset(0, 1.5)),
      Paint()
        ..color = Colors.black26
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2),
    );
    c.drawRRect(caja, Paint()..color = color);
    c.drawRRect(
      caja,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    final texto = TextPainter(
      text: TextSpan(
        text: numero,
        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    texto.paint(c, Offset((ancho - texto.width) / 2, (alto - 4 - texto.height) / 2 + 1));
    final imagen = await grabadora.endRecording().toImage((ancho * dpr).round(), (alto * dpr).round());
    final png = await imagen.toByteData(format: ui.ImageByteFormat.png);
    return gm.BitmapDescriptor.bytes(png!.buffer.asUint8List(), imagePixelRatio: dpr);
  }

  // ── Pantalla ──

  @override
  Widget build(BuildContext context) {
    final conteo = <String, int>{};
    for (final b in _buses) {
      conteo[asStr(b['estado'])] = (conteo[asStr(b['estado'])] ?? 0) + 1;
    }
    final hayClave = AppConfig.googleMapsKey.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mapa en vivo'),
        actions: [
          PopupMenuButton<(EstiloMapa, bool)>(
            icon: const Icon(Icons.layers_outlined),
            tooltip: 'Estilo del mapa',
            onSelected: (v) => _cambiarEstilo(v.$1, alterno: v.$2),
            itemBuilder: (_) => [
              for (final e in EstiloMapa.values)
                CheckedPopupMenuItem(value: (e, _alterno), checked: e == _estilo, child: Text(e.nombre)),
              if (hayClave) ...[
                const PopupMenuDivider(),
                CheckedPopupMenuItem(
                  value: (_estilo, !_alterno),
                  checked: _alterno,
                  child: const Text('Mapa alterno (Esri)'),
                ),
              ],
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
          _usarGoogle ? _mapaGoogle() : _mapaEsri(),
          Positioned(
            left: 10,
            right: 10,
            top: 10,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                child: Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  for (final e in estadosGps.entries)
                    if ((conteo[e.key] ?? 0) > 0) Etiqueta('${e.value.$1}: ${conteo[e.key]}', e.value.$2),
                  if (_buses.isEmpty) const Text('Ningún bus con GPS activo'),
                  if (_actualizado != null)
                    Text(
                      'Actualizado ${_actualizado!.hour.toString().padLeft(2, '0')}:'
                      '${_actualizado!.minute.toString().padLeft(2, '0')}:'
                      '${_actualizado!.second.toString().padLeft(2, '0')}',
                      style: const TextStyle(fontSize: 11, color: AppColors.muted),
                    ),
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
        ]),
      ),
    );
  }

  Widget _mapaGoogle() {
    final inicio = _posiciones.isNotEmpty ? _posiciones.first : _centroDefecto;
    return gm.GoogleMap(
      key: const ValueKey('google'),
      initialCameraPosition: gm.CameraPosition(target: gm.LatLng(inicio.lat, inicio.lon), zoom: 13),
      mapType: _estilo == EstiloMapa.satelite ? gm.MapType.hybrid : gm.MapType.normal,
      style: switch (_estilo) {
        EstiloMapa.claro => _googleClaro,
        EstiloMapa.oscuro => _googleOscuro,
        _ => null,
      },
      // Deja libre la tarjeta de estados de arriba (y el logo de Google abajo).
      padding: const EdgeInsets.only(top: 64),
      zoomControlsEnabled: false,
      mapToolbarEnabled: false,
      myLocationButtonEnabled: false,
      tiltGesturesEnabled: false,
      onMapCreated: (ctl) {
        _googleCtl = ctl;
        _encuadrar();
      },
      polylines: {
        for (final t in _trazados)
          gm.Polyline(
            polylineId: gm.PolylineId(t.id),
            points: [for (final p in t.puntos) gm.LatLng(p.lat, p.lon)],
            color: t.color,
            width: 4,
          ),
      },
      markers: {
        for (final b in _buses)
          if (_posicion(b) case final p?)
            gm.Marker(
              markerId: gm.MarkerId('bus-${b['bus_id'] ?? b['numero']}'),
              position: gm.LatLng(p.lat, p.lon),
              icon: _icono(b),
              anchor: const Offset(.5, .5),
              consumeTapEvents: true,
              onTap: () => _detalle(b),
            ),
      },
    );
  }

  Widget _mapaEsri() {
    final capa = _capasEsri[_estilo]!;
    final inicio = _posiciones.isNotEmpty ? _posiciones.first : _centroDefecto;
    return FlutterMap(
      key: const ValueKey('esri'),
      mapController: _esriCtl,
      options: MapOptions(
        initialCenter: LatLng(inicio.lat, inicio.lon),
        initialZoom: 13,
        maxZoom: 20,
        onMapReady: () {
          _esriListo = true;
          _encuadrar();
        },
      ),
      children: [
        TileLayer(urlTemplate: capa.url, maxNativeZoom: capa.maxNativo, userAgentPackageName: 'co.lamilagrosa.buscontrol'),
        if (capa.etiquetas case final etiquetas?)
          TileLayer(urlTemplate: etiquetas, maxNativeZoom: capa.maxNativo, userAgentPackageName: 'co.lamilagrosa.buscontrol'),
        PolylineLayer(polylines: [
          for (final t in _trazados)
            Polyline(points: [for (final p in t.puntos) LatLng(p.lat, p.lon)], color: t.color, strokeWidth: 4),
        ]),
        MarkerLayer(markers: [
          for (final b in _buses)
            if (_posicion(b) case final p?)
              Marker(
                point: LatLng(p.lat, p.lon),
                width: 56,
                height: 34,
                child: GestureDetector(onTap: () => _detalle(b), child: _MarcadorBus(b)),
              ),
        ]),
        RichAttributionWidget(attributions: [TextSourceAttribution(capa.atrib)]),
      ],
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
                    onTap: _posicion(b) == null
                        ? null
                        : () {
                            Navigator.pop(context);
                            _irA(_posicion(b)!);
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
