import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';

/// "Mis Buses": resumen del mes para el propietario (movilidad, ingreso
/// estimado, documentos por vencer y alertas de mantenimiento).
class PropietarioScreen extends ConsumerStatefulWidget {
  const PropietarioScreen({super.key});

  @override
  ConsumerState<PropietarioScreen> createState() => _PropietarioScreenState();
}

class _PropietarioScreenState extends ConsumerState<PropietarioScreen> {
  bool _cargando = true;
  String? _error;
  List<Bus> _buses = [];
  List<Map<String, dynamic>> _movilidad = [];
  List<Map<String, dynamic>> _docs = [];
  List<Map<String, dynamic>> _alertas = [];
  double _tarifa = 0;

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
    final uid = ref.read(sessionProvider).value?.id;
    try {
      final r = await Future.wait([
        api.get('/buses', query: {'user_id': uid}),
        api.get('/movilidad/rango',
            query: {'desde': Fechas.primerDiaMes(), 'hasta': Fechas.hoy(), 'user_id': uid}),
        api.get('/tarifas'),
        api.get('/documentos/alertas'),
        api.get('/dashboard/propietario', query: {'user_id': uid}),
      ]);
      _buses = asLista(r[0]).map(Bus.fromJson).toList();
      _movilidad = asLista(r[1]);
      // Ingreso estimado = pasajeros × promedio de las tarifas activas
      // (mismo cálculo que dashboard-propietario.html).
      final activas = asLista(r[2]).where((t) => asBool(t['activa'])).toList();
      _tarifa = activas.isEmpty
          ? 0
          : activas.fold<double>(0, (s, t) => s + (asDouble(t['valor']) ?? 0)) / activas.length;
      _docs = asLista(r[3]);
      _alertas = asLista((r[4] as Map<String, dynamic>)['alerts']);
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  @override
  Widget build(BuildContext context) {
    int suma(String campo, [Iterable<Map<String, dynamic>>? regs]) =>
        (regs ?? _movilidad).fold<int>(0, (s, m) => s + (asInt(m[campo]) ?? 0));
    final pax = suma('pasajeros');
    final docsCriticos = _docs.where((d) => d['estado'] != 'sin_registrar').toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Mis Buses')),
      body: CargaView(
        cargando: _cargando,
        error: _error,
        onReintentar: _cargar,
        builder: () => RefreshIndicator(
          onRefresh: _cargar,
          child: ListView(padding: const EdgeInsets.all(16), children: [
            Text('Mes en curso · desde ${Fechas.corta(Fechas.primerDiaMes())}',
                style: const TextStyle(color: AppColors.muted)),
            const SizedBox(height: 10),
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.7,
              children: [
                Indicador('Pasajeros', miles(pax), AppColors.primary, icono: Icons.people_outline),
                Indicador('Ingreso estimado', pesos(pax * _tarifa), AppColors.green,
                    icono: Icons.payments_outlined),
                Indicador('Vueltas', miles(suma('vueltas')), AppColors.blue, icono: Icons.loop),
                Indicador('Vehículos', '${_buses.length}', AppColors.yellow,
                    icono: Icons.directions_bus_outlined),
              ],
            ),
            if (docsCriticos.isNotEmpty) ...[
              const TituloSeccion('Documentos'),
              for (final d in docsCriticos) _doc(d),
            ],
            if (_alertas.isNotEmpty) ...[
              const TituloSeccion('Alertas de mantenimiento'),
              for (final a in _alertas)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Card(
                    child: ListTile(
                      leading: Icon(Icons.build_circle_outlined,
                          color: a['estado'] == 'alert' ? AppColors.red : AppColors.yellow),
                      title: Text('Bus ${a['bus_numero']} · ${asStr(a['novedad_label'])}'),
                      subtitle: asStr(a['ultima_obs']).isEmpty ? null : Text(asStr(a['ultima_obs'])),
                    ),
                  ),
                ),
            ],
            const TituloSeccion('Por vehículo'),
            if (_buses.isEmpty) const VacioView('No tienes vehículos asignados.'),
            for (final b in _buses)
              Builder(builder: (_) {
                final regs = _movilidad.where((m) => asInt(m['bus_id']) == b.id);
                final p = suma('pasajeros', regs);
                return Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Card(
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor: AppColors.primary.withValues(alpha: .12),
                        child: Text(b.numero,
                            style: const TextStyle(color: AppColors.primary, fontWeight: FontWeight.w800, fontSize: 13)),
                      ),
                      title: Text(b.etiqueta, style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text('${regs.length} días · ${miles(suma('vueltas', regs))} vueltas'),
                      trailing: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text('${miles(p)} pax', style: const TextStyle(fontWeight: FontWeight.w700)),
                          Text(pesos(p * _tarifa),
                              style: const TextStyle(fontSize: 12, color: AppColors.green)),
                        ],
                      ),
                    ),
                  ),
                );
              }),
            const SizedBox(height: 8),
            const Text('El ingreso es un estimado: pasajeros × tarifa promedio vigente.',
                style: TextStyle(fontSize: 12, color: AppColors.muted)),
          ]),
        ),
      ),
    );
  }

  Widget _doc(Map<String, dynamic> d) {
    final vencido = d['estado'] == 'vencido';
    final dias = asInt(d['dias_restantes']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: ListTile(
          leading: Icon(vencido ? Icons.error_outline : Icons.schedule,
              color: vencido ? AppColors.red : AppColors.yellow),
          title: Text('Bus ${d['bus_numero']} · ${asStr(d['tipo_label'])}'),
          subtitle: Text('Vence ${Fechas.corta(d['fecha_vencimiento'])}'),
          trailing: Etiqueta(
            vencido ? 'Vencido hace ${-(dias ?? 0)}d' : 'Faltan ${dias ?? 0}d',
            vencido ? AppColors.red : AppColors.yellow,
          ),
        ),
      ),
    );
  }
}
