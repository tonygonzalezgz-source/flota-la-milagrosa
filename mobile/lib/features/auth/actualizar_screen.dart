import 'package:flutter/material.dart';

import '../../core/config.dart';
import '../../widgets/comunes.dart';
import '../../widgets/marca.dart';

/// Se muestra en lugar de la app cuando la versión instalada ya no es
/// compatible con el servidor: solo deja ir a la Play Store a actualizar.
class ActualizarScreen extends StatelessWidget {
  const ActualizarScreen({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        body: FondoAnimado(
          child: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 420),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    const Center(child: LogoBusControl(tamano: 110)),
                    const SizedBox(height: 28),
                    const Text(
                      'Actualiza BusControl',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontFamily: Marca.display,
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        color: Marca.texto,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'Hay una versión nueva de la app y esta ya no funciona con el servidor. '
                      'Actualízala desde la Play Store para seguir usándola.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontFamily: Marca.cuerpo, fontSize: 15, height: 1.5, color: Marca.apagado),
                    ),
                    const SizedBox(height: 28),
                    FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: Marca.cian,
                        foregroundColor: Marca.sobreCian,
                        minimumSize: const Size.fromHeight(58),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        textStyle: const TextStyle(
                            fontFamily: Marca.display, fontSize: 16, fontWeight: FontWeight.w700, letterSpacing: 3),
                      ),
                      onPressed: () => abrirEnlace(context, AppConfig.urlPlayStore),
                      child: const Text('ACTUALIZAR'),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
      );
}
