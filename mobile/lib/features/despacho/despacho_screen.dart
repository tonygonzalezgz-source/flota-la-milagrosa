import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import '../alistamiento/alistamiento_form.dart';

const _estados = {
  'trabajando': ('Trabajando', AppColors.green),
  'taller': ('En taller', AppColors.yellow),
  'descanso': ('Descanso', AppColors.muted),
};

const _docs = [
  ('soat_vencimiento', 'SOAT'),
  ('tecno_vencimiento', 'Téc. Mecánica'),
  ('tarjeta_op_vencimiento', 'Tarjeta de Op.'),
];

/// Documentos legales del bus: vencidos bloquean "Trabajando" (el backend
/// también lo valida en /api/despacho/batch).
({List<String> vencidos, List<String> porVencer}) docsBus(Map<String, dynamic> b) {
  final vencidos = <String>[], porVencer = <String>[];
  for (final (campo, label) in _docs) {
    final dias = Fechas.diasHasta(b[campo]);
    if (dias == null) continue;
    if (dias < 0) {
      vencidos.add('$label (venc. hace ${-dias}d)');
    } else if (dias <= 30) {
      porVencer.add('$label (${dias}d)');
    }
  }
  return (vencidos: vencidos, porVencer: porVencer);
}

/// Despacho diario: estado, ruta, conductor, registradora y viajes de cada
/// bus para hoy. Cada cambio se guarda al instante con /api/despacho/batch.
class DespachoScreen extends ConsumerStatefulWidget {
  const DespachoScreen({super.key});

  @override
  ConsumerState<DespachoScreen> createState() => _DespachoScreenState();
}

class _DespachoScreenState extends ConsumerState<DespachoScreen> {
  final _hoy = Fechas.hoy();
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<Map<String, dynamic>> _rutas = [];
  List<Map<String, dynamic>> _conductores = [];
  String _filtro = '';

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  Future<void> _cargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    final api = ref.read(apiClientProvider);
    try {
      final r = await Future.wait([
        api.get('/despacho', query: {'fecha': _hoy}),
        api.get('/conductores'),
      ]);
      final d = r[0] as Map<String, dynamic>;
      _rutas = asLista(d['rutas']);
      _buses = asLista(d['buses']);
      _conductores = asLista(r[1]);
      // Secuencia del torniquete: se sugiere como REG Inicio la lectura final
      // del último día con datos (el despachador puede cambiarla).
      for (final b in _buses) {
        if (b['registradora_inicio'] == null && b['ultima_reg_fin'] != null) {
          b['registradora_inicio'] = asInt(b['ultima_reg_fin']);
          b['_reg_ini_sugerida'] = true;
        }
      }
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  /// Copia ruta y conductor del último día con despacho (hasta 7 días atrás,
  /// sin domingos) como sugerencia sin guardar, igual que la web.
  Future<void> _copiarDiaAnterior() async {
    final api = ref.read(apiClientProvider);
    try {
      String? fuente;
      List<Map<String, dynamic>> prev = [];
      for (var i = 1; i <= 7; i++) {
        final f = Fechas.haceDias(i);
        if (DateTime.parse(f).weekday == DateTime.sunday) continue;
        final d = await api.get('/despacho', query: {'fecha': f}) as Map<String, dynamic>;
        final lista = asLista(d['buses']);
        if (lista.any((b) => b['estado'] != null)) {
          fuente = f;
          prev = lista;
          break;
        }
      }
      if (!mounted) return;
      if (fuente == null) {
        mostrarMensaje(context, 'No se encontró despacho en los últimos 7 días', error: true);
        return;
      }
      final porBus = {for (final b in prev) asInt(b['id']): b};
      var n = 0;
      for (final b in _buses) {
        if (b['estado'] != null || b['conductor_id'] != null || b['ruta_id'] != null) continue;
        final p = porBus[asInt(b['id'])];
        if (p == null || (p['conductor_id'] == null && p['ruta_id'] == null)) continue;
        b['conductor_id'] = p['conductor_id'];
        b['ruta_id'] = p['ruta_id'];
        b['_sugerido'] = true;
        n++;
      }
      setState(() {});
      mostrarMensaje(
          context,
          n == 0
              ? 'El despacho del ${Fechas.corta(fuente)} no tiene conductores para sugerir'
              : '$n buses sugeridos del ${Fechas.corta(fuente)} — confirma cada uno');
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    }
  }

  String _nombreConductor(dynamic id) {
    final c = _conductores.where((c) => asInt(c['id']) == asInt(id));
    return c.isEmpty ? '' : asStr(c.first['nombre']);
  }

  String _nombreRuta(dynamic id) {
    final r = _rutas.where((r) => asInt(r['id']) == asInt(id));
    return r.isEmpty ? '' : asStr(r.first['nombre']);
  }

  @override
  Widget build(BuildContext context) {
    final c = {'trabajando': 0, 'taller': 0, 'descanso': 0};
    for (final b in _buses) {
      final e = b['estado'] as String?;
      if (e != null && c.containsKey(e)) c[e] = c[e]! + 1;
    }
    final hayVacios = _buses.any(
        (b) => b['estado'] == null && b['conductor_id'] == null && b['ruta_id'] == null);
    final q = _filtro.trim().toLowerCase();
    final visibles = _buses.where((b) {
      if (q.isEmpty) return true;
      return '${b['numero']} ${b['placa'] ?? ''} ${_nombreConductor(b['conductor_id'])}'
          .toLowerCase()
          .contains(q);
    }).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Despacho'),
        actions: [
          if (hayVacios)
            IconButton(
              tooltip: 'Copiar día anterior',
              icon: const Icon(Icons.content_copy),
              onPressed: _copiarDiaAnterior,
            ),
        ],
      ),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargar,
        builder: () => RefreshIndicator(
          onRefresh: _cargar,
          child: ListView(padding: const EdgeInsets.all(16), children: [
            Text(Fechas.larga(_hoy), style: const TextStyle(color: AppColors.muted)),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(child: Indicador('Trabajando', '${c['trabajando']}', AppColors.green)),
              const SizedBox(width: 10),
              Expanded(child: Indicador('En taller', '${c['taller']}', AppColors.yellow)),
              const SizedBox(width: 10),
              Expanded(child: Indicador('Descanso', '${c['descanso']}', AppColors.muted)),
            ]),
            const SizedBox(height: 12),
            TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Buscar bus, placa o conductor',
              ),
              onChanged: (v) => setState(() => _filtro = v),
            ),
            if (_buses.isEmpty) const VacioView('No hay buses registrados.'),
            for (final g in ['A', 'B']) ...[
              if (visibles.any((b) => b['grupo'] == g)) TituloSeccion(grupoLabel(g)),
              for (final b in visibles.where((b) => b['grupo'] == g)) _tarjeta(b),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _tarjeta(Map<String, dynamic> b) {
    final sugerido = b['_sugerido'] == true && b['estado'] == null;
    final estado = b['estado'] as String?;
    final info = _estados[estado];
    final docs = docsBus(b);
    final trabaja = estado == 'trabajando';
    final ini = asInt(b['registradora_inicio']), fin = asInt(b['registradora_fin']);

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => _editar(b),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text('${b['numero']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(asStr(b['placa']), style: const TextStyle(color: AppColors.muted)),
                ),
                if (sugerido) const Etiqueta('Sugerido', AppColors.blue),
                if (!sugerido)
                  Etiqueta(info?.$1 ?? 'Sin definir', info?.$2 ?? AppColors.muted),
              ]),
              if (docs.vencidos.isNotEmpty) ...[
                const SizedBox(height: 6),
                Etiqueta('🚫 Docs vencidos: ${docs.vencidos.join(' · ')}', AppColors.red),
              ] else if (docs.porVencer.isNotEmpty) ...[
                const SizedBox(height: 6),
                Etiqueta('Por vencer: ${docs.porVencer.join(' · ')}', AppColors.yellow),
              ],
              if (estado != 'descanso' && (b['ruta_id'] != null || b['conductor_id'] != null)) ...[
                const SizedBox(height: 8),
                Text([
                  _nombreRuta(b['ruta_id']).isEmpty ? 'Sin ruta' : _nombreRuta(b['ruta_id']),
                  _nombreConductor(b['conductor_id']).isEmpty
                      ? 'Sin conductor'
                      : _nombreConductor(b['conductor_id']),
                ].join(' · ')),
              ],
              if (trabaja) ...[
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(
                    child: Text(
                      'REG ${ini ?? '—'} → ${fin ?? '—'}'
                      '${ini != null && fin != null && fin >= ini ? '  = ${miles(fin - ini)} pax' : ''}'
                      '   ·   ${asInt(b['viajes_realizados']) ?? 0} viajes',
                      style: const TextStyle(fontSize: 13, color: AppColors.muted),
                    ),
                  ),
                  ActionChip(
                    avatar: Icon(
                        asBool(b['tiene_alistamiento']) ? Icons.check : Icons.warning_amber_rounded,
                        size: 16),
                    label: Text(asBool(b['tiene_alistamiento']) ? 'Alistamiento' : 'Alistar'),
                    backgroundColor: (asBool(b['tiene_alistamiento']) ? AppColors.green : AppColors.yellow)
                        .withValues(alpha: .15),
                    onPressed: () async {
                      final ok = await abrirAlistamiento(context,
                          busId: asInt(b['id'])!,
                          titulo: 'Bus ${b['numero']}',
                          conductorId: asInt(b['conductor_id']));
                      if (ok) setState(() => b['tiene_alistamiento'] = 1);
                    },
                  ),
                ]),
              ],
            ]),
          ),
        ),
      ),
    );
  }

  Future<void> _editar(Map<String, dynamic> b) async {
    final guardado = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _EditorBus(
        bus: b,
        rutas: _rutas.where((r) => r['grupo'] == b['grupo']).toList(),
        conductores: _conductores,
        fecha: _hoy,
      ),
    );
    if (guardado != null && mounted) {
      setState(() {
        b.addAll(guardado);
        b.remove('_sugerido');
        b.remove('_reg_ini_sugerida');
      });
      mostrarMensaje(context, 'Bus ${b['numero']} actualizado');
    }
  }
}

/// Hoja de edición de un bus. Devuelve los valores guardados o null.
class _EditorBus extends ConsumerStatefulWidget {
  final Map<String, dynamic> bus;
  final List<Map<String, dynamic>> rutas;
  final List<Map<String, dynamic>> conductores;
  final String fecha;
  const _EditorBus({
    required this.bus,
    required this.rutas,
    required this.conductores,
    required this.fecha,
  });

  @override
  ConsumerState<_EditorBus> createState() => _EditorBusState();
}

class _EditorBusState extends ConsumerState<_EditorBus> {
  late String _estado;
  int? _rutaId;
  int? _conductorId;
  late final TextEditingController _ini, _fin, _viajes;
  bool _guardando = false;

  @override
  void initState() {
    super.initState();
    final b = widget.bus;
    final bloqueado = docsBus(b).vencidos.isNotEmpty;
    _estado = (b['estado'] as String?) ?? (bloqueado ? 'descanso' : 'trabajando');
    _rutaId = asInt(b['ruta_id']);
    if (!widget.rutas.any((r) => asInt(r['id']) == _rutaId)) _rutaId = null;
    _conductorId = asInt(b['conductor_id']);
    _ini = TextEditingController(text: asStr(b['registradora_inicio']));
    _fin = TextEditingController(text: asStr(b['registradora_fin']));
    _viajes = TextEditingController(text: asStr(b['viajes_realizados']));
  }

  @override
  void dispose() {
    _ini.dispose();
    _fin.dispose();
    _viajes.dispose();
    super.dispose();
  }

  int? _num(TextEditingController c) => c.text.trim().isEmpty ? null : int.tryParse(c.text.trim());

  Future<void> _guardar() async {
    final trabaja = _estado == 'trabajando';
    final ini = _num(_ini), fin = _num(_fin);
    if (trabaja && ini != null && fin != null && fin < ini) {
      mostrarMensaje(context, 'REG Fin no puede ser menor que REG Inicio', error: true);
      return;
    }
    final registro = <String, dynamic>{
      'bus_id': asInt(widget.bus['id']),
      'estado': _estado,
      // Un bus en descanso no lleva conductor ni ruta; uno que no trabaja no
      // acumula viajes ni lecturas (mismas reglas que despacho.html y el backend).
      'conductor_id': _estado == 'descanso' ? null : _conductorId,
      'ruta_id': _estado == 'descanso' ? null : _rutaId,
      'viajes_realizados': trabaja ? _num(_viajes) : null,
      'registradora_inicio': trabaja ? ini : null,
      'registradora_fin': trabaja ? fin : null,
    };
    setState(() => _guardando = true);
    try {
      await ref.read(apiClientProvider).put('/despacho/batch', body: {
        'fecha': widget.fecha,
        'registros': [registro],
      });
      if (mounted) Navigator.of(context).pop(registro..remove('bus_id'));
    } catch (e) {
      if (mounted) {
        mostrarMensaje(context, e.toString(), error: true);
        setState(() => _guardando = false);
      }
    }
  }

  Future<void> _elegirConductor() async {
    final r = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _SelectorConductor(widget.conductores),
    );
    if (r != null) setState(() => _conductorId = r == 0 ? null : r);
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.bus;
    final bloqueado = docsBus(b).vencidos.isNotEmpty;
    final trabaja = _estado == 'trabajando';
    final cond = widget.conductores.where((c) => asInt(c['id']) == _conductorId);
    final ini = _num(_ini), fin = _num(_fin);
    final numFmt = [FilteringTextInputFormatter.digitsOnly];

    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Center(
            child: Container(
              width: 40, height: 4,
              margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(color: Colors.black26, borderRadius: BorderRadius.circular(2)),
            ),
          ),
          Text('Bus ${b['numero']}${asStr(b['placa']).isEmpty ? '' : ' · ${b['placa']}'}',
              style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
          if (bloqueado)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                  'Documentos vencidos: ${docsBus(b).vencidos.join(', ')}. '
                  'Solicita al Administrador la renovación.',
                  style: const TextStyle(color: AppColors.red, fontSize: 13)),
            ),
          const SizedBox(height: 14),
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: [
              ButtonSegment(value: 'trabajando', label: const Text('Trabajando'), enabled: !bloqueado),
              const ButtonSegment(value: 'taller', label: Text('Taller')),
              const ButtonSegment(value: 'descanso', label: Text('Descanso')),
            ],
            selected: {_estado},
            onSelectionChanged: (s) => setState(() => _estado = s.first),
          ),
          if (_estado != 'descanso') ...[
            const SizedBox(height: 14),
            DropdownButtonFormField<int?>(
              initialValue: _rutaId,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Ruta'),
              items: [
                const DropdownMenuItem(value: null, child: Text('— Sin ruta —')),
                for (final r in widget.rutas)
                  DropdownMenuItem(value: asInt(r['id']), child: Text(asStr(r['nombre']))),
              ],
              onChanged: (v) => setState(() => _rutaId = v),
            ),
            const SizedBox(height: 12),
            InkWell(
              onTap: _elegirConductor,
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Conductor',
                  suffixIcon: Icon(Icons.search),
                ),
                child: Text(cond.isEmpty ? '— Sin conductor —' : asStr(cond.first['nombre'])),
              ),
            ),
          ],
          if (trabaja) ...[
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _ini,
                  keyboardType: TextInputType.number,
                  inputFormatters: numFmt,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    labelText: 'REG Inicio',
                    helperText: b['_reg_ini_sugerida'] == true ? 'Continúa del día anterior' : null,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  controller: _fin,
                  keyboardType: TextInputType.number,
                  inputFormatters: numFmt,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    labelText: 'REG Fin',
                    helperText: ini != null && fin != null
                        ? (fin >= ini ? '= ${miles(fin - ini)} pax' : 'Menor que inicio')
                        : null,
                  ),
                ),
              ),
            ]),
            const SizedBox(height: 12),
            TextField(
              controller: _viajes,
              keyboardType: TextInputType.number,
              inputFormatters: numFmt,
              decoration: const InputDecoration(labelText: 'Viajes realizados'),
            ),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: _guardando ? null : _guardar,
            child: Text(_guardando ? 'Guardando…' : 'Guardar'),
          ),
        ]),
      ),
    );
  }
}

/// Lista buscable de conductores. Devuelve el id elegido, o 0 para "sin conductor".
class _SelectorConductor extends StatefulWidget {
  final List<Map<String, dynamic>> conductores;
  const _SelectorConductor(this.conductores);

  @override
  State<_SelectorConductor> createState() => _SelectorConductorState();
}

class _SelectorConductorState extends State<_SelectorConductor> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final q = _q.trim().toLowerCase();
    final lista = widget.conductores
        .where((c) => q.isEmpty || asStr(c['nombre']).toLowerCase().contains(q))
        .toList();
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .75,
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              autofocus: true,
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Buscar conductor'),
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          Expanded(
            child: ListView(children: [
              ListTile(
                title: const Text('— Sin conductor —'),
                onTap: () => Navigator.pop(context, 0),
              ),
              for (final c in lista)
                ListTile(
                  title: Text(asStr(c['nombre'])),
                  subtitle: asStr(c['cedula']).isEmpty ? null : Text('C.C. ${c['cedula']}'),
                  onTap: () => Navigator.pop(context, asInt(c['id'])),
                ),
            ]),
          ),
        ]),
      ),
    );
  }
}
