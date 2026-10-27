import 'package:buscontrol/core/version.dart';
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
}
