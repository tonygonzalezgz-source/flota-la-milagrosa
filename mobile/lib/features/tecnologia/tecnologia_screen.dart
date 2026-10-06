import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:signature/signature.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import '../../widgets/fotos.dart';
import '../../widgets/registros.dart';

const _areas = {'camaras': 'Cámaras', 'sensores': 'Sensores'};

/// Roles que registran intervenciones (ROLES_TECNOLOGIA en api/app.py).
const _rolesEscritura = {'Administrador', 'Técnico Cámaras', 'Jefe Op. Tecnológicas'};

/// Dispositivos tecnológicos: intervenciones a cámaras y sensores con
/// fotos y firma de quien recibe.
class TecnologiaScreen extends ConsumerStatefulWidget {
  const TecnologiaScreen({super.key});

  @override
  ConsumerState<TecnologiaScreen> createState() => _TecnologiaScreenState();
}

class _TecnologiaScreenState extends ConsumerState<TecnologiaScreen> {
  final _historial = GlobalKey<HistorialRegistrosState>();
  String _area = 'camaras';

  @override
  Widget build(BuildContext context) {
    final api = ref.read(apiClientProvider);
    final user = ref.watch(sessionProvider).value;
    final rol = user?.rol ?? '';
    final escribe = _rolesEscritura.contains(rol);

    final selectorArea = Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: SegmentedButton<String>(
        expandedInsets: EdgeInsets.zero,
        showSelectedIcon: false,
        segments: [
          for (final e in _areas.entries) ButtonSegment(value: e.key, label: Text(e.value)),
        ],
        selected: {_area},
        onSelectionChanged: (s) {
          setState(() => _area = s.first);
          _historial.currentState?.recargar();
        },
      ),
    );

    final historial = Column(children: [
      selectorArea,
      Expanded(
        child: HistorialRegistros(
          key: _historial,
          cargar: (desde, hasta) async => asLista(await api.get('/tecnologia', query: {
            'area': _area,
            'desde': desde,
            'hasta': hasta,
          })),
          fila: (r) => FilaRegistro(
            titulo: asStr(r['tipo']),
            subtitulo:
                'Bus ${r['numero']} · ${Fechas.corta(r['fecha'])} · ${asStr(r['tecnico'])}',
            descripcion: asStr(r['descripcion']),
            etiqueta: asBool(r['tiene_firma']) ? const Etiqueta('Firmada', AppColors.green) : null,
            numFotos: numFotos(r) + (asBool(r['tiene_firma']) ? 1 : 0),
          ),
          fotos: (r) async {
            final d = await api.get('/tecnologia/${r['id']}/fotos') as Map<String, dynamic>;
            return [
              ...(d['fotos'] as List).cast<String>(),
              if (d['firma_base64'] != null) d['firma_base64'] as String,
            ];
          },
          // El técnico solo recibe sus propias intervenciones, así que todas las
          // que ve puede borrarlas; el backend vuelve a validar el dueño.
          borrar: escribe ? (r) => api.delete('/tecnologia/${r['id']}') : null,
        ),
      ),
    ]);

    if (!escribe) {
      return Scaffold(appBar: AppBar(title: const Text('Disp. Tecnológicos')), body: historial);
    }
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Disp. Tecnológicos'),
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white60,
            indicatorColor: Colors.white,
            tabs: [Tab(text: 'Registrar'), Tab(text: 'Historial')],
          ),
        ),
        body: TabBarView(children: [
          _FormTecnologia(onGuardado: () => _historial.currentState?.recargar()),
          historial,
        ]),
      ),
    );
  }
}

class _FormTecnologia extends ConsumerStatefulWidget {
  final VoidCallback onGuardado;
  const _FormTecnologia({required this.onGuardado});

  @override
  ConsumerState<_FormTecnologia> createState() => _FormTecnologiaState();
}

class _FormTecnologiaState extends ConsumerState<_FormTecnologia>
    with AutomaticKeepAliveClientMixin {
  List<Bus>? _buses;
  String? _errorBuses;
  String _area = 'camaras';
  int? _busId;
  String _fecha = Fechas.hoy();
  final _tipo = TextEditingController();
  final _tecnico = TextEditingController();
  final _desc = TextEditingController();
  final _firmante = TextEditingController();
  final _firma = SignatureController(
    penStrokeWidth: 2.2,
    penColor: const Color(0xFF111111),
    exportBackgroundColor: Colors.white,
  );
  List<String> _fotos = [];
  bool _enviando = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _tecnico.text = ref.read(sessionProvider).value?.nombre ?? '';
    _cargarBuses();
  }

  @override
  void dispose() {
    for (final c in [_tipo, _tecnico, _desc, _firmante]) {
      c.dispose();
    }
    _firma.dispose();
    super.dispose();
  }

  Future<void> _cargarBuses() async {
    try {
      final l = asLista(await ref.read(apiClientProvider).get('/buses'));
      _buses = l.map(Bus.fromJson).toList();
      _errorBuses = null;
    } catch (e) {
      _errorBuses = e.toString();
    }
    if (mounted) setState(() {});
  }

  Future<void> _guardar() async {
    if (_busId == null || _tipo.text.trim().isEmpty || _tecnico.text.trim().isEmpty) {
      mostrarMensaje(context, 'Completa los campos obligatorios', error: true);
      return;
    }
    setState(() => _enviando = true);
    try {
      final firmaPng = _firma.isEmpty ? null : await _firma.toPngBytes();
      await ref.read(apiClientProvider).post('/tecnologia', body: {
        'bus_id': _busId,
        'area': _area,
        'fecha': _fecha,
        'tipo': _tipo.text.trim(),
        'tecnico': _tecnico.text.trim(),
        'descripcion': _desc.text.trim(),
        'fotos': _fotos,
        'firma_base64': firmaPng == null ? null : aDataUrl(firmaPng, mime: 'image/png'),
        'firma_nombre': _firmante.text.trim(),
      });
      if (!mounted) return;
      mostrarMensaje(context, 'Intervención registrada correctamente');
      setState(() {
        _busId = null;
        _tipo.clear();
        _desc.clear();
        _firmante.clear();
        _firma.clear();
        _fotos = [];
        _fecha = Fechas.hoy();
      });
      widget.onGuardado();
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return CargaView(
      cargando: _buses == null && _errorBuses == null,
      error: _errorBuses,
      onReintentar: _cargarBuses,
      builder: () => ListView(padding: const EdgeInsets.all(16), children: [
        SegmentedButton<String>(
          showSelectedIcon: false,
          segments: [
            for (final e in _areas.entries) ButtonSegment(value: e.key, label: Text(e.value)),
          ],
          selected: {_area},
          onSelectionChanged: (s) => setState(() => _area = s.first),
        ),
        const SizedBox(height: 14),
        CampoBus(buses: _buses!, valor: _busId, onChanged: (v) => setState(() => _busId = v)),
        const SizedBox(height: 12),
        CampoFecha(valor: _fecha, onChanged: (v) => setState(() => _fecha = v)),
        const SizedBox(height: 12),
        TextField(
          controller: _tipo,
          decoration: const InputDecoration(
            labelText: 'Tipo de intervención',
            hintText: 'Ej: Cambio de cámara frontal',
          ),
        ),
        const SizedBox(height: 12),
        TextField(controller: _tecnico, decoration: const InputDecoration(labelText: 'Realizada por')),
        const SizedBox(height: 12),
        TextField(
          controller: _desc,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(
            labelText: 'Novedad / descripción del trabajo (opcional)',
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 16),
        const Text('Evidencias', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        FotosPicker(fotos: _fotos, onChanged: (f) => setState(() => _fotos = f)),
        const SizedBox(height: 16),
        Row(children: [
          const Expanded(
            child: Text('Firma de quien recibe (opcional)', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
          TextButton(onPressed: _firma.clear, child: const Text('Borrar firma')),
        ]),
        Container(
          decoration: BoxDecoration(
            border: Border.all(color: const Color(0xFFCCCCD4), width: 2),
            borderRadius: BorderRadius.circular(12),
            color: Colors.white,
          ),
          clipBehavior: Clip.antiAlias,
          child: Signature(controller: _firma, height: 170, backgroundColor: Colors.white),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _firmante,
          decoration: const InputDecoration(
            labelText: 'Nombre de quien firma (opcional)',
            hintText: 'Ej: Pedro Gómez (conductor)',
          ),
        ),
        const SizedBox(height: 20),
        BotonGuardar(enviando: _enviando, texto: 'Guardar intervención', onPressed: _guardar),
      ]),
    );
  }
}
