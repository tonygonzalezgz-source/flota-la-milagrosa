import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import '../../widgets/fotos.dart';
import '../../widgets/registros.dart';

/// Tipos de actividad (EDS_TIPOS en api/app.py, TIPO_META en operador-eds.html).
const tiposEds = {
  'aseo_patio': ('Aseo de patio', 'Todos los días'),
  'canaletas': ('Aseo de canaletas', 'Lunes · Miércoles · Viernes'),
  'aseo_estacion': ('Aseo equipo y lavado de estación', 'Martes · Jueves · Domingo'),
  'trampa_grasa': ('Limpieza trampa de grasa', 'Sábado'),
  'novedad': ('Novedad', ''),
};

/// Actividades programadas por día (DateTime.weekday: 1 = lunes … 7 = domingo).
const _cronograma = {
  1: ['aseo_patio', 'canaletas'],
  2: ['aseo_patio', 'aseo_estacion'],
  3: ['aseo_patio', 'canaletas'],
  4: ['aseo_patio', 'aseo_estacion'],
  5: ['aseo_patio', 'canaletas'],
  6: ['aseo_patio', 'trampa_grasa'],
  7: ['aseo_patio', 'aseo_estacion'],
};

class EdsScreen extends ConsumerStatefulWidget {
  const EdsScreen({super.key});

  @override
  ConsumerState<EdsScreen> createState() => _EdsScreenState();
}

class _EdsScreenState extends ConsumerState<EdsScreen> {
  final _historial = GlobalKey<HistorialRegistrosState>();
  bool _verNovedades = false;

  @override
  Widget build(BuildContext context) {
    final api = ref.read(apiClientProvider);
    final esAdmin = ref.watch(sessionProvider).value?.esAdmin ?? false;
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Operador EDS'),
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white60,
            indicatorColor: Colors.white,
            tabs: [Tab(text: 'Registrar'), Tab(text: 'Historial')],
          ),
        ),
        body: TabBarView(children: [
          _FormEds(onGuardado: () => _historial.currentState?.recargar()),
          Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: SegmentedButton<bool>(
                expandedInsets: EdgeInsets.zero,
                showSelectedIcon: false,
                segments: const [
                  ButtonSegment(value: false, label: Text('Aseo')),
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
                cargar: (desde, hasta) async => asLista(await api.get('/eds', query: {
                  'tipo': _verNovedades ? 'novedad' : 'aseo',
                  'desde': desde,
                  'hasta': hasta,
                })),
                fila: (r) => FilaRegistro(
                  titulo: tiposEds[r['tipo']]?.$1 ?? asStr(r['tipo']),
                  subtitulo:
                      '${Fechas.corta(r['fecha'])} · ${r['tipo'] == 'novedad' ? 'Reportada' : 'Realizada'} por ${asStr(r['realizado_por'])}',
                  descripcion: asStr(r['descripcion']),
                  numFotos: numFotos(r),
                ),
                fotos: (r) async {
                  final d = await api.get('/eds/${r['id']}/fotos') as Map<String, dynamic>;
                  return (d['fotos'] as List).cast<String>();
                },
                // Solo el administrador borra historial (igual que el backend).
                borrar: esAdmin ? (r) => api.delete('/eds/${r['id']}') : null,
              ),
            ),
          ]),
        ]),
      ),
    );
  }
}

class _FormEds extends ConsumerStatefulWidget {
  final VoidCallback onGuardado;
  const _FormEds({required this.onGuardado});

  @override
  ConsumerState<_FormEds> createState() => _FormEdsState();
}

class _FormEdsState extends ConsumerState<_FormEds> with AutomaticKeepAliveClientMixin {
  bool _novedad = false;
  String? _tipo;
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
  }

  @override
  void dispose() {
    _resp.dispose();
    _desc.dispose();
    super.dispose();
  }

  Future<void> _guardar() async {
    final tipo = _novedad ? 'novedad' : _tipo;
    if (tipo == null || _resp.text.trim().isEmpty) {
      mostrarMensaje(context, 'Completa los campos obligatorios', error: true);
      return;
    }
    if (_novedad && _desc.text.trim().isEmpty) {
      mostrarMensaje(context, 'Describe la novedad observada', error: true);
      return;
    }
    setState(() => _enviando = true);
    try {
      await ref.read(apiClientProvider).post('/eds', body: {
        'tipo': tipo,
        'fecha': _fecha,
        'realizado_por': _resp.text.trim(),
        'descripcion': _desc.text.trim(),
        'fotos': _fotos,
      });
      if (!mounted) return;
      mostrarMensaje(context, _novedad ? 'Novedad reportada correctamente' : 'Actividad registrada correctamente');
      setState(() {
        _tipo = null;
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
    final hoy = _cronograma[DateTime.parse(Fechas.hoy()).weekday] ?? const [];
    return ListView(padding: const EdgeInsets.all(16), children: [
      SegmentedButton<bool>(
        showSelectedIcon: false,
        segments: const [
          ButtonSegment(value: false, label: Text('Aseo'), icon: Icon(Icons.cleaning_services_outlined)),
          ButtonSegment(value: true, label: Text('Novedad'), icon: Icon(Icons.report_outlined)),
        ],
        selected: {_novedad},
        onSelectionChanged: (s) => setState(() => _novedad = s.first),
      ),
      const SizedBox(height: 14),
      if (!_novedad) ...[
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('Programado para hoy', style: TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final t in hoy) Etiqueta(tiposEds[t]!.$1, AppColors.primary),
              ]),
            ]),
          ),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _tipo,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Actividad'),
          items: [
            for (final e in tiposEds.entries.where((e) => e.key != 'novedad'))
              DropdownMenuItem(value: e.key, child: Text(e.value.$1)),
          ],
          onChanged: (v) => setState(() => _tipo = v),
        ),
        if (_tipo != null)
          Padding(
            padding: const EdgeInsets.only(top: 4, left: 4),
            child: Text(tiposEds[_tipo]!.$2, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          ),
        const SizedBox(height: 12),
      ],
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
    ]);
  }
}
