import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';

/// 30 ítems EXACTOS del formulario oficial (mismo texto que alistamiento.html
/// y `_ALIST_CAMPOS` en api/app.py). No modificar el texto de las preguntas.
const itemsAlistamiento = <(String, String)>[
  ('retrovisores', '¿Retrovisores?'),
  ('luz_estacionaria', '¿Luz Estacionaria?'),
  ('luz_alta_baja', '¿Luz alta-baja?'),
  ('luz_reversa', '¿Luz de reversa?'),
  ('logo_empresa', '¿Logo de la empresa?'),
  ('nivel_liquido_freno', '¿Nivel de liquido de freno?'),
  ('nivel_deposito_hidraulico', '¿Nivel deposito Hidráulico?'),
  ('nivel_refrigerante', '¿Nivel del refrigerante?'),
  ('presion_llantas', '¿Presión de las llantas?'),
  ('pito', '¿Pito?'),
  ('stop', '¿Stop?'),
  ('llantas_general', '¿Llantas en general?'),
  ('direccionales', '¿Direccionales?'),
  ('frenos_general', '¿Frenos en general?'),
  ('nivel_liquido_aceite', '¿Nivel del liquido de aceite?'),
  ('ballestas', '¿Ballestas?'),
  ('fugas_aceite', '¿Fugas de aceite?'),
  ('anclaje_bateria', '¿Anclaje y estado de la batería?'),
  ('dispositivo_luminoso', '¿Dispositivo luminoso?'),
  ('equipo_prevencion', '¿Equipo de prevención?'),
  ('cinturon_seguridad', '¿Cinturón de seguridad?'),
  ('salidas_emergencia', '¿Salidas de emergencia?'),
  ('aseo_vehiculo', '¿Aseo del vehículo?'),
  ('fugas_diafragmas', '¿Fugas en los diafragmas?'),
  ('asientos_anclados', '¿Asientas mal anclados?'),
  ('limpia_brillas', '¿Limpia-brillas?'),
  ('condiciones_botiquin', '¿Condiciones de botiquín?'),
  ('observaciones_adicionales', '¿Observaciones adicionales?'),
  ('lavada_primeriada', '¿Lavada primeriada?'),
  ('primeriada', '¿Primeriada?'),
];

const lugaresAlistamiento = ['CLT', 'TERMINAL P CATALUÑA', 'TERMINAL PABLO (RENACER)'];
const _responsable = 'Supervisor de Alistamiento de Flota';

Map<String, String> parseNovedades(dynamic raw) {
  if (raw == null) return {};
  if (raw is Map) return raw.map((k, v) => MapEntry(k.toString(), v.toString()));
  try {
    final m = jsonDecode(raw.toString());
    if (m is Map) return m.map((k, v) => MapEntry(k.toString(), v.toString()));
  } catch (_) {}
  return {};
}

/// Abre el formulario de alistamiento de hoy para un bus. Devuelve true si se guardó.
Future<bool> abrirAlistamiento(BuildContext context,
    {required int busId, required String titulo, int? conductorId}) async {
  final r = await Navigator.of(context).push<bool>(MaterialPageRoute(
    builder: (_) => AlistamientoForm(busId: busId, titulo: titulo, conductorId: conductorId),
  ));
  return r ?? false;
}

class AlistamientoForm extends ConsumerStatefulWidget {
  final int busId;
  final String titulo;
  final int? conductorId;
  const AlistamientoForm({super.key, required this.busId, required this.titulo, this.conductorId});

  @override
  ConsumerState<AlistamientoForm> createState() => _AlistamientoFormState();
}

class _AlistamientoFormState extends ConsumerState<AlistamientoForm> {
  final _hoy = Fechas.hoy();
  bool _cargando = true;
  bool _guardando = false;
  String? _error;
  String? _lugar;
  final Map<String, String?> _valores = {};
  final Map<String, TextEditingController> _novedades = {};

  @override
  void initState() {
    super.initState();
    for (final (campo, _) in itemsAlistamiento) {
      _novedades[campo] = TextEditingController();
    }
    _cargar();
  }

  @override
  void dispose() {
    for (final c in _novedades.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _cargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      final d = await ref
          .read(apiClientProvider)
          .get('/alistamiento', query: {'fecha': _hoy, 'bus_id': widget.busId});
      final datos = (d as Map<String, dynamic>?) ?? {};
      _lugar = lugaresAlistamiento.contains(datos['lugar']) ? datos['lugar'] as String : null;
      final nov = parseNovedades(datos['novedades']);
      for (final (campo, _) in itemsAlistamiento) {
        _valores[campo] = datos[campo] as String?;
        _novedades[campo]!.text = nov[campo] ?? '';
      }
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  int get _respondidos => _valores.values.where((v) => v != null).length;

  Future<void> _guardar() async {
    final faltan = itemsAlistamiento.length - _respondidos;
    if (faltan > 0 &&
        !await confirmar(context, 'Ítems sin responder',
            'Quedan $faltan ítems sin marcar. ¿Guardar de todos modos?', si: 'Guardar')) {
      return;
    }
    setState(() => _guardando = true);
    final novedades = <String, String>{};
    final body = <String, dynamic>{
      'fecha': _hoy,
      'bus_id': widget.busId,
      'conductor_id': widget.conductorId,
      'lugar': _lugar,
      'nombre_responsable': _responsable,
    };
    for (final (campo, _) in itemsAlistamiento) {
      body[campo] = _valores[campo];
      final txt = _novedades[campo]!.text.trim();
      if (_valores[campo] == 'otros' && txt.isNotEmpty) novedades[campo] = txt;
    }
    body['novedades'] = novedades;
    try {
      await ref.read(apiClientProvider).post('/alistamiento', body: body);
      if (!mounted) return;
      mostrarMensaje(context, 'Alistamiento guardado');
      Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) {
        mostrarMensaje(context, e.toString(), error: true);
        setState(() => _guardando = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.titulo),
        actions: [
          IconButton(
            tooltip: 'Ver historial',
            icon: const Icon(Icons.history),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => HistorialAlistamiento(busId: widget.busId, titulo: widget.titulo),
            )),
          ),
        ],
      ),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargar,
        builder: () => ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 100), children: [
          Text(Fechas.larga(_hoy), style: const TextStyle(color: AppColors.muted)),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: _lugar,
            isExpanded: true,
            decoration: const InputDecoration(labelText: '¿Lugar del alistamiento?'),
            items: [
              for (final l in lugaresAlistamiento) DropdownMenuItem(value: l, child: Text(l)),
            ],
            onChanged: (v) => setState(() => _lugar = v),
          ),
          const SizedBox(height: 8),
          for (var i = 0; i < itemsAlistamiento.length; i++) _item(i),
          const SizedBox(height: 12),
          TextFormField(
            initialValue: _responsable,
            readOnly: true,
            decoration: const InputDecoration(
              labelText: 'Nombre de quien realiza el alistamiento',
              filled: true,
              fillColor: Color(0xFFF4F4F6),
            ),
          ),
        ]),
      ),
      bottomNavigationBar: _cargando || _error != null
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(
                  onPressed: _guardando ? null : _guardar,
                  child: Text(_guardando
                      ? 'Guardando…'
                      : 'Guardar alistamiento ($_respondidos/${itemsAlistamiento.length})'),
                ),
              ),
            ),
    );
  }

  Widget _item(int i) {
    final (campo, label) = itemsAlistamiento[i];
    final v = _valores[campo];
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('${i + 1}. $label', style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              emptySelectionAllowed: true,
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: 'buena', label: Text('Buena')),
                ButtonSegment(value: 'mala', label: Text('Mala')),
                ButtonSegment(value: 'otros', label: Text('Otros')),
              ],
              selected: {?v},
              style: ButtonStyle(
                backgroundColor: WidgetStateProperty.resolveWith((s) {
                  if (!s.contains(WidgetState.selected)) return null;
                  return switch (v) {
                    'buena' => AppColors.green.withValues(alpha: .18),
                    'mala' => AppColors.red.withValues(alpha: .18),
                    _ => AppColors.yellow.withValues(alpha: .22),
                  };
                }),
              ),
              onSelectionChanged: (s) => setState(() => _valores[campo] = s.isEmpty ? null : s.first),
            ),
            if (v == 'otros') ...[
              const SizedBox(height: 8),
              TextField(
                controller: _novedades[campo],
                decoration: const InputDecoration(hintText: 'Describe la novedad…'),
              ),
            ],
          ]),
        ),
      ),
    );
  }
}

/// Historial de alistamientos de un bus (solo lectura).
class HistorialAlistamiento extends ConsumerStatefulWidget {
  final int busId;
  final String titulo;
  const HistorialAlistamiento({super.key, required this.busId, required this.titulo});

  @override
  ConsumerState<HistorialAlistamiento> createState() => _HistorialAlistamientoState();
}

class _HistorialAlistamientoState extends ConsumerState<HistorialAlistamiento> {
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _regs = [];

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
    try {
      _regs = asLista(await ref
          .read(apiClientProvider)
          .get('/alistamiento/historial', query: {'bus_id': widget.busId}));
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Historial · ${widget.titulo}')),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargar,
        builder: () => _regs.isEmpty
            ? const VacioView('Este vehículo aún no tiene alistamientos.')
            : ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: _regs.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (_, i) {
                  final r = _regs[i];
                  final malas = itemsAlistamiento.where((it) => r[it.$1] == 'mala').length;
                  final otros = itemsAlistamiento.where((it) => r[it.$1] == 'otros').length;
                  return Card(
                    child: ListTile(
                      title: Text(Fechas.corta(r['fecha'])),
                      subtitle: Text([asStr(r['lugar']), asStr(r['despachador_nombre'])]
                          .where((s) => s.isNotEmpty)
                          .join(' · ')),
                      trailing: malas + otros == 0
                          ? const Etiqueta('Sin novedades', AppColors.green)
                          : Etiqueta(
                              [if (malas > 0) '$malas mala${malas == 1 ? '' : 's'}', if (otros > 0) '$otros otros']
                                  .join(' · '),
                              malas > 0 ? AppColors.red : AppColors.yellow),
                      onTap: () => _detalle(r),
                    ),
                  );
                },
              ),
      ),
    );
  }

  void _detalle(Map<String, dynamic> r) {
    final nov = parseNovedades(r['novedades']);
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .8,
        builder: (_, sc) => ListView(controller: sc, padding: const EdgeInsets.all(16), children: [
          Text('Alistamiento del ${Fechas.corta(r['fecha'])}',
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text('Lugar: ${asStr(r['lugar']).isEmpty ? '—' : r['lugar']}'),
          Text('Responsable: ${asStr(r['nombre_responsable']).isEmpty ? '—' : r['nombre_responsable']}'),
          const Divider(height: 24),
          for (var i = 0; i < itemsAlistamiento.length; i++)
            Builder(builder: (_) {
              final (campo, label) = itemsAlistamiento[i];
              final v = asStr(r[campo]);
              final color = switch (v) {
                'buena' => AppColors.green,
                'mala' => AppColors.red,
                'otros' => AppColors.yellow,
                _ => AppColors.muted,
              };
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Text('${i + 1}. $label${nov[campo] != null ? '\n   → ${nov[campo]}' : ''}'),
                  ),
                  Etiqueta(v.isEmpty ? '—' : '${v[0].toUpperCase()}${v.substring(1)}', color),
                ]),
              );
            }),
        ]),
      ),
    );
  }
}
