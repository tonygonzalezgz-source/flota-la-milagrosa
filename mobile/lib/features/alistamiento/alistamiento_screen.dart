import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import 'alistamiento_form.dart';

/// Lista de unidades que trabajan hoy con su estado de alistamiento
/// (vista del Conductor, Analista y Jefe de Ruta; igual que alistamiento.html).
class AlistamientoScreen extends ConsumerStatefulWidget {
  const AlistamientoScreen({super.key});

  @override
  ConsumerState<AlistamientoScreen> createState() => _AlistamientoScreenState();
}

class _AlistamientoScreenState extends ConsumerState<AlistamientoScreen> {
  final _hoy = Fechas.hoy();
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
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
    try {
      final d = await ref.read(apiClientProvider).get('/despacho', query: {'fecha': _hoy});
      _buses = asLista((d as Map<String, dynamic>)['buses']);
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  @override
  Widget build(BuildContext context) {
    final trabajan = _buses.where((b) => (b['estado'] ?? 'trabajando') == 'trabajando').toList();
    final listos = trabajan.where((b) => asBool(b['tiene_alistamiento'])).length;
    final q = _filtro.trim().toLowerCase();
    final visibles = trabajan
        .where((b) => q.isEmpty || '${b['numero']} ${b['placa'] ?? ''}'.toLowerCase().contains(q))
        .toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Alistamiento')),
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
              Expanded(child: Indicador('Pendientes', '${trabajan.length - listos}', AppColors.yellow)),
              const SizedBox(width: 10),
              Expanded(child: Indicador('Alistados', '$listos', AppColors.green)),
              const SizedBox(width: 10),
              Expanded(child: Indicador('Trabajando', '${trabajan.length}', AppColors.primary)),
            ]),
            const SizedBox(height: 12),
            TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Buscar por número o placa',
              ),
              onChanged: (v) => setState(() => _filtro = v),
            ),
            if (visibles.isEmpty) const VacioView('No hay unidades trabajando hoy.'),
            for (final g in ['A', 'B']) ...[
              if (visibles.any((b) => b['grupo'] == g)) TituloSeccion(grupoLabel(g)),
              for (final b in visibles.where((b) => b['grupo'] == g)) _fila(b),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _fila(Map<String, dynamic> b) {
    final ok = asBool(b['tiene_alistamiento']);
    final titulo = 'Bus ${b['numero']}${asStr(b['placa']).isEmpty ? '' : ' · ${b['placa']}'}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor: (ok ? AppColors.green : AppColors.yellow).withValues(alpha: .15),
            child: Icon(ok ? Icons.check : Icons.priority_high,
                color: ok ? AppColors.green : AppColors.yellow),
          ),
          title: Text(titulo, style: const TextStyle(fontWeight: FontWeight.w700)),
          trailing: Etiqueta(ok ? '✓ Ver' : '⚠ Registrar', ok ? AppColors.green : AppColors.yellow),
          onTap: () async {
            final guardado = await abrirAlistamiento(context,
                busId: asInt(b['id'])!, titulo: titulo, conductorId: asInt(b['conductor_id']));
            if (guardado) setState(() => b['tiene_alistamiento'] = 1);
          },
        ),
      ),
    );
  }
}
