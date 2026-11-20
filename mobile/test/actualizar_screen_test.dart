import 'package:buscontrol/features/auth/actualizar_screen.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// El aviso de "actualiza la app" no puede nombrar la Play Store en iPhone:
/// Apple rechaza las apps que mencionan o enlazan otras tiendas.
void main() {
  bool hayTextoCon(String aguja) => find
      .byWidgetPredicate((w) => w is Text && (w.data ?? '').contains(aguja))
      .evaluate()
      .isNotEmpty;

  /// Dibuja la pantalla como si el celular fuera [plataforma] y devuelve qué
  /// tienda nombra y si muestra el botón. El override se quita antes de
  /// terminar la prueba, como exige flutter_test.
  Future<({bool play, bool apple, bool boton})> dibujar(
    WidgetTester tester,
    TargetPlatform plataforma,
  ) async {
    debugDefaultTargetPlatformOverride = plataforma;
    await tester.pumpWidget(const MaterialApp(home: ActualizarScreen()));
    await tester.pump(const Duration(milliseconds: 100));
    final r = (
      play: hayTextoCon('Play Store'),
      apple: hayTextoCon('App Store'),
      boton: find.text('ACTUALIZAR').evaluate().isNotEmpty,
    );
    debugDefaultTargetPlatformOverride = null;
    return r;
  }

  testWidgets('en Android manda a la Play Store', (tester) async {
    final r = await dibujar(tester, TargetPlatform.android);
    expect(r.play, isTrue);
    expect(r.boton, isTrue);
  });

  testWidgets('en iPhone habla de la App Store y no nombra la Play Store', (tester) async {
    final r = await dibujar(tester, TargetPlatform.iOS);
    expect(r.apple, isTrue);
    expect(r.play, isFalse);
    // Sin APP_STORE_ID todavía no hay ficha a la que mandar al usuario.
    expect(r.boton, isFalse);
  });
}
