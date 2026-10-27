import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../widgets/marca.dart';

/// true cuando terminó la animación de apertura. El router no sale de
/// /splash hasta que la intro termine y la sesión esté cargada.
final introTerminadaProvider = NotifierProvider<IntroTerminada, bool>(IntroTerminada.new);

class IntroTerminada extends Notifier<bool> {
  @override
  bool build() => false;
  void terminar() => state = true;
}

/// Pantalla de apertura: el logo entra con rebote, el halo late y aparece
/// el nombre. Dura ~1,8 s y en paralelo se restaura la sesión guardada.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1800));

  late final _escala = CurvedAnimation(parent: _c, curve: const Interval(0, .55, curve: Curves.elasticOut));
  late final _aparece = CurvedAnimation(parent: _c, curve: const Interval(0, .25, curve: Curves.easeOut));
  late final _halo = CurvedAnimation(parent: _c, curve: const Interval(.3, .8, curve: Curves.easeInOut));
  late final _nombre = CurvedAnimation(parent: _c, curve: const Interval(.45, .8, curve: Curves.easeOutCubic));
  late final _sub = CurvedAnimation(parent: _c, curve: const Interval(.6, .95, curve: Curves.easeOut));

  bool _iniciada = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_iniciada) return;
    _iniciada = true;
    // Se espera a que el logo esté decodificado: si no, el primer instante
    // se ve la insignia blanca vacía.
    precacheImage(const AssetImage(logoBusControlAsset), context).whenComplete(() {
      if (!mounted) return;
      _c.forward().whenComplete(() {
        if (mounted) ref.read(introTerminadaProvider.notifier).terminar();
      });
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: FondoAnimado(
        child: Center(
          child: AnimatedBuilder(
            animation: _c,
            builder: (_, _) {
              // El halo sube y baja una vez (latido) mientras entra el nombre.
              final pulso = _halo.value < .5 ? _halo.value * 2 : (1 - _halo.value) * 2;
              return Column(mainAxisSize: MainAxisSize.min, children: [
                Opacity(
                  opacity: _aparece.value,
                  child: Transform.scale(
                    scale: .4 + .6 * _escala.value,
                    child: Hero(
                      tag: 'logo-buscontrol',
                      child: LogoBusControl(tamano: 132, brillo: .3 + .7 * pulso),
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                Opacity(
                  opacity: _nombre.value,
                  child: Transform.translate(
                    offset: Offset(0, 24 * (1 - _nombre.value)),
                    child: const Hero(tag: 'nombre-buscontrol', child: NombreBusControl()),
                  ),
                ),
                const SizedBox(height: 6),
                Opacity(
                  opacity: _sub.value,
                  child: const Hero(tag: 'sub-buscontrol', child: SubtituloBusControl()),
                ),
              ]);
            },
          ),
        ),
      ),
    );
  }
}
