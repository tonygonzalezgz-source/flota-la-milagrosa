import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../../widgets/comunes.dart';

/// Aviso de tratamiento de datos personales (Ley 1581 de 2012). Mismo texto
/// que el modal de index.html; la aceptación queda registrada en el servidor.
class TratamientoScreen extends ConsumerStatefulWidget {
  const TratamientoScreen({super.key});

  @override
  ConsumerState<TratamientoScreen> createState() => _TratamientoScreenState();
}

class _TratamientoScreenState extends ConsumerState<TratamientoScreen> {
  bool _acepto = false;
  bool _enviando = false;

  Future<void> _aceptar() async {
    setState(() => _enviando = true);
    try {
      await ref.read(sessionProvider.notifier).aceptarTratamiento();
    } catch (e) {
      if (mounted) mostrarMensaje(context, e.toString(), error: true);
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    const h = TextStyle(fontWeight: FontWeight.w700, fontSize: 15);
    Widget item(String t) => Padding(
          padding: const EdgeInsets.only(left: 8, bottom: 4),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('•  '),
            Expanded(child: Text(t)),
          ]),
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Tratamiento de datos')),
      body: SafeArea(
        child: Column(children: [
          Expanded(
            child: ListView(padding: const EdgeInsets.all(20), children: [
              const Text('Aviso de tratamiento de datos personales',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              const Text('Ley 1581 de 2012 · Habeas Data'),
              const SizedBox(height: 14),
              const Text(
                  'En cumplimiento de la Ley Estatutaria 1581 de 2012 y el Decreto 1377 de 2013 '
                  'de la República de Colombia, Flota La Milagrosa, responsable del tratamiento, '
                  'le informa que los datos personales que suministra a la plataforma BusControl '
                  'serán tratados con las finalidades, alcances y garantías que se describen a continuación.'),
              const SizedBox(height: 14),
              const Text('Datos que se recolectan', style: h),
              item('Datos de identificación (nombre, cédula, teléfono, correo).'),
              item('Información de sus vehículos (placa, número, kilometraje, vencimientos de SOAT, '
                  'tecnomecánica y tarjeta de operación).'),
              item('Registros operativos asociados a sus buses (despacho, movilidad, mantenimiento, '
                  'alistamiento, gastos).'),
              const SizedBox(height: 10),
              const Text('Finalidades del tratamiento', style: h),
              item('Gestión operativa y administrativa de su flota dentro de la plataforma.'),
              item('Emisión de reportes de operación, movilidad, gastos y estado de vehículos.'),
              item('Comunicaciones sobre novedades operativas de sus buses.'),
              item('Cumplimiento de obligaciones contractuales, legales y regulatorias.'),
              const SizedBox(height: 10),
              const Text('Sus derechos como titular', style: h),
              item('Conocer, actualizar y rectificar sus datos personales.'),
              item('Solicitar prueba de esta autorización.'),
              item('Ser informado sobre el uso dado a sus datos.'),
              item('Presentar quejas ante la Superintendencia de Industria y Comercio (SIC).'),
              item('Revocar la autorización y/o solicitar la supresión del dato, cuando no exista '
                  'un deber legal o contractual que lo impida.'),
              const SizedBox(height: 10),
              const Text('Canales de atención', style: h),
              const Text(
                  'Para consultas, reclamos o para ejercer sus derechos como titular, puede contactarnos '
                  'a través de los canales oficiales de Flota La Milagrosa. Su solicitud será atendida '
                  'en los términos de la Ley 1581 de 2012.'),
              const SizedBox(height: 14),
              const Text(
                  'Al aceptar, usted declara que ha leído y comprendido este aviso y autoriza expresamente '
                  'a Flota La Milagrosa para el tratamiento de sus datos personales conforme a lo aquí '
                  'descrito. Su autorización queda registrada con fecha y hora en el sistema.',
                  style: TextStyle(fontStyle: FontStyle.italic)),
            ]),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: [
              CheckboxListTile(
                value: _acepto,
                onChanged: (v) => setState(() => _acepto = v ?? false),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: const Text(
                    'He leído y acepto el aviso de tratamiento de datos personales y autorizo el '
                    'tratamiento de mi información conforme a lo aquí descrito.',
                    style: TextStyle(fontSize: 13)),
              ),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(
                  flex: 2,
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
                    onPressed: _enviando
                        ? null
                        : () => ref.read(sessionProvider.notifier).logout(),
                    child: const Text('No acepto'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  flex: 3,
                  child: FilledButton(
                    onPressed: _acepto && !_enviando ? _aceptar : null,
                    child: const Text('Acepto y continúo'),
                  ),
                ),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }
}
