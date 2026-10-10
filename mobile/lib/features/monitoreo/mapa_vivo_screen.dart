import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart' as gm;
import 'package:intl/intl.dart' show DateFormat;
import 'package:latlong2/latlong.dart';

import '../../core/config.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import 'rutas_mapa.dart';

/// Estados del bus que calcula /api/monitoreo/vivo (mismos colores que monitoreo-mapa.html).
const estadosGps = {
  'movimiento': ('En movimiento', Color(0xFF16A34A)),
  'detenido': ('Detenido', Color(0xFFD97706)),
  'sin_fix': ('Sin fix GPS', Color(0xFF9333EA)),
  'sin_senal': ('Sin señal', Color(0xFF6B7280)),
  'encierro': ('En encierro', Color(0xFF92400E)),
  'alarma': ('En alarma', Color(0xFFDC2626)),
};
const _sinDespacho = ('Sin despacho', Color(0xFF7C3AED));

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

/// Línea de un trazado lista para dibujar.
typedef _Linea = ({String id, Color color, List<Punto> puntos, bool regreso});

/// Mapa en vivo: última posición de cada bus con GPS y el trazado de sus
/// rutas. Como en la web, se puede ver todas las rutas o una sola: con una
/// ruta elegida solo aparecen los buses despachados hoy en ella.
class MapaVivoScreen extends ConsumerStatefulWidget {
  const MapaVivoScreen({super.key});

  @override
  ConsumerState<MapaVivoScreen> createState() => _MapaVivoScreenState();
}

class _MapaVivoScreenState extends ConsumerState<MapaVivoScreen> {
  /// Estilo y ruta elegidos; se recuerdan mientras la app esté abierta.
  static EstiloMapa _estiloRecordado = EstiloMapa.calles;
  static bool _alternoRecordado = false;
  static int? _rutaRecordada;

  final _esriCtl = MapController();
  gm.GoogleMapController? _googleCtl;
  bool _esriListo = false;

  Timer? _timer;
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<RutaMapa> _rutas = [];
  Map<int, Color> _colores = {};
  EstiloMapa _estilo = _estiloRecordado;

  /// Ruta elegida (null = todas las rutas).
  int? _ruta = _rutaRecordada;

  /// Forzar Esri aunque haya clave (por si Google rechaza la clave).
  bool _alterno = _alternoRecordado;
  bool _encuadrado = false;
  DateTime? _actualizado;

  /// Íconos ya dibujados para Google Maps (buses y puntos de control).
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
    final api = ref.read(apiClientProvider);
    // Sin trazados el mapa sigue siendo útil: los errores aquí no bloquean.
    final r = await Future.wait([
      api.get('/monitoreo/rutas').then<Object?>((v) => v).catchError((_) => null),
      api.get('/monitoreo/rutas/geometria').then<Object?>((v) => v).catchError((_) => null),
    ]);
    _rutas = RutaMapa.desde(asLista(r[0]), asLista(r[1]));
    _colores = coloresRutas(_rutas);
    if (_ruta != null && !_rutas.any((x) => x.id == _ruta)) _ruta = _rutaRecordada = null;
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

  // ── Lo que se ve según la ruta elegida ──

  List<Map<String, dynamic>> get _visibles => busesDeRuta(_buses, _ruta);
  List<RutaMapa> get _rutasVisibles => _ruta == null ? _rutas : [for (final r in _rutas) if (r.id == _ruta) r];
  RutaMapa? get _rutaElegida => _ruta == null ? null : _rutas.where((r) => r.id == _ruta).firstOrNull;

  /// Con una sola ruta con trazado en pantalla se pinta por sentido.
  bool get _porSentido => _rutasVisibles.where((r) => r.tieneTrazado).length <= 1;

  List<_Linea> get _lineas => [
        for (final r in _rutasVisibles)
          for (final e in r.trazados.entries)
            (
              id: '${r.id}-${e.key}',
              color: _porSentido
                  ? (e.key == 'regreso' ? colorRegreso : colorIda)
                  : (e.key == 'regreso'
                      ? aclarar(_colores[r.id] ?? AppColors.primary, .45)
                      : _colores[r.id] ?? AppColors.primary),
              puntos: e.value,
              regreso: e.key == 'regreso',
            ),
      ];

  /// Puntos de control: solo con una ruta elegida (con todas se amontonan).
  List<Map<String, dynamic>> get _puntosControl => _rutaElegida?.puntos ?? const [];

  Color _colorPunto(Map<String, dynamic> p) =>
      switch (p['sentido']) { 'ida' => colorIda, 'regreso' => colorRegreso, 'ambos' => colorAmbos, _ => AppColors.muted };

  Punto? _posicion(Map<String, dynamic> b) {
    final lat = asDouble(b['lat']), lon = asDouble(b['lon']);
    return lat == null || lon == null ? null : (lat: lat, lon: lon);
  }

  List<Punto> get _posiciones => [for (final b in _visibles) ?_posicion(b)];

  /// Encuadra la ruta (o rutas) en pantalla junto con sus buses, como la web.
  void _encuadrar() {
    final pts = <Punto>[..._posiciones, for (final l in _lineas) ...l.puntos];
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
      padding: const EdgeInsets.fromLTRB(40, 140, 40, 40),
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

  void _cambiarRuta(int? ruta) {
    setState(() {
      _ruta = _rutaRecordada = ruta;
      _encuadrado = false;
    });
    if (_usarGoogle) {
      _prepararIconos().then((_) {
        if (mounted) setState(() {});
      });
    }
    _encuadrar();
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

  // ── Íconos para Google Maps (mismo diseño que los marcadores de Esri) ──

  Color _colorBus(Map<String, dynamic> b) => estadosGps[b['estado']]?.$2 ?? AppColors.muted;

  Future<void> _prepararIconos() async {
    final dpr = MediaQuery.maybeDevicePixelRatioOf(context) ?? 2;
    for (final b in _buses) {
      final clave = 'bus|${b['numero']}|${_colorBus(b).toARGB32()}';
      if (!_iconos.containsKey(clave)) {
        _iconos[clave] = await _dibujarIcono('${b['numero']}', _colorBus(b), dpr, ancho: 56, alto: 34, radio: 10);
      }
    }
    for (final p in _puntosControl) {
      final clave = _clavePunto(p);
      if (!_iconos.containsKey(clave)) {
        final terminal = p['tipo'] == 'terminal';
        _iconos[clave] =
            await _dibujarIcono('${p['orden']}', _colorPunto(p), dpr, ancho: 26, alto: 26, radio: terminal ? 6 : 13, letra: 11);
      }
    }
  }

  String _clavePunto(Map<String, dynamic> p) => 'pc|${p['orden']}|${p['tipo']}|${_colorPunto(p).toARGB32()}';

  gm.BitmapDescriptor _iconoBus(Map<String, dynamic> b) =>
      _iconos['bus|${b['numero']}|${_colorBus(b).toARGB32()}'] ?? gm.BitmapDescriptor.defaultMarker;

  static Future<gm.BitmapDescriptor> _dibujarIcono(String texto, Color color, double dpr,
      {required double ancho, required double alto, required double radio, double letra = 13}) async {
    final grabadora = ui.PictureRecorder();
    final c = Canvas(grabadora)..scale(dpr);
    final caja = RRect.fromRectAndRadius(Rect.fromLTWH(3, 3, ancho - 6, alto - 7), Radius.circular(radio));
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
    final tp = TextPainter(
      text: TextSpan(
        text: texto,
        style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: letra),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, Offset((ancho - tp.width) / 2, (alto - 4 - tp.height) / 2 + 1));
    final imagen = await grabadora.endRecording().toImage((ancho * dpr).round(), (alto * dpr).round());
    final png = await imagen.toByteData(format: ui.ImageByteFormat.png);
    return gm.BitmapDescriptor.bytes(png!.buffer.asUint8List(), imagePixelRatio: dpr);
  }

  // ── Pantalla ──

  @override
  Widget build(BuildContext context) {
    final hayClave = AppConfig.googleMapsKey.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mapa en vivo'),
        actions: [
          IconButton(icon: const Icon(Icons.alt_route), tooltip: 'Cambiar de ruta', onPressed: _elegirRuta),
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
          Positioned(left: 10, right: 10, top: 10, child: _tarjeta()),
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

  /// Tarjeta de arriba: ruta elegida, conteo por estado y leyenda.
  Widget _tarjeta() {
    final visibles = _visibles;
    final conteo = <String, int>{};
    for (final b in visibles) {
      conteo[asStr(b['estado'])] = (conteo[asStr(b['estado'])] ?? 0) + 1;
    }
    final sinDespacho = visibles.where((b) => b['ruta_id'] == null).length;
    final ocultos = _buses.length - visibles.length;
    final ruta = _rutaElegida;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Material(
            color: AppColors.campo,
            shape: const StadiumBorder(),
            child: InkWell(
              customBorder: const StadiumBorder(),
              onTap: _elegirRuta,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  if (ruta != null) ...[_punto(_colores[ruta.id]), const SizedBox(width: 8)] else ...[
                    const Icon(Icons.alt_route, size: 16, color: AppColors.primary),
                    const SizedBox(width: 6),
                  ],
                  Flexible(
                    child: Text(
                      ruta?.nombre ?? 'Todas las rutas',
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                    ),
                  ),
                  const Icon(Icons.arrow_drop_down, size: 20),
                ]),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            for (final e in estadosGps.entries)
              if ((conteo[e.key] ?? 0) > 0) Etiqueta('${e.value.$1}: ${conteo[e.key]}', e.value.$2),
            if (sinDespacho > 0) Etiqueta('${_sinDespacho.$1}: $sinDespacho', _sinDespacho.$2),
            if (visibles.isEmpty) Text(ruta == null ? 'Ningún bus con GPS activo' : 'Ningún bus despachado hoy en esta ruta'),
          ]),
          if (ruta != null && ocultos > 0)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                Expanded(
                  child: Text(
                    '$ocultos bus${ocultos == 1 ? '' : 'es'} no ${ocultos == 1 ? 'está despachado' : 'están despachados'} '
                    'hoy en esta ruta.',
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ),
                TextButton(onPressed: () => _cambiarRuta(null), child: const Text('Ver todas')),
              ]),
            ),
          if (ruta != null && _porSentido && ruta.tieneTrazado)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Wrap(spacing: 14, runSpacing: 4, children: [
                if (ruta.trazados.containsKey('ida')) _leyendaLinea('Ida', colorIda, false),
                if (ruta.trazados.containsKey('regreso')) _leyendaLinea('Regreso', colorRegreso, true),
                if (ruta.puntos.isNotEmpty) _leyendaPunto('Punto de control'),
              ]),
            ),
          if (ruta != null && !ruta.tieneTrazado)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text('Esta ruta aún no tiene trazado.', style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ),
          if (_actualizado != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Actualizado ${DateFormat('HH:mm:ss').format(_actualizado!)}',
                style: const TextStyle(fontSize: 11, color: AppColors.muted),
              ),
            ),
        ]),
      ),
    );
  }

  Widget _punto(Color? color, [double tamano = 10]) => Container(
        width: tamano,
        height: tamano,
        decoration: BoxDecoration(color: color ?? AppColors.muted, shape: BoxShape.circle),
      );

  Widget _leyendaLinea(String texto, Color color, bool punteada) => Row(mainAxisSize: MainAxisSize.min, children: [
        SizedBox(
          width: 22,
          height: 4,
          child: punteada
              // stretch: sin él cada raya queda de alto cero.
              ? Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  for (var i = 0; i < 3; i++) ...[
                    Expanded(child: ColoredBox(color: color)),
                    if (i < 2) const SizedBox(width: 3),
                  ],
                ])
              : ColoredBox(color: color),
        ),
        const SizedBox(width: 6),
        Text(texto, style: const TextStyle(fontSize: 12)),
      ]);

  Widget _leyendaPunto(String texto) => Row(mainAxisSize: MainAxisSize.min, children: [
        _punto(colorAmbos, 12),
        const SizedBox(width: 6),
        Text(texto, style: const TextStyle(fontSize: 12)),
      ]);

  /// Selector de ruta, como el desplegable "Todas las rutas" de la web.
  void _elegirRuta() {
    final porRuta = busesPorRuta(_buses);
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (c) => SizedBox(
        height: MediaQuery.sizeOf(context).height * .6,
        child: Column(children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 18, 20, 6),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('Ruta a monitorear', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17)),
            ),
          ),
          Expanded(
            child: ListView(children: [
              ListTile(
                leading: const Icon(Icons.alt_route, color: AppColors.primary),
                title: const Text('Todas las rutas'),
                subtitle: Text('${_buses.length} bus${_buses.length == 1 ? '' : 'es'} con GPS'),
                trailing: _ruta == null ? const Icon(Icons.check, color: AppColors.primary) : null,
                onTap: () {
                  Navigator.pop(c);
                  _cambiarRuta(null);
                },
              ),
              const Divider(height: 1),
              for (final r in _rutas)
                ListTile(
                  leading: Padding(padding: const EdgeInsets.all(6), child: _punto(_colores[r.id], 14)),
                  title: Text(r.nombre),
                  subtitle: Text([
                    '${porRuta[r.id] ?? 0} bus${(porRuta[r.id] ?? 0) == 1 ? '' : 'es'} hoy',
                    if (!r.tieneTrazado) 'sin trazado',
                  ].join(' · ')),
                  trailing: _ruta == r.id ? const Icon(Icons.check, color: AppColors.primary) : null,
                  onTap: () {
                    Navigator.pop(c);
                    _cambiarRuta(r.id);
                  },
                ),
              if (_rutas.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(20),
                  child: Text('No hay rutas configuradas.', style: TextStyle(color: AppColors.muted)),
                ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _mapaGoogle() {
    final inicio = _posiciones.firstOrNull ?? _lineas.firstOrNull?.puntos.firstOrNull ?? _centroDefecto;
    return gm.GoogleMap(
      key: const ValueKey('google'),
      initialCameraPosition: gm.CameraPosition(target: gm.LatLng(inicio.lat, inicio.lon), zoom: 13),
      mapType: _estilo == EstiloMapa.satelite ? gm.MapType.hybrid : gm.MapType.normal,
      style: switch (_estilo) {
        EstiloMapa.claro => _googleClaro,
        EstiloMapa.oscuro => _googleOscuro,
        _ => null,
      },
      // Deja libre la tarjeta de arriba (y el logo de Google abajo).
      padding: const EdgeInsets.only(top: 120),
      zoomControlsEnabled: false,
      mapToolbarEnabled: false,
      myLocationButtonEnabled: false,
      tiltGesturesEnabled: false,
      onMapCreated: (ctl) {
        _googleCtl = ctl;
        _encuadrar();
      },
      polylines: {
        for (final l in _lineas) ...[
          // Borde blanco debajo para que el trazado se lea sobre cualquier capa.
          gm.Polyline(
            polylineId: gm.PolylineId('${l.id}-borde'),
            points: [for (final p in l.puntos) gm.LatLng(p.lat, p.lon)],
            color: Colors.white.withValues(alpha: .7),
            width: l.regreso ? 7 : 8,
            zIndex: 1,
          ),
          gm.Polyline(
            polylineId: gm.PolylineId(l.id),
            points: [for (final p in l.puntos) gm.LatLng(p.lat, p.lon)],
            color: l.color,
            width: l.regreso ? 4 : 5,
            zIndex: 2,
            patterns: l.regreso ? [gm.PatternItem.dash(18), gm.PatternItem.gap(14)] : const [],
          ),
        ],
      },
      circles: {
        for (final p in _puntosControl)
          gm.Circle(
            circleId: gm.CircleId('pc-${p['id'] ?? p['orden']}'),
            center: gm.LatLng(asDouble(p['lat'])!, asDouble(p['lon'])!),
            radius: asDouble(p['radio_m']) ?? 50,
            strokeWidth: 2,
            strokeColor: _colorPunto(p),
            fillColor: _colorPunto(p).withValues(alpha: .12),
            zIndex: 3,
          ),
      },
      markers: {
        for (final p in _puntosControl)
          gm.Marker(
            markerId: gm.MarkerId('pc-${p['id'] ?? p['orden']}'),
            position: gm.LatLng(asDouble(p['lat'])!, asDouble(p['lon'])!),
            icon: _iconos[_clavePunto(p)] ?? gm.BitmapDescriptor.defaultMarker,
            anchor: const Offset(.5, .5),
            zIndexInt: 4,
            consumeTapEvents: true,
            onTap: () => _detallePunto(p),
          ),
        for (final b in _visibles)
          if (_posicion(b) case final p?)
            gm.Marker(
              markerId: gm.MarkerId('bus-${b['bus_id'] ?? b['numero']}'),
              position: gm.LatLng(p.lat, p.lon),
              icon: _iconoBus(b),
              anchor: const Offset(.5, .5),
              zIndexInt: 10,
              consumeTapEvents: true,
              onTap: () => _detalle(b),
            ),
      },
    );
  }

  Widget _mapaEsri() {
    final capa = _capasEsri[_estilo]!;
    final inicio = _posiciones.firstOrNull ?? _lineas.firstOrNull?.puntos.firstOrNull ?? _centroDefecto;
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
          for (final l in _lineas)
            Polyline(
              points: [for (final p in l.puntos) LatLng(p.lat, p.lon)],
              color: l.color,
              strokeWidth: l.regreso ? 4 : 5,
              borderColor: Colors.white.withValues(alpha: .7),
              borderStrokeWidth: 1.5,
              pattern: l.regreso ? StrokePattern.dashed(segments: const [9, 7]) : const StrokePattern.solid(),
            ),
        ]),
        CircleLayer(circles: [
          for (final p in _puntosControl)
            CircleMarker(
              point: LatLng(asDouble(p['lat'])!, asDouble(p['lon'])!),
              radius: asDouble(p['radio_m']) ?? 50,
              useRadiusInMeter: true,
              color: _colorPunto(p).withValues(alpha: .12),
              borderColor: _colorPunto(p),
              borderStrokeWidth: 1.5,
            ),
        ]),
        MarkerLayer(markers: [
          for (final p in _puntosControl)
            Marker(
              point: LatLng(asDouble(p['lat'])!, asDouble(p['lon'])!),
              width: 24,
              height: 24,
              child: GestureDetector(onTap: () => _detallePunto(p), child: _MarcadorPunto(p, _colorPunto(p))),
            ),
          for (final b in _visibles)
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

  /// Detalle del bus, como el globo de la web: estado, ruta de hoy, zona,
  /// velocidad, último reporte y precisión del GPS.
  void _detalle(Map<String, dynamic> b) {
    final est = estadosGps[b['estado']];
    final rutaId = asInt(b['ruta_id']);
    final rutaNombre = asStr(b['ruta_nombre']);
    showModalBottomSheet(
      context: context,
      builder: (c) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('Bus ${b['numero']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(width: 8),
              Text(asStr(b['placa']), style: const TextStyle(color: AppColors.muted)),
              const Spacer(),
              if (est != null) Etiqueta(est.$1, est.$2),
            ]),
            const SizedBox(height: 14),
            _dato(
              'Ruta',
              rutaId == null
                  ? const Text('Sin despacho hoy', style: TextStyle(color: AppColors.muted, fontWeight: FontWeight.w600))
                  : Row(children: [
                      _punto(_colores[rutaId], 10),
                      const SizedBox(width: 8),
                      Expanded(child: Text(rutaNombre, style: const TextStyle(fontWeight: FontWeight.w700))),
                    ]),
            ),
            if (b['encierro'] != null) _datoTexto('Zona', asStr(b['encierro'])),
            _datoTexto('Velocidad', b['velocidad_kmh'] == null ? '—' : '${asDouble(b['velocidad_kmh'])!.round()} km/h'),
            _datoTexto('Último reporte', '${_horaBogota(b['ultimo_reporte_at'])} · ${_haceCuanto(b['ultimo_reporte_at'])}'),
            if (b['precision_m'] != null) _datoTexto('Precisión GPS', '${asDouble(b['precision_m'])!.round()} m'),
            if (b['satelites'] != null) _datoTexto('Satélites', asStr(b['satelites'])),
            if (rutaId != null && rutaId != _ruta) ...[
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () {
                    Navigator.pop(c);
                    _cambiarRuta(rutaId);
                  },
                  icon: const Icon(Icons.alt_route),
                  label: Text('Monitorear ${rutaNombre.isEmpty ? 'su ruta' : rutaNombre}'),
                ),
              ),
            ],
          ]),
        ),
      ),
    );
  }

  void _detallePunto(Map<String, dynamic> p) {
    final alias = asStr(p['alias']);
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              _MarcadorPunto(p, _colorPunto(p)),
              const SizedBox(width: 10),
              Expanded(
                child: Text('${alias.isEmpty ? '' : '$alias · '}${asStr(p['nombre'])}',
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
              ),
            ]),
            const SizedBox(height: 12),
            if (_rutaElegida != null) _datoTexto('Ruta', _rutaElegida!.nombre),
            _datoTexto('Sentido', nombreSentido[p['sentido']] ?? 'Sin sentido'),
            _datoTexto('Tipo', p['tipo'] == 'terminal' ? 'Terminal' : 'Punto de control'),
            _datoTexto('Radio', '${asInt(p['radio_m']) ?? 0} m'),
            if (p['minutos_objetivo'] != null) _datoTexto('Tiempo objetivo', '${p['minutos_objetivo']} min'),
          ]),
        ),
      ),
    );
  }

  Widget _dato(String k, Widget v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          SizedBox(width: 120, child: Text(k, style: const TextStyle(color: AppColors.muted))),
          Expanded(child: v),
        ]),
      );

  Widget _datoTexto(String k, String v) => _dato(k, Text(v, style: const TextStyle(fontWeight: FontWeight.w600)));

  /// '08/10 07:42:15' en hora de Bogotá.
  String _horaBogota(dynamic iso) {
    final d = DateTime.tryParse(asStr(iso));
    if (d == null) return '—';
    return DateFormat('dd/MM HH:mm:ss').format(d.toUtc().subtract(const Duration(hours: 5)));
  }

  String _haceCuanto(dynamic iso) {
    final d = DateTime.tryParse(asStr(iso));
    if (d == null) return '—';
    final s = DateTime.now().toUtc().difference(d.toUtc()).inSeconds;
    if (s < 60) return 'hace $s s';
    if (s < 3600) return 'hace ${s ~/ 60} min';
    if (s < 86400) return 'hace ${s ~/ 3600} h';
    return 'hace ${s ~/ 86400} días';
  }

  /// Lista de buses de la ruta elegida, con buscador (como el panel de la web).
  void _lista() {
    var buscar = '';
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (c) => StatefulBuilder(
        builder: (c, setSheet) {
          final q = buscar.trim().toLowerCase();
          final lista = [
            for (final b in _visibles)
              if (q.isEmpty || '${b['numero']}'.contains(q) || asStr(b['placa']).toLowerCase().contains(q)) b,
          ];
          final ocultos = _buses.length - _visibles.length;
          return Padding(
            padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(c).bottom),
            child: SizedBox(
              height: MediaQuery.sizeOf(context).height * .65,
              child: Column(children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                  child: TextField(
                    decoration: const InputDecoration(
                      hintText: 'Buscar bus o placa…',
                      prefixIcon: Icon(Icons.search),
                      isDense: true,
                    ),
                    onChanged: (v) => setSheet(() => buscar = v),
                  ),
                ),
                if (_ruta != null && ocultos > 0)
                  ListTile(
                    dense: true,
                    title: Text(
                      '$ocultos bus${ocultos == 1 ? '' : 'es'} no ${ocultos == 1 ? 'está despachado' : 'están despachados'} hoy en esta ruta.',
                      style: const TextStyle(color: AppColors.muted),
                    ),
                    trailing: TextButton(
                      onPressed: () {
                        Navigator.pop(c);
                        _cambiarRuta(null);
                      },
                      child: const Text('Ver todas'),
                    ),
                  ),
                Expanded(
                  child: lista.isEmpty
                      ? VacioView(_buses.isEmpty ? 'Ningún bus con GPS activo.' : 'Ningún bus coincide con el filtro.')
                      : ListView(children: [
                          for (final b in lista) _filaBus(b, c),
                        ]),
                ),
              ]),
            ),
          );
        },
      ),
    );
  }

  Widget _filaBus(Map<String, dynamic> b, BuildContext sheet) {
    final est = estadosGps[b['estado']];
    final rutaId = asInt(b['ruta_id']);
    final moviendo = b['estado'] == 'movimiento' && b['velocidad_kmh'] != null;
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: _colorBus(b),
        child: Text('${b['numero']}',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
      ),
      title: Text.rich(TextSpan(children: [
        TextSpan(text: asStr(b['placa']).isEmpty ? 's/p' : asStr(b['placa'])),
        TextSpan(
          text: ' · ${est?.$1 ?? b['estado']}${moviendo ? ' · ${asDouble(b['velocidad_kmh'])!.round()} km/h' : ''}',
          style: TextStyle(color: _colorBus(b), fontSize: 13),
        ),
      ])),
      subtitle: Row(children: [
        if (rutaId != null) ...[_punto(_colores[rutaId], 9), const SizedBox(width: 6)],
        Expanded(
          child: Text(
            rutaId == null ? 'Sin despacho hoy' : asStr(b['ruta_nombre']),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ]),
      trailing: Text(_haceCuanto(b['ultimo_reporte_at']), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
      onTap: () {
        Navigator.pop(sheet);
        if (_posicion(b) case final p?) _irA(p);
        _detalle(b);
      },
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

/// Punto de control numerado; las terminales van en cuadro.
class _MarcadorPunto extends StatelessWidget {
  final Map<String, dynamic> p;
  final Color color;
  const _MarcadorPunto(this.p, this.color);

  @override
  Widget build(BuildContext context) => Container(
        width: 24,
        height: 24,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(p['tipo'] == 'terminal' ? 6 : 12),
          border: Border.all(color: Colors.white, width: 2),
          boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 3)],
        ),
        child: Text('${p['orden']}',
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 11)),
      );
}
