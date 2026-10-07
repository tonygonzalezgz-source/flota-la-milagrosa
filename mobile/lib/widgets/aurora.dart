import 'package:flutter/material.dart';

import '../core/theme.dart';

/// Piezas del estilo "Aurora Clara" (propuesta C): cabecera azul noche con
/// esquinas inferiores redondeadas y tarjetas blancas que flotan sobre ella.

const sombraSuave = [BoxShadow(color: Color(0x0F0F1A33), blurRadius: 18, offset: Offset(0, 6))];
const sombraFuerte = [BoxShadow(color: Color(0x1F0F1A33), blurRadius: 40, offset: Offset(0, 16))];

/// Cabecera azul noche. [traslape] es el espacio inferior que queda debajo
/// del contenido para que la primera tarjeta se monte encima.
class CabeceraAurora extends StatelessWidget {
  final Widget child;
  final double traslape;
  const CabeceraAurora({super.key, required this.child, this.traslape = 96});

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.fromLTRB(20, MediaQuery.paddingOf(context).top + 16, 20, traslape),
        decoration: const BoxDecoration(
          color: AppColors.navy,
          borderRadius: BorderRadius.vertical(bottom: Radius.circular(36)),
        ),
        child: child,
      );
}

/// Tarjeta blanca redondeada con sombra suave.
class TarjetaAurora extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final double radio;
  final Color color;
  final List<BoxShadow> sombra;
  final VoidCallback? onTap;
  final BoxBorder? borde;

  const TarjetaAurora({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.radio = 22,
    this.color = Colors.white,
    this.sombra = sombraSuave,
    this.onTap,
    this.borde,
  });

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radio);
    return DecoratedBox(
      decoration: BoxDecoration(color: color, borderRadius: r, boxShadow: sombra, border: borde),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: r,
          onTap: onTap,
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}

/// Botón circular translúcido para la cabecera (volver, salir, flechas).
class BotonCabecera extends StatelessWidget {
  final IconData icono;
  final String tooltip;
  final VoidCallback? onPressed;
  final bool tenue;
  const BotonCabecera({
    super.key,
    required this.icono,
    required this.tooltip,
    required this.onPressed,
    this.tenue = false,
  });

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: tooltip,
        onPressed: onPressed,
        style: IconButton.styleFrom(
          fixedSize: const Size(44, 44),
          backgroundColor: Colors.white.withValues(alpha: tenue ? .05 : .12),
          foregroundColor: Colors.white,
          disabledForegroundColor: const Color(0xFF4A5A85),
          disabledBackgroundColor: Colors.white.withValues(alpha: .05),
        ),
        icon: Icon(icono, size: 22),
      );
}

/// Cuadro de icono con fondo tenue (indicadores y datos).
class IconoSuave extends StatelessWidget {
  final IconData icono;
  final Color color;
  final Color fondo;
  final double tamano;
  const IconoSuave(this.icono, {super.key, required this.color, required this.fondo, this.tamano = 36});

  @override
  Widget build(BuildContext context) => Container(
        width: tamano,
        height: tamano,
        decoration: BoxDecoration(color: fondo, borderRadius: BorderRadius.circular(tamano * .32)),
        child: Icon(icono, color: color, size: tamano * .52),
      );
}

/// Variación frente a la semana pasada: ▲ verde / ▼ rojo; nada si no hay base.
class Variacion extends StatelessWidget {
  final double? cambio;
  final bool pastilla;
  const Variacion(this.cambio, {super.key, this.pastilla = false});

  @override
  Widget build(BuildContext context) {
    final c = cambio;
    if (c == null) {
      return Text('sin base', style: TextStyle(fontSize: 12, color: AppColors.muted.withValues(alpha: .8)));
    }
    final sube = c >= 0;
    final color = sube ? AppColors.dinero : const Color(0xFFC0262D);
    final texto = '${sube ? '▲' : '▼'} ${c.abs().toStringAsFixed(0)}%';
    if (!pastilla) {
      return Text(texto, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color));
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: sube ? const Color(0xFFE3F5EC) : const Color(0xFFFDECEC),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(texto, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color)),
    );
  }
}

/// Aviso de color (documentos por vencer, novedades).
class AvisoAurora extends StatelessWidget {
  final IconData icono;
  final Widget texto;
  final bool critico;
  const AvisoAurora({super.key, required this.icono, required this.texto, this.critico = false});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: critico ? const Color(0xFFFDECEC) : const Color(0xFFFFF4E0),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(children: [
          Icon(icono, color: critico ? const Color(0xFFC0262D) : const Color(0xFFB36B00), size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: DefaultTextStyle.merge(
              style: TextStyle(fontSize: 13, color: critico ? const Color(0xFF7A1A1F) : const Color(0xFF5C3A00)),
              child: texto,
            ),
          ),
        ]),
      );
}

/// Pesos abreviados para listas: $ 7,47 M · $ 850.000.
String pesosCortos(num v) {
  if (v.abs() >= 1000000) {
    return '\$ ${(v / 1000000).toStringAsFixed(2).replaceAll('.', ',')} M';
  }
  final s = v.round().toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write('.');
    b.write(s[i]);
  }
  return '\$ $b';
}

const estiloTituloAurora = TextStyle(fontFamily: Fuentes.titulo, fontSize: 16, fontWeight: FontWeight.w700, color: AppColors.texto);
