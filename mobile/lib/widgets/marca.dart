import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Estilo "Cabina Neón" (propuesta A elegida para el login y la apertura):
/// azul casi negro con cuadrícula, cian y violeta luminosos.
class Marca {
  static const fondo = Color(0xFF050B18);
  static const cian = Color(0xFF22D3EE);
  static const violeta = Color(0xFFA78BFA);
  static const texto = Color(0xFFE6F6FF);
  static const apagado = Color(0xFF8FA7BD);
  static const verde = Color(0xFF34D399);
  static const sobreCian = Color(0xFF04121F);

  static const display = 'ChakraPetch';
  static const cuerpo = 'Manrope';
}

/// Fondo de cuadrícula con dos resplandores que se desplazan lentamente.
class FondoAnimado extends StatefulWidget {
  final Widget child;
  const FondoAnimado({super.key, required this.child});

  @override
  State<FondoAnimado> createState() => _FondoAnimadoState();
}

class _FondoAnimadoState extends State<FondoAnimado> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(seconds: 16))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CustomPaint(painter: _Cuadricula(_c), child: widget.child);
}

class _Cuadricula extends CustomPainter {
  final Animation<double> t;
  _Cuadricula(this.t) : super(repaint: t);

  static const _paso = 32.0;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = Marca.fondo);

    // Resplandores: cian arriba a la derecha, violeta abajo a la izquierda.
    final lado = size.shortestSide;
    final a = t.value * 2 * math.pi;
    for (final (x, y, color, fase) in const [
      (0.8, 0.22, Marca.cian, 0.0),
      (0.2, 0.82, Marca.violeta, math.pi),
    ]) {
      final centro = Offset(
        size.width * x + math.cos(a + fase) * lado * .07,
        size.height * y + math.sin(a + fase) * lado * .05,
      );
      final radio = lado * .7;
      canvas.drawCircle(
        centro,
        radio,
        Paint()
          ..shader = RadialGradient(
            colors: [color.withValues(alpha: .16), color.withValues(alpha: 0)],
          ).createShader(Rect.fromCircle(center: centro, radius: radio)),
      );
    }

    final linea = Paint()
      ..color = Marca.cian.withValues(alpha: .05)
      ..strokeWidth = 1;
    for (var x = 0.0; x <= size.width; x += _paso) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), linea);
    }
    for (var y = 0.0; y <= size.height; y += _paso) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), linea);
    }
  }

  @override
  bool shouldRepaint(_Cuadricula old) => false;
}

const logoBusControlAsset = 'assets/logo-buscontrol.png';

/// Logo de BusControl en un círculo blanco con anillo cian-violeta luminoso.
/// [brillo] (0–1) intensifica el resplandor; se usa para el pulso de la intro.
class LogoBusControl extends StatelessWidget {
  final double tamano;
  final double brillo;
  const LogoBusControl({super.key, this.tamano = 120, this.brillo = .5});

  @override
  Widget build(BuildContext context) => Container(
        width: tamano,
        height: tamano,
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: const SweepGradient(
            startAngle: 0,
            endAngle: 2 * math.pi,
            colors: [Marca.cian, Marca.violeta, Marca.cian],
          ),
          boxShadow: [
            BoxShadow(
              color: Marca.cian.withValues(alpha: .25 + .35 * brillo),
              blurRadius: 20 + 30 * brillo,
              spreadRadius: 1 + 5 * brillo,
            ),
          ],
        ),
        child: Container(
          padding: EdgeInsets.all(tamano * .15),
          decoration: const BoxDecoration(color: Colors.white, shape: BoxShape.circle),
          child: Image.asset(logoBusControlAsset, fit: BoxFit.contain),
        ),
      );
}

/// "BUSCONTROL" en Chakra Petch con resplandor cian.
class NombreBusControl extends StatelessWidget {
  final double tamano;
  const NombreBusControl({super.key, this.tamano = 34});

  // Material transparente: durante el Hero el texto viaja fuera del Scaffold
  // y sin él Flutter lo pinta con el subrayado amarillo de "falta Material".
  @override
  Widget build(BuildContext context) => Material(
        type: MaterialType.transparency,
        child: Text(
          'BUSCONTROL',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: Marca.display,
            color: Colors.white,
            fontSize: tamano,
            fontWeight: FontWeight.w700,
            letterSpacing: 2,
            shadows: [Shadow(color: Marca.cian.withValues(alpha: .55), blurRadius: 22)],
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
          'FLOTA LA MILAGROSA',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontFamily: Marca.cuerpo,
            color: Marca.cian,
            fontSize: 12,
            fontWeight: FontWeight.w600,
            letterSpacing: 4,
          ),
        ),
      );
}
