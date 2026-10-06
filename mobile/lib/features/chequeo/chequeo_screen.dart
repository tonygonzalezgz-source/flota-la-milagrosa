import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/gps.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';

/// Chequeo de despachadores: marca llegada y salida del puesto con la
/// ubicación GPS (endpoints /api/chequeo/*).
class ChequeoScreen extends ConsumerStatefulWidget {
  const ChequeoScreen({super.key});

  @override
  ConsumerState<ChequeoScreen> createState() => _ChequeoScreenState();
}

class _ChequeoScreenState extends ConsumerState<ChequeoScreen> {
  bool _cargando = true;
  bool _marcando = false;
  String? _error;
  Map<String, dynamic>? _hoy; // {fecha, puesto, chequeo}
  List<Map<String, dynamic>> _puestos = [];
  List<Map<String, dynamic>> _historial = [];
  int? _puestoId;

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
        api.get('/chequeo/hoy'),
        api.get('/puestos'),
        api.get('/chequeo/historial'),
      ]);
      _hoy = r[0] as Map<String, dynamic>;
      _puestos = asLista(r[1]).where((p) => asBool(p['activo'])).toList();
      _historial = asLista(r[2]);
      final asignado = _hoy?['puesto'] as Map<String, dynamic>?;
      _puestoId ??= asInt(asignado?['id']);
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  Future<void> _marcar(String tipo) async {
    if (tipo == 'llegada' && _puestos.isNotEmpty && _puestoId == null) {
      mostrarMensaje(context, 'Elige tu puesto de trabajo', error: true);
      return;
    }
    setState(() => _marcando = true);
    try {
      final pos = await ubicacionActual();
      final body = {
        'lat': pos.latitude,
        'lng': pos.longitude,
        'precision': pos.accuracy,
        if (tipo == 'llegada' && _puestoId != null) 'puesto_id': _puestoId,
      };
      await ref.read(apiClientProvider).post('/chequeo/$tipo', body: body);
      if (!mounted) return;
      mostrarMensaje(context, tipo == 'llegada' ? 'Llegada registrada' : 'Salida registrada');
      await _cargar();
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => _marcando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Chequeo')),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargar,
        builder: () => RefreshIndicator(
          onRefresh: _cargar,
          child: ListView(padding: const EdgeInsets.all(16), children: [
            _tarjetaHoy(),
            const TituloSeccion('Historial'),
            if (_historial.isEmpty) const VacioView('Sin registros en el periodo.'),
            for (final h in _historial) _filaHistorial(h),
          ]),
        ),
      ),
    );
  }

  Widget _tarjetaHoy() {
    final c = _hoy?['chequeo'] as Map<String, dynamic>?;
    final fecha = asStr(_hoy?['fecha']);
    final llegada = asStr(c?['hora_llegada']);
    final salida = asStr(c?['hora_salida']);

    Widget boton(String tipo, String texto, Color color) => FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: color, minimumSize: const Size.fromHeight(64)),
          onPressed: _marcando ? null : () => _marcar(tipo),
          icon: _marcando
              ? const SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
              : const Icon(Icons.my_location),
          label: Text(_marcando ? 'Obteniendo ubicación…' : texto),
        );

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(Fechas.larga(fecha),
              textAlign: TextAlign.center, style: const TextStyle(color: AppColors.muted)),
          const SizedBox(height: 14),
          if (c == null) ...[
            if (_puestos.isEmpty)
              const Etiqueta('⚠ Sin puestos creados — informa al administrador', AppColors.yellow)
            else
              DropdownButtonFormField<int>(
                initialValue: _puestoId,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Puesto de trabajo'),
                items: [
                  for (final p in _puestos)
                    DropdownMenuItem(value: asInt(p['id']), child: Text(asStr(p['nombre']))),
                ],
                onChanged: (v) => setState(() => _puestoId = v),
              ),
            const SizedBox(height: 16),
            boton('llegada', 'Marcar llegada', AppColors.green),
          ] else ...[
            Row(children: [
              Expanded(child: _hora('Llegada', llegada, AppColors.green)),
              const SizedBox(width: 12),
              Expanded(child: _hora('Salida', salida, AppColors.red)),
            ]),
            const SizedBox(height: 10),
            Text(
              c['puesto_nombre'] != null ? '📍 Puesto: ${c['puesto_nombre']}' : '⚠ Sin puesto registrado',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            if (salida.isEmpty)
              boton('salida', 'Marcar salida', AppColors.red)
            else
              Text('Jornada completa: ${_duracion(asInt(c['minutos_trabajados']))}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
          ],
          const SizedBox(height: 10),
          const Text('Se registra tu ubicación al momento de marcar.',
              textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      ),
    );
  }

  Widget _hora(String titulo, String hora, Color color) => Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .08),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(children: [
          Text(titulo, style: TextStyle(color: color, fontWeight: FontWeight.w600)),
          Text(hora.isEmpty ? '--:--' : hora.substring(0, 5),
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
        ]),
      );

  String _duracion(int? min) {
    if (min == null) return '—';
    return '${min ~/ 60} h ${min % 60} min';
  }

  Widget _filaHistorial(Map<String, dynamic> h) {
    final ll = asStr(h['hora_llegada']);
    final sa = asStr(h['hora_salida']);
    final verTodos = ref.read(sessionProvider).value?.rol != 'Despachador';
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: ListTile(
          title: Text(verTodos ? asStr(h['despachador']) : Fechas.corta(h['fecha'])),
          subtitle: Text([
            if (verTodos) Fechas.corta(h['fecha']),
            asStr(h['puesto']).isEmpty ? 'Sin puesto' : asStr(h['puesto']),
          ].join(' · ')),
          trailing: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('${ll.isEmpty ? '--' : ll.substring(0, 5)} → ${sa.isEmpty ? '--' : sa.substring(0, 5)}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
              Text(_duracion(asInt(h['minutos_trabajados'])),
                  style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            ],
          ),
        ),
      ),
    );
  }
}
