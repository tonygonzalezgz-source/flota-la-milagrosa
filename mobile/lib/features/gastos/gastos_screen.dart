import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../widgets/comunes.dart';
import '../../widgets/fotos.dart';
import '../../widgets/registros.dart';

/// GASTO_CATEGORIAS en api/app.py.
const categoriasGasto = [
  'Cambio de aceite', 'Frenos', 'Llantas', 'Motor', 'Suspensión',
  'Eléctrico', 'Combustible', 'Repuestos', 'Lavado', 'Otro',
];

/// Gastos y facturas de mantenimiento (Administrador y Propietario).
class GastosScreen extends ConsumerStatefulWidget {
  const GastosScreen({super.key});

  @override
  ConsumerState<GastosScreen> createState() => _GastosScreenState();
}

class _GastosScreenState extends ConsumerState<GastosScreen> {
  final _historial = GlobalKey<HistorialRegistrosState>();

  @override
  Widget build(BuildContext context) {
    final api = ref.read(apiClientProvider);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Gastos y Facturas'),
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white60,
            indicatorColor: Colors.white,
            tabs: [Tab(text: 'Registrar'), Tab(text: 'Historial')],
          ),
        ),
        body: TabBarView(children: [
          _FormGasto(onGuardado: () => _historial.currentState?.recargar()),
          HistorialRegistros(
            key: _historial,
            cargar: (desde, hasta) async =>
                asLista(await api.get('/gastos', query: {'desde': desde, 'hasta': hasta})),
            encabezado: (regs) {
              final total = regs.fold<double>(0, (s, g) => s + (asDouble(g['monto']) ?? 0));
              return Indicador('Total (${regs.length} gastos)', pesos(total), AppColors.primary,
                  icono: Icons.payments_outlined);
            },
            fila: (g) => FilaRegistro(
              titulo: pesos(asDouble(g['monto'])),
              subtitulo: [
                'Bus ${g['numero']}',
                Fechas.corta(g['fecha']),
                if (asStr(g['taller']).isNotEmpty) asStr(g['taller']),
              ].join(' · '),
              descripcion: asStr(g['descripcion']),
              etiqueta: Etiqueta(asStr(g['categoria']), AppColors.blue),
              numFotos: asBool(g['tiene_comprobante']) ? 1 : 0,
            ),
            fotos: (g) async {
              final d = await api.get('/gastos/${g['id']}/comprobante') as Map<String, dynamic>;
              if (asStr(d['comprobante_mime']).contains('pdf')) {
                throw Exception('El comprobante es un PDF: ábrelo desde la versión web.');
              }
              return [if (d['comprobante_base64'] != null) d['comprobante_base64'] as String];
            },
            borrar: (g) => api.delete('/gastos/${g['id']}'),
          ),
        ]),
      ),
    );
  }
}

class _FormGasto extends ConsumerStatefulWidget {
  final VoidCallback onGuardado;
  const _FormGasto({required this.onGuardado});

  @override
  ConsumerState<_FormGasto> createState() => _FormGastoState();
}

class _FormGastoState extends ConsumerState<_FormGasto> with AutomaticKeepAliveClientMixin {
  List<Bus>? _buses;
  String? _errorBuses;
  int? _busId;
  String _fecha = Fechas.hoy();
  String? _categoria;
  final _monto = TextEditingController();
  final _taller = TextEditingController();
  final _desc = TextEditingController();
  String? _comprobante;
  bool _enviando = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _cargarBuses();
  }

  @override
  void dispose() {
    _monto.dispose();
    _taller.dispose();
    _desc.dispose();
    super.dispose();
  }

  Future<void> _cargarBuses() async {
    final user = ref.read(sessionProvider).value;
    try {
      // Con user_id el backend limita la lista a los buses del propietario.
      final l = asLista(await ref.read(apiClientProvider).get('/buses', query: {'user_id': user?.id}));
      _buses = l.map(Bus.fromJson).toList();
      if (_buses!.length == 1) _busId = _buses!.first.id;
      _errorBuses = null;
    } catch (e) {
      _errorBuses = e.toString();
    }
    if (mounted) setState(() {});
  }

  Future<void> _foto(ImageSource src) async {
    final f = await tomarFoto(context, src);
    if (f != null) setState(() => _comprobante = f);
  }

  Future<void> _guardar() async {
    final monto = double.tryParse(_monto.text.replaceAll('.', '').trim());
    if (_busId == null || _categoria == null || monto == null) {
      mostrarMensaje(context, 'Completa los campos obligatorios', error: true);
      return;
    }
    setState(() => _enviando = true);
    try {
      await ref.read(apiClientProvider).post('/gastos', body: {
        'bus_id': _busId,
        'fecha': _fecha,
        'categoria': _categoria,
        'descripcion': _desc.text.trim(),
        'taller': _taller.text.trim(),
        'monto': monto,
        'comprobante_base64': _comprobante,
        'comprobante_mime': _comprobante == null ? null : 'image/jpeg',
        'comprobante_nombre': _comprobante == null ? null : 'comprobante_$_fecha.jpg',
      });
      if (!mounted) return;
      mostrarMensaje(context, 'Gasto registrado correctamente');
      setState(() {
        _categoria = null;
        _monto.clear();
        _taller.clear();
        _desc.clear();
        _comprobante = null;
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
    return CargaView(
      cargando: _buses == null && _errorBuses == null,
      error: _errorBuses,
      onReintentar: _cargarBuses,
      builder: () => ListView(padding: const EdgeInsets.all(16), children: [
        if (_buses!.isEmpty)
          const VacioView('No tienes vehículos asignados.')
        else
          CampoBus(buses: _buses!, valor: _busId, onChanged: (v) => setState(() => _busId = v)),
        const SizedBox(height: 12),
        CampoFecha(valor: _fecha, onChanged: (v) => setState(() => _fecha = v)),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _categoria,
          isExpanded: true,
          decoration: const InputDecoration(labelText: 'Categoría'),
          items: [for (final c in categoriasGasto) DropdownMenuItem(value: c, child: Text(c))],
          onChanged: (v) => setState(() => _categoria = v),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _monto,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(labelText: 'Monto (COP)', prefixText: '\$ '),
        ),
        const SizedBox(height: 12),
        TextField(controller: _taller, decoration: const InputDecoration(labelText: 'Taller / proveedor (opcional)')),
        const SizedBox(height: 12),
        TextField(
          controller: _desc,
          minLines: 2,
          maxLines: 5,
          decoration: const InputDecoration(labelText: 'Descripción (opcional)', alignLabelWithHint: true),
        ),
        const SizedBox(height: 16),
        const Text('Comprobante / factura', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        if (_comprobante == null)
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _foto(ImageSource.camera),
                icon: const Icon(Icons.photo_camera_outlined),
                label: const Text('Foto'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _foto(ImageSource.gallery),
                icon: const Icon(Icons.photo_library_outlined),
                label: const Text('Galería'),
              ),
            ),
          ])
        else
          Stack(children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.memory(deDataUrl(_comprobante)!, height: 180, width: double.infinity, fit: BoxFit.cover),
            ),
            Positioned(
              right: 6,
              top: 6,
              child: IconButton.filled(
                style: IconButton.styleFrom(backgroundColor: Colors.black54),
                icon: const Icon(Icons.close),
                onPressed: () => setState(() => _comprobante = null),
              ),
            ),
          ]),
        const SizedBox(height: 20),
        BotonGuardar(enviando: _enviando, texto: 'Guardar gasto', onPressed: _guardar),
      ]),
    );
  }
}
