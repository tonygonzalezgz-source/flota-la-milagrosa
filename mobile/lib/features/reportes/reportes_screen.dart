import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/movilidad.dart';
import '../../core/reportes.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/aurora.dart';
import '../../widgets/comunes.dart';
import 'reporte_excel.dart';

/// Colores de los estados del día (barra de días trabajados).
const _colorEstado = {
  EstadoDia.trabajado: AppColors.green,
  EstadoDia.taller: AppColors.yellow,
  EstadoDia.descanso: Color(0xFF94A3B8),
  EstadoDia.sinRegistro: Color(0xFFE2E8F0),
};

/// Rango más largo que se puede consultar de una vez.
const _maxDiasRango = 366;

String _mayuscula(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

/// Reportes del propietario: movilidad por rango y días trabajados de sus
/// buses, descargables en Excel (como "Reporte" en la web).
class ReportesScreen extends ConsumerStatefulWidget {
  /// Bus preseleccionado (al entrar desde el detalle de un bus).
  final int? busId;
  const ReportesScreen({super.key, this.busId});

  @override
  ConsumerState<ReportesScreen> createState() => _ReportesScreenState();
}

class _ReportesScreenState extends ConsumerState<ReportesScreen> {
  final _scroll = ScrollController();
  Periodo _periodo = Periodo.mes;
  late Rango _rango = Periodo.mes.rango();
  late int? _busId = widget.busId;

  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _buses = [];
  List<Map<String, dynamic>> _movilidad = [];
  List<Map<String, dynamic>>? _despacho;
  int _consulta = 0;
  bool _verTodoDiario = false;
  bool _exportando = false;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _cargar() async {
    final consulta = ++_consulta;
    setState(() {
      _cargando = true;
      _error = null;
    });
    final api = ref.read(apiClientProvider);
    final uid = ref.read(sessionProvider).value?.id;
    try {
      final r = await Future.wait([
        api.get('/buses', query: {'user_id': uid}),
        api.get('/movilidad/rango', query: {'desde': _rango.desde, 'hasta': _rango.hasta, 'user_id': uid}),
        // El despacho dice si el bus estuvo en taller o en descanso. Si no se
        // puede consultar, el reporte sale igual con lo que hay en movilidad.
        api
            .get('/despacho/historial', query: {'desde': _rango.desde, 'hasta': _rango.hasta})
            .then<Object?>((v) => v)
            .catchError((_) => null),
      ]);
      if (consulta != _consulta || !mounted) return;
      _buses = asLista(r[0]);
      _movilidad = asLista(r[1]);
      _despacho = r[2] == null ? null : asLista(r[2]);
    } catch (e) {
      if (consulta != _consulta || !mounted) return;
      _error = e.toString();
    }
    setState(() => _cargando = false);
  }

  void _elegirPeriodo(Periodo p) async {
    if (p == Periodo.personalizado) {
      final hoy = DateTime.parse(Fechas.hoy());
      final elegido = await showDateRangePicker(
        context: context,
        firstDate: DateTime(2023),
        lastDate: hoy,
        initialDateRange: DateTimeRange(start: DateTime.parse(_rango.desde), end: DateTime.parse(_rango.hasta)),
        helpText: 'Rango del reporte',
      );
      if (elegido == null || !mounted) return;
      if (elegido.duration.inDays + 1 > _maxDiasRango) {
        mostrarMensaje(context, 'Elige un rango de máximo un año.', error: true);
        return;
      }
      _rango = (desde: Fechas.iso(elegido.start), hasta: Fechas.iso(elegido.end));
    } else {
      _rango = p.rango();
    }
    _periodo = p;
    _verTodoDiario = false;
    _cargar();
  }

  void _elegirBus(int? id) {
    setState(() {
      _busId = id;
      _verTodoDiario = false;
    });
    _scroll.animateTo(0, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
  }

  Reporte? get _reporte => _cargando || _error != null
      ? null
      : Reporte.armar(rango: _rango, buses: _buses, movilidad: _movilidad, despacho: _despacho, busId: _busId);

  Rect _origenCompartir() {
    final t = MediaQuery.sizeOf(context);
    return Rect.fromLTWH(0, 0, t.width, t.height / 2); // necesario en iPad
  }

  Future<void> _compartirExcel(Reporte r) async {
    setState(() => _exportando = true);
    try {
      final bytes = Uint8List.fromList(excelReporte(r));
      await SharePlus.instance.share(ShareParams(
        files: [XFile.fromData(bytes, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')],
        fileNameOverrides: [nombreExcel(r)],
        subject: 'Reporte de movilidad',
        sharePositionOrigin: _origenCompartir(),
      ));
    } catch (e) {
      if (mounted) mostrarMensaje(context, 'No se pudo generar el Excel: $e', error: true);
    } finally {
      if (mounted) setState(() => _exportando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _reporte;
    return Scaffold(
      backgroundColor: AppColors.bgLight,
      body: RefreshIndicator(
        onRefresh: _cargar,
        child: ListView(controller: _scroll, padding: EdgeInsets.zero, children: [
          _cabecera(r),
          Transform.translate(
            offset: const Offset(0, -48),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 18),
              child: r == null
                  ? TarjetaAurora(
                      radio: 26,
                      sombra: sombraFuerte,
                      child: CargaView(
                        cargando: _cargando,
                        error: _error,
                        onReintentar: _cargar,
                        builder: () => const SizedBox(),
                      ),
                    )
                  : _contenido(r),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _cabecera(Reporte? r) {
    final fmt = DateFormat("d 'de' MMMM", 'es_CO');
    final dias = DateTime.parse(_rango.hasta).difference(DateTime.parse(_rango.desde)).inDays + 1;
    return CabeceraAurora(
      traslape: 72,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          BotonCabecera(icono: Icons.arrow_back, tooltip: 'Volver', onPressed: () => Navigator.of(context).pop()),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Reportes',
                  style: TextStyle(
                      fontFamily: Fuentes.titulo, fontSize: 21, fontWeight: FontWeight.w700, color: Colors.white)),
              Text('Movilidad y días trabajados', style: TextStyle(fontSize: 12, color: Color(0xFF9FB2E8))),
            ]),
          ),
        ]),
        const SizedBox(height: 16),
        _filaChips([
          for (final p in Periodo.values)
            (p == Periodo.personalizado && _periodo == p ? 'Otro rango ✓' : p.nombre, _periodo == p, () => _elegirPeriodo(p)),
        ]),
        if (_buses.length > 1) ...[
          const SizedBox(height: 8),
          _filaChips([
            ('Todos mis buses', _busId == null, () => _elegirBus(null)),
            for (final b in _buses) ('Bus ${b['numero']}', _busId == asInt(b['id']), () => _elegirBus(asInt(b['id']))),
          ]),
        ],
        const SizedBox(height: 12),
        Text(
          '${_mayuscula(fmt.format(DateTime.parse(_rango.desde)))} al ${fmt.format(DateTime.parse(_rango.hasta))}'
          ' · $dias día${dias == 1 ? '' : 's'}',
          style: const TextStyle(fontSize: 13, color: Color(0xFFC9D6FF)),
        ),
      ]),
    );
  }

  Widget _filaChips(List<(String, bool, VoidCallback)> chips) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (final (texto, activo, onTap) in chips)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Material(
                color: activo ? Colors.white : Colors.white.withValues(alpha: .1),
                shape: const StadiumBorder(),
                child: InkWell(
                  customBorder: const StadiumBorder(),
                  onTap: _cargando ? null : onTap,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                    child: Text(texto,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: activo ? AppColors.navy : Colors.white,
                        )),
                  ),
                ),
              ),
            ),
        ]),
      );

  Widget _contenido(Reporte r) {
    final t = r.total;
    final trabajados = r.cuantos(EstadoDia.trabajado);
    String dec(double v, [int n = 1]) => v.toStringAsFixed(n).replaceAll('.', ',');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      TarjetaAurora(
        radio: 26,
        sombra: sombraFuerte,
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Dinero bruto del periodo',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.muted)),
          const SizedBox(height: 6),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(pesos(t.dinero),
                style: const TextStyle(
                    fontFamily: Fuentes.titulo,
                    fontSize: 34,
                    fontWeight: FontWeight.w700,
                    letterSpacing: -1,
                    color: AppColors.dinero)),
          ),
          Text('${miles(t.pasajeros)} pasajeros × ${pesos(tarifaPasaje)}',
              style: const TextStyle(fontSize: 12, color: AppColors.muted)),
        ]),
      ),
      const SizedBox(height: 14),
      Row(children: [
        Expanded(
            child: _kpi('Pasajeros', miles(t.pasajeros),
                trabajados == 0 ? null : '${miles(t.pasajeros / trabajados)} por día trabajado')),
        const SizedBox(width: 10),
        Expanded(
            child: _kpi('Vueltas', miles(t.vueltas),
                t.vueltas == 0 ? null : '${miles(t.pasajerosPorVuelta)} pasajeros por vuelta')),
      ]),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: _kpi('Km recorridos', dec(t.km), null)),
        const SizedBox(width: 10),
        Expanded(child: _kpi('IPK', dec(t.ipkValor, 2), 'pasajeros por km', destacado: true)),
      ]),
      _titulo('Días trabajados'),
      if (!r.conDespacho) ...[
        const AvisoAurora(
          icono: Icons.info_outline,
          texto: Text('No se pudo consultar el despacho: los días sin movilidad salen como "sin registro" '
              'en vez de taller o descanso.'),
        ),
        const SizedBox(height: 10),
      ],
      TarjetaAurora(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (final (i, b) in r.buses.indexed) ...[
            if (i > 0) const Divider(height: 26),
            _diasBus(b, r.diasPeriodo),
          ],
          if (r.buses.isEmpty) const VacioView('No tienes vehículos asignados.'),
        ]),
      ),
      if (r.buses.length > 1) ...[
        _titulo('Por bus'),
        for (final b in r.buses) ...[_filaBus(b), const SizedBox(height: 8)],
      ],
      _titulo('Por ruta'),
      _tablaGrupos(r.porRuta, (v) => '${v.dias.length} día${v.dias.length == 1 ? '' : 's'} · ${miles(v.vueltas)} vueltas'),
      _titulo('Por conductor'),
      _tablaGrupos(
          r.porConductor,
          (v) => '${v.dias.length} día${v.dias.length == 1 ? '' : 's'} · ${miles(v.vueltas)} vueltas'
              '${v.vueltas == 0 ? '' : ' · ${miles(v.pasajerosPorVuelta)} pas/vuelta'}'),
      _titulo('Detalle diario'),
      if (r.diario.isEmpty)
        const TarjetaAurora(child: VacioView('Sin movilidad registrada en este periodo.', icono: Icons.event_busy)),
      for (final f in (_verTodoDiario ? r.diario : r.diario.take(20))) ...[_filaDia(f), const SizedBox(height: 8)],
      if (!_verTodoDiario && r.diario.length > 20)
        TextButton(
          onPressed: () => setState(() => _verTodoDiario = true),
          child: Text('Ver los ${r.diario.length} registros'),
        ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: _exportando ? null : () => _compartirExcel(r),
        icon: _exportando
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
            : const Icon(Icons.table_view_outlined),
        label: const Text('Descargar Excel'),
      ),
      const SizedBox(height: 14),
      Text(
        'Dinero bruto = pasajeros × ${pesos(tarifaPasaje)}. Un día cuenta como trabajado si tiene movilidad '
        'registrada o el despacho lo marcó "trabajando".',
        style: const TextStyle(fontSize: 11, color: AppColors.muted),
      ),
    ]);
  }

  Widget _titulo(String texto) => Padding(
        padding: const EdgeInsets.only(top: 22, bottom: 10),
        child: Text(texto, style: estiloTituloAurora),
      );

  Widget _kpi(String titulo, String valor, String? detalle, {bool destacado = false}) => TarjetaAurora(
        radio: 20,
        color: destacado ? AppColors.primary : Colors.white,
        sombra: destacado
            ? const [BoxShadow(color: Color(0x592F5BFF), blurRadius: 24, offset: Offset(0, 10))]
            : sombraSuave,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(titulo, style: TextStyle(fontSize: 12, color: destacado ? const Color(0xFFD6E0FF) : AppColors.muted)),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(valor,
                style: TextStyle(
                  fontFamily: Fuentes.titulo,
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  color: destacado ? Colors.white : AppColors.texto,
                )),
          ),
          if (detalle != null)
            Text(detalle,
                style: TextStyle(fontSize: 11, color: destacado ? const Color(0xFFD6E0FF) : AppColors.muted)),
        ]),
      );

  Widget _diasBus(ReporteBus b, int totalDias) {
    final trabajados = b.cuantos(EstadoDia.trabajado);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(child: Text(b.nombre, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15))),
        Text.rich(TextSpan(children: [
          TextSpan(
              text: '$trabajados',
              style: const TextStyle(fontFamily: Fuentes.titulo, fontWeight: FontWeight.w700, color: AppColors.dinero)),
          TextSpan(text: ' de $totalDias días', style: const TextStyle(color: AppColors.muted)),
        ])),
      ]),
      const SizedBox(height: 10),
      ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: SizedBox(
          height: 12,
          // stretch: sin él cada tramo de color queda de alto cero.
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            for (final e in EstadoDia.values)
              if (b.cuantos(e) > 0) Expanded(flex: b.cuantos(e), child: ColoredBox(color: _colorEstado[e]!)),
          ]),
        ),
      ),
      const SizedBox(height: 8),
      Wrap(spacing: 14, runSpacing: 4, children: [
        for (final e in EstadoDia.values)
          if (b.cuantos(e) > 0)
            Row(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 9,
                height: 9,
                decoration: BoxDecoration(
                  color: _colorEstado[e],
                  shape: BoxShape.circle,
                  border: e == EstadoDia.sinRegistro ? Border.all(color: const Color(0xFFCBD5E1)) : null,
                ),
              ),
              const SizedBox(width: 5),
              Text('${e.nombre} ${b.cuantos(e)}', style: const TextStyle(fontSize: 12, color: AppColors.muted)),
            ]),
      ]),
    ]);
  }

  Widget _filaBus(ReporteBus b) => TarjetaAurora(
        padding: const EdgeInsets.all(14),
        onTap: () => _elegirBus(b.id),
        child: Row(children: [
          Container(
            width: 46,
            height: 46,
            alignment: Alignment.center,
            decoration: BoxDecoration(color: AppColors.primary, borderRadius: BorderRadius.circular(15)),
            child: Text(b.numero,
                style: const TextStyle(
                    fontFamily: Fuentes.titulo, fontSize: 17, fontWeight: FontWeight.w700, color: Colors.white)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(b.nombre, style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(
                '${b.cuantos(EstadoDia.trabajado)} días · ${miles(b.totales.vueltas)} vueltas · '
                '${miles(b.totales.pasajeros)} pax',
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ]),
          ),
          Text(pesosCortos(b.totales.dinero),
              style: const TextStyle(
                  fontFamily: Fuentes.titulo, fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.dinero)),
        ]),
      );

  Widget _tablaGrupos(Map<String, Totales> grupos, String Function(Totales) detalle) {
    if (grupos.isEmpty) {
      return const TarjetaAurora(child: Text('Sin datos en este periodo.', style: TextStyle(color: AppColors.muted)));
    }
    return TarjetaAurora(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Column(children: [
        for (final (i, e) in grupos.entries.indexed) ...[
          if (i > 0) const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(e.key, style: const TextStyle(fontWeight: FontWeight.w700)),
                  Text(detalle(e.value), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                ]),
              ),
              const SizedBox(width: 8),
              Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                Text('${miles(e.value.pasajeros)} pax', style: const TextStyle(fontWeight: FontWeight.w700)),
                Text(pesosCortos(e.value.dinero),
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.dinero)),
              ]),
            ]),
          ),
        ],
      ]),
    );
  }

  Widget _filaDia(Map<String, dynamic> f) {
    final pax = asInt(f['pasajeros']) ?? 0;
    final conductor = conductorReporte(f);
    final ruta = rutaReporte(f);
    final novedad = asStr(f['novedades']).trim();
    final fecha = Fechas.parse(f['fecha']);
    return TarjetaAurora(
      radio: 18,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                '${fecha == null ? '' : _mayuscula(DateFormat('EEE d MMM', 'es_CO').format(fecha).replaceAll('.', ''))}'
                ' · Bus ${f['numero']}',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              Text(
                [conductor, ruta].where((s) => s.isNotEmpty).join(' · ').ifEmpty('Sin conductor ni ruta'),
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: AppColors.muted),
              ),
            ]),
          ),
          const SizedBox(width: 8),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${miles(pax)} pax · ${miles(asInt(f['vueltas']) ?? 0)} v',
                style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(pesos(dineroLiquidar(pax)),
                style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.dinero)),
          ]),
        ]),
        if (novedad.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(color: const Color(0xFFFFF4E0), borderRadius: BorderRadius.circular(10)),
            child: Text(novedad, style: const TextStyle(fontSize: 12, color: Color(0xFF5C3A00))),
          ),
        ],
      ]),
    );
  }
}

extension on String {
  String ifEmpty(String otro) => isEmpty ? otro : this;
}
