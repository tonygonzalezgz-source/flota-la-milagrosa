import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Colores de la marca BusControl (los del login web: azul noche + cian).
class Marca {
  static const fondoArriba = Color(0xFF020C18);
  static const fondoAbajo = Color(0xFF04213A);
  static const cian = Color(0xFF22D3EE);
  static const azul = Color(0xFF3B82F6);
  static const texto = Color(0xFFC8F0FF);
}

/// Fondo azul noche con destellos que se desplazan lentamente.
class FondoAnimado extends StatefulWidget {
  final Widget child;
  const FondoAnimado({super.key, required this.child});

  @override
  State<FondoAnimado> createState() => _FondoAnimadoState();
}

class _FondoAnimadoState extends State<FondoAnimado>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 14),
  )..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      CustomPaint(painter: _Destellos(_c), child: widget.child);
}

class _Destellos extends CustomPainter {
  final Animation<double> t;
  _Destellos(this.t) : super(repaint: t);

  // (x, y, radio relativo, color, fase)
  static const _orbes = [
    (0.15, 0.20, 0.55, Marca.azul, 0.0),
    (0.85, 0.35, 0.45, Marca.cian, 0.33),
    (0.40, 0.90, 0.60, Marca.azul, 0.66),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Marca.fondoArriba, Marca.fondoAbajo],
        ).createShader(rect),
    );
    final lado = size.shortestSide;
    for (final (x, y, r, color, fase) in _orbes) {
      final a = (t.value + fase) * 2 * math.pi;
      final centro = Offset(
        size.width * x + math.cos(a) * lado * .08,
        size.height * y + math.sin(a) * lado * .06,
      );
      final radio = lado * r;
      canvas.drawCircle(
        centro,
        radio,
        Paint()
          ..shader = RadialGradient(
            colors: [color.withValues(alpha: .22), color.withValues(alpha: 0)],
          ).createShader(Rect.fromCircle(center: centro, radius: radio)),
      );
    }
  }

  @override
  bool shouldRepaint(_Destellos old) => false;
}

const logoBusControlAsset = 'assets/logo-buscontrol.png';

/// Logo de BusControl sobre una insignia blanca con halo cian.
/// [brillo] (0–1) intensifica el halo; se usa para el pulso de la intro.
class LogoBusControl extends StatelessWidget {
  final double tamano;
  final double brillo;
  const LogoBusControl({super.key, this.tamano = 120, this.brillo = .5});

  @override
  Widget build(BuildContext context) => Container(
    width: tamano,
    height: tamano,
    padding: EdgeInsets.all(tamano * .14),
    decoration: BoxDecoration(
      color: Colors.white,
      shape: BoxShape.circle,
      boxShadow: [
        BoxShadow(
          color: Marca.cian.withValues(alpha: .25 + .35 * brillo),
          blurRadius: 18 + 30 * brillo,
          spreadRadius: 2 + 6 * brillo,
        ),
      ],
    ),
    child: Image.asset(logoBusControlAsset, fit: BoxFit.contain),
  );
}

/// Nombre "BusControl" con el mismo estilo del login web.
class NombreBusControl extends StatelessWidget {
  final double tamano;
  const NombreBusControl({super.key, this.tamano = 32});

  // Material transparente: durante el Hero el texto viaja fuera del Scaffold
  // y sin él Flutter lo pinta con el subrayado amarillo de "falta Material".
  @override
  Widget build(BuildContext context) => Material(
    type: MaterialType.transparency,
    child: Text(
      'BusControl',
      textAlign: TextAlign.center,
      style: TextStyle(
        color: Colors.white,
        fontSize: tamano,
        fontWeight: FontWeight.w800,
        letterSpacing: -.3,
        shadows: [
          Shadow(color: Marca.cian.withValues(alpha: .45), blurRadius: 24),
        ],
      ),
    ),
  );
}

class SubtituloBusControl extends StatelessWidget {
  const SubtituloBusControl({super.key});

  @override
  Widget build(BuildContext context) => const Material(
    type: MaterialType.transparency,
    child: Text(
      'Flota La Milagrosa',
      textAlign: TextAlign.center,
      style: TextStyle(color: Marca.texto, fontSize: 15, letterSpacing: .5),
    ),
  );
}
