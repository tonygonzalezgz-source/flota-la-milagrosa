import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import '../../widgets/fotos.dart';
import '../../widgets/registros.dart';

/// LAVADA_TIPOS en api/app.py.
const tiposLavada = {
  'lavada': 'Lavada (exterior)',
  'primeriada': 'Primeriada (interior)',
  'ambas': 'Lavada + Primeriada',
  'novedad': 'Novedad',
};

/// Lavada Primeriada: solo micros (grupo B). El propietario solo consulta.
class LavadaScreen extends ConsumerStatefulWidget {
  const LavadaScreen({super.key});

  @override
  ConsumerState<LavadaScreen> createState() => _LavadaScreenState();
}

class _LavadaScreenState extends ConsumerState<LavadaScreen> {
  final _historial = GlobalKey<HistorialRegistrosState>();
  bool _verNovedades = false;

  @override
  Widget build(BuildContext context) {
    final api = ref.read(apiClientProvider);
    final user = ref.watch(sessionProvider).value;
    final soloLectura = user?.esPropietario ?? false;

    final historial = Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: SegmentedButton<bool>(
          expandedInsets: EdgeInsets.zero,
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: false, label: Text('Lavados')),
            ButtonSegment(value: true, label: Text('Novedades')),
          ],
          selected: {_verNovedades},
          onSelectionChanged: (s) {
            setState(() => _verNovedades = s.first);
            _historial.currentState?.recargar();
          },
        ),
      ),
      Expanded(
        child: HistorialRegistros(
          key: _historial,
          cargar: (desde, hasta) async => asLista(await api.get('/lavada', query: {
            'tipo': _verNovedades ? 'novedad' : 'lavados',
            'desde': desde,
            'hasta': hasta,
          })),
          fila: (r) => FilaRegistro(
            titulo: 'Micro ${r['bus_numero']}${asStr(r['bus_placa']).isEmpty ? '' : ' · ${r['bus_placa']}'}',
            subtitulo:
                '${Fechas.corta(r['fecha'])} · ${r['tipo'] == 'novedad' ? 'Reportada' : 'Realizada'} por ${asStr(r['realizado_por'])}',
            descripcion: asStr(r['descripcion']),
            etiqueta: Etiqueta(tiposLavada[r['tipo']] ?? asStr(r['tipo']),
                r['tipo'] == 'novedad' ? AppColors.red : AppColors.blue),
            numFotos: numFotos(r),
          ),
          fotos: (r) async {
            final d = await api.get('/lavada/${r['id']}/fotos') as Map<String, dynamic>;
            return (d['fotos'] as List).cast<String>();
          },
          borrar: (user?.esAdmin ?? false) ? (r) => api.delete('/lavada/${r['id']}') : null,
        ),
      ),
    ]);

    if (soloLectura) {
      return Scaffold(appBar: AppBar(title: const Text('Lavada Primeriada')), body: historial);
    }
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Lavada Primeriada'),
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white60,
            indicatorColor: Colors.white,
            tabs: [Tab(text: 'Registrar'), Tab(text: 'Historial')],
          ),
        ),
        body: TabBarView(children: [
          _FormLavada(onGuardado: () => _historial.currentState?.recargar()),
          historial,
        ]),
      ),
    );
  }
}

class _FormLavada extends ConsumerStatefulWidget {
  final VoidCallback onGuardado;
  const _FormLavada({required this.onGuardado});

  @override
  ConsumerState<_FormLavada> createState() => _FormLavadaState();
}

class _FormLavadaState extends ConsumerState<_FormLavada> with AutomaticKeepAliveClientMixin {
  List<Bus>? _micros;
  String? _errorBuses;
  bool _novedad = false;
  String _tipo = 'ambas';
  int? _busId;
  String _fecha = Fechas.hoy();
  final _resp = TextEditingController();
  final _desc = TextEditingController();
  List<String> _fotos = [];
  bool _enviando = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _resp.text = ref.read(sessionProvider).value?.nombre ?? '';
    _cargarBuses();
  }

  @override
  void dispose() {
    _resp.dispose();
    _desc.dispose();
    super.dispose();
  }

  Future<void> _cargarBuses() async {
    try {
      final l = asLista(await ref.read(apiClientProvider).get('/buses'));
      _micros = l.map(Bus.fromJson).where((b) => b.grupo == 'B').toList();
      _errorBuses = null;
    } catch (e) {
      _errorBuses = e.toString();
    }
    if (mounted) setState(() {});
  }

  Future<void> _guardar() async {
    if (_busId == null || _resp.text.trim().isEmpty) {
      mostrarMensaje(context, 'Completa los campos obligatorios (incluyendo el micro)', error: true);
      return;
    }
    if (_novedad && _desc.text.trim().isEmpty) {
      mostrarMensaje(context, 'Describe la novedad observada', error: true);
      return;
    }
    setState(() => _enviando = true);
    try {
      await ref.read(apiClientProvider).post('/lavada', body: {
        'bus_id': _busId,
        'tipo': _novedad ? 'novedad' : _tipo,
        'fecha': _fecha,
        'realizado_por': _resp.text.trim(),
        'descripcion': _desc.text.trim(),
        'fotos': _fotos,
      });
      if (!mounted) return;
      mostrarMensaje(context, _novedad ? 'Novedad reportada correctamente' : 'Lavado registrado correctamente');
      setState(() {
        _busId = null;
        _desc.clear();
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
      cargando: _micros == null && _errorBuses == null,
      error: _errorBuses,
      onReintentar: _cargarBuses,
      builder: () => ListView(padding: const EdgeInsets.all(16), children: [
        SegmentedButton<bool>(
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: false, label: Text('Lavado'), icon: Icon(Icons.water_drop_outlined)),
            ButtonSegment(value: true, label: Text('Novedad'), icon: Icon(Icons.report_outlined)),
          ],
          selected: {_novedad},
          onSelectionChanged: (s) => setState(() => _novedad = s.first),
        ),
        const SizedBox(height: 14),
        CampoBus(
          buses: _micros!,
          valor: _busId,
          label: 'Micro',
          onChanged: (v) => setState(() => _busId = v),
        ),
        if (!_novedad) ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _tipo,
            decoration: const InputDecoration(labelText: 'Tipo de lavado'),
            items: [
              for (final e in tiposLavada.entries.where((e) => e.key != 'novedad'))
                DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => setState(() => _tipo = v ?? 'ambas'),
          ),
        ],
        const SizedBox(height: 12),
        CampoFecha(valor: _fecha, onChanged: (v) => setState(() => _fecha = v)),
        const SizedBox(height: 12),
        TextField(
          controller: _resp,
          decoration: InputDecoration(labelText: _novedad ? 'Reportada por' : 'Realizada por'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _desc,
          minLines: 3,
          maxLines: 6,
          decoration: InputDecoration(
            labelText: _novedad ? 'Descripción de la novedad' : 'Observaciones (opcional)',
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 16),
        const Text('Evidencias', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        FotosPicker(fotos: _fotos, onChanged: (f) => setState(() => _fotos = f)),
        const SizedBox(height: 20),
        BotonGuardar(
          enviando: _enviando,
          texto: _novedad ? 'Reportar novedad' : 'Guardar registro',
          onPressed: _guardar,
        ),
      ]),
    );
  }
}
