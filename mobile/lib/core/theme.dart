import 'package:flutter/material.dart';

/// Paleta "Aurora Clara" (propuesta C elegida para la app): azul noche en
/// cabeceras, fondo gris azulado claro, tarjetas blancas y azul eléctrico.
/// El login usa la propuesta A (ver widgets/marca.dart).
class AppColors {
  static const primary = Color(0xFF2F5BFF);
  static const primaryDark = Color(0xFF1D3FD1);
  static const primarySoft = Color(0xFFE8EDFF);
  static const navy = Color(0xFF0B1530);
  static const texto = Color(0xFF0F1A33);
  static const green = Color(0xFF16A34A);
  static const dinero = Color(0xFF0E7A50);
  static const yellow = Color(0xFFF59E0B);
  static const red = Color(0xFFDC2626);
  static const blue = Color(0xFF0E8F83);
  static const muted = Color(0xFF5B6785);
  static const bgLight = Color(0xFFEEF2F8);
  static const campo = Color(0xFFF2F5FB);

  /// Compatibilidad con pantallas anteriores.
  static const dark = navy;
}

/// Tipografías incluidas en assets/fonts.
class Fuentes {
  static const titulo = 'Sora';
  static const texto = 'DMSans';
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    primary: AppColors.primary,
    surface: Colors.white,
    onSurface: AppColors.texto,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, fontFamily: Fuentes.texto);
  TextStyle? sora(TextStyle? s) => s?.copyWith(fontFamily: Fuentes.titulo, fontWeight: FontWeight.w700);
  const pill = StadiumBorder();

  return base.copyWith(
    scaffoldBackgroundColor: AppColors.bgLight,
    textTheme: base.textTheme.copyWith(
      headlineSmall: sora(base.textTheme.headlineSmall),
      titleLarge: sora(base.textTheme.titleLarge),
      titleMedium: base.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.navy,
      foregroundColor: Colors.white,
      centerTitle: false,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(
        fontFamily: Fuentes.titulo,
        fontWeight: FontWeight.w700,
        fontSize: 20,
        color: Colors.white,
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 2,
      shadowColor: const Color(0x260F1A33),
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.campo,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: AppColors.primary, width: 1.5),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(54),
        shape: pill,
        elevation: 0,
        textStyle: const TextStyle(fontFamily: Fuentes.titulo, fontSize: 16, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        shape: pill,
        minimumSize: const Size(0, 48),
        side: const BorderSide(color: AppColors.primary, width: 1.3),
        textStyle: const TextStyle(fontWeight: FontWeight.w700),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        shape: const WidgetStatePropertyAll(pill),
        side: const WidgetStatePropertyAll(BorderSide(color: Color(0xFFD5DCEB))),
        backgroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? AppColors.primary : Colors.white,
        ),
        foregroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? Colors.white : AppColors.muted,
        ),
        textStyle: const WidgetStatePropertyAll(TextStyle(fontWeight: FontWeight.w700)),
      ),
    ),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(
      backgroundColor: AppColors.primary,
      foregroundColor: Colors.white,
    ),
    snackBarTheme: SnackBarThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
  );
}
