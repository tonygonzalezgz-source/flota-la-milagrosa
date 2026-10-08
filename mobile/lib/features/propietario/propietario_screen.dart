import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/movilidad.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/aurora.dart';
import '../../widgets/comunes.dart';
import '../../widgets/marca.dart' show logoBusControlAsset;
import '../chat/chat_screen.dart';
import '../reportes/reportes_screen.dart';
import 'grafica_semanal.dart';
import 'vehiculo_screen.dart';

/// Semanas que se muestran en la gráfica comparativa (incluida la actual).
const semanasGrafica = 8;

/// Saludo según la hora de Bogotá.
String saludo() {
  final h = Fechas.ahoraBogota().hour;
  if (h < 12) return 'Buenos días';
  if (h < 19) return 'Buenas tardes';
  return 'Buenas noches';
}

/// "Mis Buses" (estilo Aurora Clara): la semana en curso frente a la pasada,
/// la gráfica de las últimas semanas y los vehículos del propietario; tocando
/// uno se abre su detalle diario.
class PropietarioScreen extends ConsumerStatefulWidget {
  const PropietarioScreen({super.key});

  @override
  ConsumerState<PropietarioScreen> createState() => _PropietarioScreenState();
}

class _PropietarioScreenState extends ConsumerState<PropietarioScreen> {
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<Map<String, dynamic>> _movilidad = [];
  List<Map<String, dynamic>> _docs = [];
  late String _desde;

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
    final hoy = DateTime.parse(Fechas.hoy());
    _desde = Fechas.iso(lunesDe(hoy).subtract(const Duration(days: 7 * (semanasGrafica - 1))));
    try {
      final r = await Future.wait([
        api.get('/buses', query: {'user_id': uid}),
        api.get('/movilidad/rango', query: {'desde': _desde, 'hasta': Fechas.hoy(), 'user_id': uid}),
        api.get('/documentos/alertas'),
      ]);
      _buses = asLista(r[0]);
      _movilidad = asLista(r[1]);
      _docs = asLista(r[2]).where((d) => d['estado'] != 'sin_registrar').toList();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  Future<void> _salir() async {
    if (await confirmar(context, 'Cerrar sesión', '¿Deseas salir de BusControl?', si: 'Salir')) {
      ref.read(sessionProvider.notifier).logout();
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(sessionProvider).value;
    return Scaffold(
      backgroundColor: AppColors.bgLight,
      floatingActionButton: const BotonAsistente(),
      body: _cargando || _error != null
          ? Column(children: [
              _cabecera(user?.nombre ?? '', traslape: 24),
              Expanded(
                child: CargaView(
                  cargando: _cargando,
                  error: _error,
                  onReintentar: _cargar,
                  builder: () => const SizedBox(),
                ),
              ),
            ])
          : RefreshIndicator(onRefresh: _cargar, child: _contenido(user?.nombre ?? '')),
    );
  }

  Widget _cabecera(String nombre, {double traslape = 96}) {
    final puedeVolver = Navigator.of(context).canPop();
    final lunes = lunesDe(DateTime.parse(Fechas.hoy()));
    return CabeceraAurora(
      traslape: traslape,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (puedeVolver) ...[
            BotonCabecera(icono: Icons.arrow_back, tooltip: 'Volver', onPressed: () => Navigator.of(context).pop()),
            const SizedBox(width: 10),
          ],
          Container(
            width: 46,
            height: 46,
            padding: const EdgeInsets.all(7),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(15)),
            child: Image.asset(logoBusControlAsset),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(saludo(), style: const TextStyle(fontSize: 13, color: Color(0xFF9FB2E8))),
              Text(
                nombre,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontFamily: Fuentes.titulo,
                  fontSize: 21,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ]),
          ),
          if (!puedeVolver) BotonCabecera(icono: Icons.logout, tooltip: 'Cerrar sesión', onPressed: _salir),
        ]),
        const SizedBox(height: 14),
        Text(
          'Semana del ${DateFormat("d 'de' MMMM", 'es_CO').format(lunes)} a hoy',
          style: const TextStyle(fontSize: 13, color: Color(0xFFC9D6FF)),
        ),
      ]),
    );
  }

  Widget _contenido(String nombre) {
    final cmp = estaSemanaVsAnterior(_movilidad);
    final a = cmp.actual, b = cmp.anterior;

    return ListView(padding: EdgeInsets.zero, children: [
      _cabecera(nombre),
      // Todo el contenido sube 72 px para que la tarjeta del dinero se monte
      // sobre la cabecera, como en la propuesta C.
      Transform.translate(
        offset: const Offset(0, -72),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            TarjetaAurora(
              radio: 26,
              sombra: sombraFuerte,
              padding: const EdgeInsets.all(20),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  const Expanded(
                    child: Text(
                      'Dinero bruto de la semana',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.muted),
                    ),
                  ),
                  Variacion(variacion(a.pasajeros, b.pasajeros), pastilla: true),
                ]),
                const SizedBox(height: 6),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    pesos(dineroLiquidar(a.pasajeros)),
                    style: const TextStyle(
                      fontFamily: Fuentes.titulo,
                      fontSize: 34,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -1,
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '${miles(a.pasajeros)} pasajeros × ${pesos(tarifaPasaje)} · vs. mismos días de la semana pasada',
                  style: const TextStyle(fontSize: 12, color: AppColors.muted),
                ),
              ]),
            ),
            const SizedBox(height: 14),
            Row(children: [
              Expanded(
                child: _kpi(Icons.people_outline, AppColors.primary, AppColors.primarySoft,
                    miles(a.pasajeros), 'Pasajeros', variacion(a.pasajeros, b.pasajeros)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _kpi(Icons.loop, AppColors.blue, const Color(0xFFE6F7F5),
                    miles(a.vueltas), 'Vueltas', variacion(a.vueltas, b.vueltas)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _kpi(
                  Icons.speed,
                  const Color(0xFFB36B00),
                  const Color(0xFFFFF4E0),
                  a.ipkValor.toStringAsFixed(2).replaceAll('.', ','),
                  'IPK',
                  b.ipkValor == 0 ? null : variacion(a.ipkValor, b.ipkValor),
                ),
              ),
            ]),
            const SizedBox(height: 16),
            GraficaSemanal(semanas: semanas(_movilidad, n: semanasGrafica)),
            const SizedBox(height: 12),
            _accesoReportes(),
            for (final d in _docs) ...[const SizedBox(height: 12), _doc(d)],
            const SizedBox(height: 20),
            const Text('Mis vehículos', style: estiloTituloAurora),
            const SizedBox(height: 10),
            if (_buses.isEmpty) const VacioView('No tienes vehículos asignados.'),
            for (final bus in _buses) ...[_bus(bus), const SizedBox(height: 10)],
            const SizedBox(height: 4),
            Text(
              'Dinero bruto = pasajeros × ${pesos(tarifaPasaje)} (valor del pasaje). '
              'IPK = pasajeros ÷ kilómetros recorridos.',
              style: const TextStyle(fontSize: 11, color: AppColors.muted),
            ),
          ]),
        ),
      ),
    ]);
  }

  Widget _accesoReportes() => TarjetaAurora(
        padding: const EdgeInsets.all(14),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ReportesScreen())),
        child: const Row(children: [
          IconoSuave(Icons.assessment_outlined, color: AppColors.primary, fondo: AppColors.primarySoft, tamano: 44),
          SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Reportes de mis buses', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
              Text('Días trabajados, movilidad por rango y Excel',
                  style: TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
          ),
          Icon(Icons.chevron_right, color: AppColors.muted),
        ]),
      );

  Widget _kpi(IconData icono, Color color, Color fondo, String valor, String titulo, double? cambio) =>
      TarjetaAurora(
        radio: 20,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          IconoSuave(icono, color: color, fondo: fondo, tamano: 34),
          const SizedBox(height: 8),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              valor,
              style: const TextStyle(fontFamily: Fuentes.titulo, fontSize: 20, fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(height: 2),
          Text(titulo, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
          Variacion(cambio),
        ]),
      );

  Widget _bus(Map<String, dynamic> bus) {
    final id = asInt(bus['id']);
    final filas = _movilidad.where((m) => asInt(m['bus_id']) == id).toList()
      ..sort((x, y) => Fechas.normalizar(y['fecha']).compareTo(Fechas.normalizar(x['fecha'])));
    final semana = estaSemanaVsAnterior(filas).actual;
    final ultimo = filas.isEmpty ? null : filas.first;
    final placa = asStr(bus['placa']);
    final micro = asStr(bus['grupo']) == 'B';

    return TarjetaAurora(
      padding: const EdgeInsets.all(14),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => VehiculoScreen(bus: bus, filas: filas, desde: _desde),
      )),
      child: Row(children: [
        Container(
          width: 52,
          height: 52,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: micro ? AppColors.blue : AppColors.primary,
            borderRadius: BorderRadius.circular(17),
          ),
          child: Text(
            asStr(bus['numero']),
            style: const TextStyle(
              fontFamily: Fuentes.titulo,
              fontSize: 19,
              fontWeight: FontWeight.w700,
              color: Colors.white,
            ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(
              'Bus ${bus['numero']}${placa.isEmpty ? '' : ' · $placa'}',
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
            ),
            const SizedBox(height: 2),
            Text(
              '${miles(semana.pasajeros)} pax · ${miles(semana.vueltas)} vueltas',
              style: const TextStyle(fontSize: 13, color: Color(0xFF3A4666)),
            ),
            Text(
              ultimo == null
                  ? 'Sin registros recientes'
                  : 'Último día: ${conductorDe(ultimo).isEmpty ? Fechas.corta(ultimo['fecha']) : conductorDe(ultimo)}',
              style: const TextStyle(fontSize: 12, color: AppColors.muted),
              overflow: TextOverflow.ellipsis,
            ),
          ]),
        ),
        const SizedBox(width: 8),
        Text(
          pesosCortos(dineroLiquidar(semana.pasajeros)),
          style: const TextStyle(
            fontFamily: Fuentes.titulo,
            fontSize: 14,
            fontWeight: FontWeight.w700,
            color: AppColors.dinero,
          ),
        ),
      ]),
    );
  }

  Widget _doc(Map<String, dynamic> d) {
    final vencido = d['estado'] == 'vencido';
    final dias = asInt(d['dias_restantes']) ?? 0;
    return AvisoAurora(
      icono: vencido ? Icons.error_outline : Icons.schedule,
      critico: vencido,
      texto: Text.rich(TextSpan(children: [
        TextSpan(text: 'Bus ${d['bus_numero']} · ${asStr(d['tipo_label'])} '),
        TextSpan(
          text: vencido ? 'venció hace ${-dias} días' : 'vence en $dias días',
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ])),
    );
  }
}
