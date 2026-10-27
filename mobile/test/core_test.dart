import 'dart:typed_data';

import 'package:buscontrol/core/fechas.dart';
import 'package:buscontrol/core/modelos.dart';
import 'package:buscontrol/core/modulos.dart';
import 'package:buscontrol/core/session.dart';
import 'package:buscontrol/features/alistamiento/alistamiento_form.dart';
import 'package:buscontrol/features/despacho/despacho_screen.dart';
import 'package:buscontrol/widgets/fotos.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Fechas', () {
    test('normaliza ISO y RFC 2822 (Postgres)', () {
      expect(Fechas.normalizar('2025-08-15'), '2025-08-15');
      expect(Fechas.normalizar('2025-08-15T00:00:00'), '2025-08-15');
      expect(Fechas.normalizar('Fri, 15 Aug 2025 00:00:00 GMT'), '2025-08-15');
      expect(Fechas.normalizar(null), '');
      expect(Fechas.normalizar('basura'), '');
    });

    test('hoy está en formato YYYY-MM-DD', () {
      expect(RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(Fechas.hoy()), isTrue);
    });

    test('diasHasta cuenta desde hoy en Bogotá', () {
      expect(Fechas.diasHasta(Fechas.hoy()), 0);
      expect(Fechas.diasHasta(Fechas.haceDias(3)), -3);
      expect(Fechas.diasHasta(null), isNull);
    });
  });

  group('Modelos', () {
    test('conversiones tolerantes', () {
      expect(asInt('12'), 12);
      expect(asInt(3.0), 3);
      expect(asBool(1), isTrue);
      expect(asBool(0), isFalse);
      expect(asBool('true'), isTrue);
      expect(asDouble('2.5'), 2.5);
    });

    test('formato de pesos colombianos', () {
      expect(pesos(1234567), '\$ 1.234.567');
      expect(pesos(0), '\$ 0');
      expect(miles(12345), '12.345');
    });
  });

  group('Permisos por rol', () {
    test('el menú usa allowedViews del backend', () {
      final m = modulosDe(['despacho', 'chequeo', 'relojes']);
      expect(m.map((e) => e.clave), ['despacho', 'chequeo', 'relojes']);
      expect(m.where((e) => e.nativo).length, 2);
    });

    test('no deja abrir pantallas nativas fuera de su rol', () {
      expect(puedeAbrir(['eds'], '/eds'), isTrue);
      expect(puedeAbrir(['eds'], '/despacho'), isFalse);
      expect(puedeAbrir(['eds'], '/'), isTrue);
    });

    test('aviso de datos solo para propietarios sin aceptar', () {
      Usuario u(String rol, bool ok) => Usuario.fromJson({
            'id': 1, 'username': 'x', 'nombre': 'X', 'rol': rol, 'iniciales': 'X',
            'allowedViews': [], 'bus_ids': [], 'tratamiento_aceptado': ok,
          });
      expect(u('Propietario', false).debeAceptarTratamiento, isTrue);
      expect(u('Propietario', true).debeAceptarTratamiento, isFalse);
      expect(u('Despachador', false).debeAceptarTratamiento, isFalse);
    });
  });

  test('alistamiento tiene los 30 ítems oficiales', () {
    expect(itemsAlistamiento.length, 30);
    expect(itemsAlistamiento.map((e) => e.$1).toSet().length, 30);
    expect(parseNovedades('{"pito":"no suena"}'), {'pito': 'no suena'});
    expect(parseNovedades(null), isEmpty);
  });

  test('documentos vencidos bloquean el despacho', () {
    final d = docsBus({
      'soat_vencimiento': Fechas.haceDias(2),
      'tecno_vencimiento': Fechas.haceDias(-10),
      'tarjeta_op_vencimiento': null,
    });
    expect(d.vencidos.length, 1);
    expect(d.porVencer.length, 1);
  });

  test('data URL de fotos ida y vuelta', () {
    final bytes = deDataUrl(aDataUrl(Uint8List.fromList([1, 2, 3])));
    expect(bytes, [1, 2, 3]);
    expect(deDataUrl('no-es-base64!!'), isNull);
  });
}
