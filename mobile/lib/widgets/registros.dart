import 'package:flutter/material.dart';

import '../core/fechas.dart';
import '../core/modelos.dart';
import '../core/theme.dart';
import 'comunes.dart';
import 'fotos.dart';

/// Descripción de cómo mostrar un registro en el historial.
class FilaRegistro {
  final String titulo;
  final String subtitulo;
  final String? descripcion;
  final Widget? etiqueta;
  final int numFotos;
  const FilaRegistro({
    required this.titulo,
    required this.subtitulo,
    this.descripcion,
    this.etiqueta,
    this.numFotos = 0,
  });
}

/// Historial genérico de registros con evidencias (EDS, lavada, tecnología,
/// gastos): filtro por rango de fechas, ver fotos y borrar si se permite.
class HistorialRegistros extends StatefulWidget {
  final Future<List<Map<String, dynamic>>> Function(String? desde, String? hasta) cargar;
  final FilaRegistro Function(Map<String, dynamic> r) fila;
  final Future<List<String>> Function(Map<String, dynamic> r)? fotos;
  final Future<void> Function(Map<String, dynamic> r)? borrar;
  final bool Function(Map<String, dynamic> r)? puedeBorrar;
  final Widget Function(List<Map<String, dynamic>> regs)? encabezado;

  const HistorialRegistros({
    super.key,
    required this.cargar,
    required this.fila,
    this.fotos,
    this.borrar,
    this.puedeBorrar,
    this.encabezado,
  });

  @override
  State<HistorialRegistros> createState() => HistorialRegistrosState();
}

class HistorialRegistrosState extends State<HistorialRegistros>
    with AutomaticKeepAliveClientMixin {
  bool _cargando = true;
  String? _error;
  List<Map<String, dynamic>> _regs = [];
  DateTimeRange? _rango;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    recargar();
  }

  Future<void> recargar() async {
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      _regs = await widget.cargar(
        _rango == null ? null : Fechas.iso(_rango!.start),
        _rango == null ? null : Fechas.iso(_rango!.end),
      );
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _cargando = false);
  }

  Future<void> _elegirRango() async {
    final hoy = DateTime.parse(Fechas.hoy());
    final r = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2023),
      lastDate: hoy,
      initialDateRange: _rango,
    );
    if (r != null) {
      _rango = r;
      recargar();
    }
  }

  Future<void> _verFotos(Map<String, dynamic> r) async {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    );
    try {
      final f = await widget.fotos!(r);
      if (!mounted) return;
      Navigator.of(context).pop();
      await verFotos(context, f);
    } catch (e) {
      if (!mounted) return;
      Navigator.of(context).pop();
      mostrarMensaje(context, e.toString(), error: true);
    }
  }

  Future<void> _borrar(Map<String, dynamic> r) async {
    if (!await confirmar(context, 'Eliminar registro', 'Esta acción no se puede deshacer.',
        si: 'Eliminar')) {
      return;
    }
    try {
      await widget.borrar!(r);
      if (!mounted) return;
      mostrarMensaje(context, 'Registro eliminado');
      recargar();
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return CargaView(
      cargando: _cargando,
      error: _error,
      onReintentar: recargar,
      builder: () => RefreshIndicator(
        onRefresh: recargar,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _elegirRango,
                icon: const Icon(Icons.date_range),
                label: Text(_rango == null
                    ? 'Todas las fechas'
                    : '${Fechas.corta(Fechas.iso(_rango!.start))} – ${Fechas.corta(Fechas.iso(_rango!.end))}'),
              ),
            ),
            if (_rango != null)
              IconButton(
                tooltip: 'Quitar filtro',
                icon: const Icon(Icons.clear),
                onPressed: () {
                  _rango = null;
                  recargar();
                },
              ),
          ]),
          if (widget.encabezado != null) ...[
            const SizedBox(height: 12),
            widget.encabezado!(_regs),
          ],
          const SizedBox(height: 8),
          if (_regs.isEmpty) const VacioView('No hay registros.'),
          for (final r in _regs) _tarjeta(r),
        ]),
      ),
    );
  }

  Widget _tarjeta(Map<String, dynamic> r) {
    final f = widget.fila(r);
    final borrable = widget.borrar != null && (widget.puedeBorrar?.call(r) ?? true);
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 6, 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(
                child: Text(f.titulo, style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
              ?f.etiqueta,
              if (borrable)
                IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.delete_outline, color: AppColors.red),
                  onPressed: () => _borrar(r),
                ),
            ]),
            Text(f.subtitulo, style: const TextStyle(color: AppColors.muted, fontSize: 13)),
            if ((f.descripcion ?? '').isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(f.descripcion!),
            ],
            if (widget.fotos != null && f.numFotos > 0)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () => _verFotos(r),
                  icon: const Icon(Icons.photo_outlined, size: 18),
                  label: Text('Ver evidencias (${f.numFotos})'),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}

/// Campo de fecha (por defecto hoy en Bogotá) con selector de calendario.
class CampoFecha extends StatelessWidget {
  final String valor;
  final ValueChanged<String> onChanged;
  final String label;
  const CampoFecha({super.key, required this.valor, required this.onChanged, this.label = 'Fecha'});

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: () async {
          final hoy = DateTime.parse(Fechas.hoy());
          final d = await showDatePicker(
            context: context,
            initialDate: DateTime.tryParse(valor) ?? hoy,
            firstDate: DateTime(2023),
            lastDate: hoy,
          );
          if (d != null) onChanged(Fechas.iso(d));
        },
        child: InputDecorator(
          decoration: InputDecoration(labelText: label, suffixIcon: const Icon(Icons.calendar_today)),
          child: Text(Fechas.corta(valor)),
        ),
      );
}

/// Selector de vehículo con buscador (la flota tiene ~100 unidades: un
/// desplegable simple es incómodo en el celular).
class CampoBus extends StatelessWidget {
  final List<Bus> buses;
  final int? valor;
  final ValueChanged<int?> onChanged;
  final String label;
  const CampoBus({
    super.key,
    required this.buses,
    required this.valor,
    required this.onChanged,
    this.label = 'Vehículo',
  });

  Future<void> _elegir(BuildContext context) async {
    final id = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _BuscadorBus(buses),
    );
    if (id != null) onChanged(id);
  }

  @override
  Widget build(BuildContext context) {
    final sel = buses.where((b) => b.id == valor);
    return InkWell(
      onTap: () => _elegir(context),
      child: InputDecorator(
        isEmpty: sel.isEmpty,
        decoration: InputDecoration(labelText: label, suffixIcon: const Icon(Icons.search)),
        child: sel.isEmpty ? null : Text(sel.first.etiqueta),
      ),
    );
  }
}

class _BuscadorBus extends StatefulWidget {
  final List<Bus> buses;
  const _BuscadorBus(this.buses);

  @override
  State<_BuscadorBus> createState() => _BuscadorBusState();
}

class _BuscadorBusState extends State<_BuscadorBus> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final q = _q.trim().toLowerCase();
    final lista = widget.buses
        .where((b) => q.isEmpty || b.numero.toLowerCase() == q || b.etiqueta.toLowerCase().contains(q))
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
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: 'Número o placa',
              ),
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          Expanded(
            child: lista.isEmpty
                ? const VacioView('Sin coincidencias')
                : ListView.builder(
                    itemCount: lista.length,
                    itemBuilder: (_, i) => ListTile(
                      leading: const Icon(Icons.directions_bus_outlined),
                      title: Text(lista[i].etiqueta),
                      subtitle: lista[i].modelo.isEmpty ? null : Text(lista[i].modelo),
                      onTap: () => Navigator.pop(context, lista[i].id),
                    ),
                  ),
          ),
        ]),
      ),
    );
  }
}

/// Botón de guardado con estado de envío.
class BotonGuardar extends StatelessWidget {
  final bool enviando;
  final String texto;
  final VoidCallback onPressed;
  const BotonGuardar({super.key, required this.enviando, required this.texto, required this.onPressed});

  @override
  Widget build(BuildContext context) => FilledButton(
        onPressed: enviando ? null : onPressed,
        child: enviando
            ? const Row(mainAxisSize: MainAxisSize.min, children: [
                SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white)),
                SizedBox(width: 12),
                Text('Guardando…'),
              ])
            : Text(texto),
      );
}

int numFotos(Map<String, dynamic> r) => asInt(r['num_fotos']) ?? 0;
