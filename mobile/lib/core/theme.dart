import 'package:flutter/material.dart';

/// Colores de la plataforma web (variables CSS de index.html).
class AppColors {
  static const primary = Color(0xFF6366F1);
  static const green = Color(0xFF22C55E);
  static const yellow = Color(0xFFF59E0B);
  static const red = Color(0xFFEF4444);
  static const blue = Color(0xFF3B82F6);
  static const dark = Color(0xFF0A0A0C);
  static const card = Color(0xFF141416);
  static const muted = Color(0xFF808080);
  static const bgLight = Color(0xFFF4F4F6);
}

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    primary: AppColors.primary,
    surface: Colors.white,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.bgLight,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.dark,
      foregroundColor: Colors.white,
      centerTitle: false,
      elevation: 0,
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE5E5EA)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(50),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
  );
}
