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
import '../reportes/reportes_screen.dart';
import 'grafica_semanal.dart';
import 'propietario_screen.dart' show semanasGrafica;

String _mayuscula(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

/// Detalle de un vehículo del propietario (estilo Aurora Clara): lo que pasó
/// en la fecha elegida (dinero, pasajeros, vueltas, km, IPK, conductor, ruta y
/// novedades), su gráfica semanal y los últimos días registrados.
class VehiculoScreen extends ConsumerStatefulWidget {
  final Map<String, dynamic> bus;

  /// Filas de movilidad de este bus ya cargadas por "Mis Buses" (desde [desde]).
  final List<Map<String, dynamic>> filas;
  final String desde;

  const VehiculoScreen({
    super.key,
    required this.bus,
    required this.filas,
    required this.desde,
  });

  @override
  ConsumerState<VehiculoScreen> createState() => _VehiculoScreenState();
}

class _VehiculoScreenState extends ConsumerState<VehiculoScreen> {
  final _scroll = ScrollController();
  late final Map<String, Map<String, dynamic>> _porFecha = {
    for (final f in widget.filas) Fechas.normalizar(f['fecha']): f,
  };

  /// Fechas anteriores a [widget.desde] ya consultadas (con o sin registro).
  final Set<String> _consultadas = {};
  late String _fecha;
  bool _buscando = false;

  int get _busId => asInt(widget.bus['id'])!;

  @override
  void initState() {
    super.initState();
    // Arranca en el último día con registro; si no hay ninguno, hoy.
    final fechas = _porFecha.keys.toList()..sort();
    _fecha = fechas.isEmpty ? Fechas.hoy() : fechas.last;
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _irA(String fecha) async {
    setState(() => _fecha = fecha);
    // Lo anterior al rango de "Mis Buses" se pide al servidor bajo demanda.
    if (fecha.compareTo(widget.desde) >= 0 || _consultadas.contains(fecha)) {
      return;
    }
    setState(() => _buscando = true);
    try {
      final uid = ref.read(sessionProvider).value?.id;
      final filas = asLista(
        await ref.read(apiClientProvider).get('/movilidad', query: {'fecha': fecha, 'user_id': uid}),
      );
      _consultadas.add(fecha);
      for (final f in filas.where((f) => asInt(f['bus_id']) == _busId)) {
        _porFecha[Fechas.normalizar(f['fecha'])] = f;
      }
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => _buscando = false);
    }
  }

  void _mover(int dias) => _irA(Fechas.iso(DateTime.parse(_fecha).add(Duration(days: dias))));

  Future<void> _elegirFecha() async {
    final hoy = DateTime.parse(Fechas.hoy());
    final d = await showDatePicker(
      context: context,
      initialDate: DateTime.parse(_fecha),
      firstDate: DateTime(2023),
      lastDate: hoy,
    );
    if (d != null) _irA(Fechas.iso(d));
  }

  /// 'Martes 6 de octubre' (con el año si no es el actual).
  String _fechaLarga(String iso) {
    final d = DateTime.parse(iso);
    final mismoAno = d.year == DateTime.parse(Fechas.hoy()).year;
    final f = DateFormat(mismoAno ? "EEEE d 'de' MMMM" : "EEEE d 'de' MMMM 'de' y", 'es_CO');
    return _mayuscula(f.format(d));
  }

  /// 'Mar 6 oct'
  String _fechaCorta(String iso) =>
      _mayuscula(DateFormat('EEE d MMM', 'es_CO').format(DateTime.parse(iso)).replaceAll('.', ''));

  @override
  Widget build(BuildContext context) {
    final recientes = _porFecha.values.toList()
      ..sort((a, b) => Fechas.normalizar(b['fecha']).compareTo(Fechas.normalizar(a['fecha'])));

    return Scaffold(
      backgroundColor: AppColors.bgLight,
      body: ListView(controller: _scroll, padding: EdgeInsets.zero, children: [
        _cabecera(),
        // El contenido sube para que la tarjeta del dinero se monte sobre la
        // cabecera, como en la propuesta C.
        Transform.translate(
          offset: const Offset(0, -86),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              ..._dia(),
              const SizedBox(height: 16),
              GraficaSemanal(semanas: semanas(widget.filas, n: semanasGrafica)),
              const SizedBox(height: 20),
              const Text('Últimos días', style: estiloTituloAurora),
              const SizedBox(height: 10),
              if (recientes.isEmpty)
                const TarjetaAurora(
                  child: VacioView('Este vehículo no tiene registros de movilidad recientes.'),
                ),
              for (final f in recientes.take(21)) ...[_filaReciente(f), const SizedBox(height: 8)],
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _cabecera() {
    final placa = asStr(widget.bus['placa']);
    final odometro = asDouble(widget.bus['km_actuales']) ?? 0;
    final esHoy = _fecha == Fechas.hoy();

    return CabeceraAurora(
      traslape: 110,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          BotonCabecera(icono: Icons.arrow_back, tooltip: 'Volver', onPressed: () => Navigator.of(context).pop()),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                'Bus ${widget.bus['numero']}${placa.isEmpty ? '' : ' · $placa'}',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontFamily: Fuentes.titulo,
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
              if (odometro > 0)
                Text(
                  'Odómetro ${miles(odometro)} km',
                  style: const TextStyle(fontSize: 12, color: Color(0xFF9FB2E8)),
                ),
            ]),
          ),
          BotonCabecera(
            icono: Icons.assessment_outlined,
            tooltip: 'Reporte de este bus',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => ReportesScreen(busId: _busId)),
            ),
          ),
        ]),
        const SizedBox(height: 18),
        Row(children: [
          BotonCabecera(icono: Icons.chevron_left, tooltip: 'Día anterior', onPressed: () => _mover(-1)),
          const SizedBox(width: 8),
          Expanded(
            child: Material(
              color: Colors.white,
              shape: const StadiumBorder(),
              child: InkWell(
                customBorder: const StadiumBorder(),
                onTap: _elegirFecha,
                child: SizedBox(
                  height: 44,
                  child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    const Icon(Icons.calendar_today_outlined, size: 18, color: AppColors.primary),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        _fechaLarga(_fecha),
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14, color: AppColors.navy),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          BotonCabecera(
            icono: Icons.chevron_right,
            tooltip: 'Día siguiente',
            tenue: esHoy,
            onPressed: esHoy ? null : () => _mover(1),
          ),
        ]),
      ]),
    );
  }

  List<Widget> _dia() {
    if (_buscando) {
      return [
        const TarjetaAurora(
          radio: 26,
          sombra: sombraFuerte,
          padding: EdgeInsets.all(48),
          child: Center(child: CircularProgressIndicator()),
        ),
      ];
    }
    final f = _porFecha[_fecha];
    if (f == null) {
      return [
        const TarjetaAurora(
          radio: 26,
          sombra: sombraFuerte,
          child: VacioView('No hay registro de movilidad para este día.', icono: Icons.event_busy),
        ),
      ];
    }
    final pax = asInt(f['pasajeros']) ?? 0;
    final km = asDouble(f['km_recorridos']) ?? 0;
    final conductor = conductorDe(f);
    final ruta = rutaDe(f);
    final novedades = asStr(f['novedades']).trim();

    return [
      TarjetaAurora(
        radio: 26,
        sombra: sombraFuerte,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 22),
        child: Column(children: [
          const Text(
            'Dinero bruto a liquidar',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.muted),
          ),
          const SizedBox(height: 4),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              pesos(dineroLiquidar(pax)),
              style: const TextStyle(
                fontFamily: Fuentes.titulo,
                fontSize: 38,
                fontWeight: FontWeight.w700,
                letterSpacing: -1,
                color: AppColors.dinero,
              ),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '${miles(pax)} pasajeros × ${pesos(tarifaPasaje)}',
            style: const TextStyle(fontSize: 12, color: AppColors.muted),
          ),
        ]),
      ),
      const SizedBox(height: 16),
      Row(children: [
        Expanded(child: _dato('Pasajeros', miles(pax))),
        const SizedBox(width: 10),
        Expanded(child: _dato('Vueltas', miles(asInt(f['vueltas']) ?? 0))),
      ]),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: _dato('Km recorridos', km.toStringAsFixed(1).replaceAll('.', ','))),
        const SizedBox(width: 10),
        Expanded(child: _dato('IPK', ipk(pax, km).toStringAsFixed(2).replaceAll('.', ','), destacado: true)),
      ]),
      const SizedBox(height: 16),
      TarjetaAurora(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _linea(Icons.person_outline, AppColors.primary, AppColors.primarySoft, 'Conductor',
              conductor.isEmpty ? 'Sin registrar' : conductor),
          const SizedBox(height: 14),
          _linea(Icons.route_outlined, AppColors.blue, const Color(0xFFE6F7F5), 'Ruta',
              ruta.isEmpty ? 'Sin registrar' : ruta),
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: novedades.isEmpty ? AppColors.campo : const Color(0xFFFFF4E0),
              borderRadius: BorderRadius.circular(16),
            ),
            child: novedades.isEmpty
                ? const Row(children: [
                    Icon(Icons.check_circle_outline, size: 18, color: AppColors.dinero),
                    SizedBox(width: 8),
                    Text('Sin novedades reportadas', style: TextStyle(fontSize: 13, color: AppColors.muted)),
                  ])
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text(
                      'Novedad reportada',
                      style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF8A5200)),
                    ),
                    const SizedBox(height: 4),
                    Text(novedades, style: const TextStyle(fontSize: 14, color: Color(0xFF5C3A00))),
                  ]),
          ),
        ]),
      ),
    ];
  }

  /// Dato del día; [destacado] lo pinta en azul (IPK, como en la propuesta).
  Widget _dato(String titulo, String valor, {bool destacado = false}) => TarjetaAurora(
        radio: 20,
        color: destacado ? AppColors.primary : Colors.white,
        sombra: destacado
            ? const [BoxShadow(color: Color(0x592F5BFF), blurRadius: 24, offset: Offset(0, 10))]
            : sombraSuave,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(titulo,
              style: TextStyle(fontSize: 12, color: destacado ? const Color(0xFFD6E0FF) : AppColors.muted)),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              valor,
              style: TextStyle(
                fontFamily: Fuentes.titulo,
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: destacado ? Colors.white : AppColors.texto,
              ),
            ),
          ),
        ]),
      );

  Widget _linea(IconData icono, Color color, Color fondo, String titulo, String valor) => Row(children: [
        IconoSuave(icono, color: color, fondo: fondo, tamano: 40),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(titulo, style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            Text(valor, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          ]),
        ),
      ]);

  Widget _filaReciente(Map<String, dynamic> f) {
    final fecha = Fechas.normalizar(f['fecha']);
    final pax = asInt(f['pasajeros']) ?? 0;
    final sel = fecha == _fecha;
    final conductor = conductorDe(f);
    return TarjetaAurora(
      radio: 18,
      color: sel ? const Color(0xFFF4F7FF) : Colors.white,
      borde: Border.all(color: sel ? AppColors.primary : Colors.transparent, width: 1.5),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      onTap: () {
        _irA(fecha);
        _scroll.animateTo(0, duration: const Duration(milliseconds: 350), curve: Curves.easeOut);
      },
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(
              _fechaCorta(fecha),
              style: TextStyle(fontWeight: FontWeight.w700, color: sel ? AppColors.primary : AppColors.texto),
            ),
            Text(
              conductor.isEmpty ? 'Conductor sin registrar' : conductor,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12, color: AppColors.muted),
            ),
          ]),
        ),
        const SizedBox(width: 8),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${miles(pax)} pax', style: const TextStyle(fontWeight: FontWeight.w700)),
          Text(
            pesos(dineroLiquidar(pax)),
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.dinero),
          ),
        ]),
      ]),
    );
  }
}
