import 'package:buscontrol/core/config.dart';
import 'package:buscontrol/core/version.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('versión mínima de la app', () {
    test('pide actualizar solo si la mínima es mayor que la instalada', () {
      expect(requiereActualizar(40, 41), isTrue);
      expect(requiereActualizar(41, 41), isFalse);
      expect(requiereActualizar(42, 41), isFalse);
    });
    test('sin mínima o con un valor raro no bloquea', () {
      expect(requiereActualizar(40, null), isFalse);
      expect(requiereActualizar(40, 0), isFalse);
      expect(requiereActualizar(40, 'abc'), isFalse);
      expect(requiereActualizar(40, '50'), isTrue);
    });
    test('una compilación de desarrollo (0) nunca se bloquea', () {
      expect(requiereActualizar(0, 99), isFalse);
    });
  });

  group('tienda según la plataforma', () {
    tearDown(() => debugDefaultTargetPlatformOverride = null);

    test('en Android habla de la Play Store y lleva a su ficha', () {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      expect(AppConfig.plataforma, 'android');
      expect(AppConfig.nombreTienda, 'Play Store');
      expect(AppConfig.urlTienda, contains('play.google.com'));
    });

    test('en iPhone habla de la App Store y no nombra la Play Store', () {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      expect(AppConfig.plataforma, 'ios');
      expect(AppConfig.nombreTienda, 'App Store');
      // Sin APP_STORE_ID (compilación normal) no hay enlace a la tienda, y
      // nunca manda a la Play Store: Apple lo rechaza.
      expect(AppConfig.urlTienda, isNot(contains('play.google.com')));
    });
  });
}
