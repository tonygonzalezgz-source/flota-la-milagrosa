import 'dart:convert';

import 'package:buscontrol/core/api_client.dart';
import 'package:buscontrol/core/fechas.dart';
import 'package:buscontrol/core/session.dart';
import 'package:buscontrol/features/chat/chat_controller.dart';
import 'package:buscontrol/features/chat/texto_markdown.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

const _usuario = Usuario(
  id: 4,
  username: 'propietario',
  nombre: 'Carlos',
  rol: 'Propietario',
  iniciales: 'CN',
  allowedViews: ['propietario'],
  busIds: [1],
  tratamientoAceptado: true,
);

class _SesionFalsa extends SessionController {
  @override
  Future<Usuario?> build() async => _usuario;
}

/// Responde a `/chat` con los eventos dados (o con [falla]) y guarda lo enviado.
class _ApiFalsa extends ApiClient {
  final List<Map<String, dynamic>> eventos;
  final Object? falla;
  final enviados = <Object?>[];
  _ApiFalsa(this.eventos, {this.falla});

  @override
  Stream<Map<String, dynamic>> postEventos(String path, {Object? body}) async* {
    enviados.add(body);
    if (falla != null) throw falla!;
    for (final e in eventos) {
      yield e;
    }
  }
}

Future<ProviderContainer> _contenedor(_ApiFalsa api) async {
  final c = ProviderContainer(overrides: [
    apiClientProvider.overrideWithValue(api),
    sessionProvider.overrideWith(_SesionFalsa.new),
  ]);
  addTearDown(c.dispose);
  await c.read(sessionProvider.future);
  c.listen(chatProvider, (_, _) {});
  return c;
}

/// Deja que termine la carga del historial (lectura asíncrona del almacén).
Future<void> _esperar() async {
  for (var i = 0; i < 5; i++) {
    await Future<void>.delayed(Duration.zero);
  }
}

String _guardado({int usuario = 4, String? dia, int pares = 1}) => jsonEncode({
      'usuario': usuario,
      'dia': dia ?? Fechas.hoy(),
      'mensajes': [
        for (var i = 1; i <= pares; i++) ...[
          {'a': 'u', 't': 'pregunta $i'},
          {'a': 'b', 't': 'respuesta $i'},
        ],
      ],
    });

Future<String?> _leerAlmacen() => const FlutterSecureStorage().read(key: claveHistorialChat);

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('SSE: arma eventos aunque lleguen partidos entre trozos', () async {
    final trozos = Stream.fromIterable([
      'data: {"type":"tool","na',
      'me":"movilidad_bus"}\n\ndata: {"type":"text","text":"Hola"}\r\n\r\n',
      'data: no-es-json\n\n',
      'data: {"type":"done"}\n\n',
    ]);
    final eventos = await eventosSse(trozos).toList();
    expect(eventos.map((e) => e['type']), ['tool', 'text', 'done']);
    expect(eventos[1]['text'], 'Hola');
  });

  test('markdown en línea: negrita, cursiva y código', () {
    final spans = spansMarkdown('El **bus 5** está *bien* con `ruta 2`').cast<TextSpan>();
    expect(spans.map((s) => s.text), ['El ', 'bus 5', ' está ', 'bien', ' con ', 'ruta 2']);
    expect(spans.elementAt(1).style?.fontWeight, FontWeight.w700);
    expect(spans.elementAt(3).style?.fontStyle, FontStyle.italic);
  });

  testWidgets('markdown oculta un ** sin cerrar mientras llega la respuesta', (t) async {
    await t.pumpWidget(const MaterialApp(
      home: Scaffold(body: TextoMarkdown('- **Bus 1** subió\n- **Bus 2', estilo: TextStyle())),
    ));
    expect(find.textContaining('**'), findsNothing);
    expect(find.text('•'), findsNWidgets(2));
  });

  test('el chat va armando la respuesta y manda el historial', () async {
    final api = _ApiFalsa([
      {'type': 'tool', 'name': 'comparativa_movilidad_flota'},
      {'type': 'text', 'text': 'Esta semana '},
      {'type': 'text', 'text': 'subió **4%**.'},
      {'type': 'done'},
    ]);
    final c = await _contenedor(api);
    await c.read(chatProvider.notifier).enviar('  ¿cómo vamos?  ');

    final s = c.read(chatProvider);
    expect(s.respondiendo, isFalse);
    expect(s.consultando, isFalse);
    expect(s.mensajes.map((m) => m.autor), [Autor.usuario, Autor.asistente]);
    expect(s.mensajes.last.texto, 'Esta semana subió **4%**.');
    expect(api.enviados.single, {
      'messages': [
        {'role': 'user', 'content': '¿cómo vamos?'},
      ],
    });

    // La segunda pregunta lleva toda la conversación.
    await c.read(chatProvider.notifier).enviar('¿y el bus 1?');
    final segundo = (api.enviados.last as Map)['messages'] as List;
    expect(segundo.map((m) => m['role']), ['user', 'assistant', 'user']);
  });

  test('si el chatbot está apagado se avisa y no se manda el error al modelo', () async {
    final api = _ApiFalsa(const [], falla: ApiException('El chatbot no está habilitado.', 404));
    final c = await _contenedor(api);
    await c.read(chatProvider.notifier).enviar('hola');

    final s = c.read(chatProvider);
    expect(s.mensajes.last.autor, Autor.error);
    expect(s.mensajes.last.texto, 'El asistente no está habilitado en este momento.');
    expect(s.respondiendo, isFalse);
  });

  group('historial en el celular', () {
    test('guarda la conversación del día al terminar la respuesta', () async {
      final api = _ApiFalsa([
        {'type': 'text', 'text': 'Todo bien.'},
        {'type': 'done'},
      ]);
      final c = await _contenedor(api);
      await c.read(chatProvider.notifier).enviar('¿cómo vamos?');

      final j = jsonDecode((await _leerAlmacen())!) as Map<String, dynamic>;
      expect(j['usuario'], 4);
      expect(j['dia'], Fechas.hoy());
      expect(j['mensajes'], [
        {'a': 'u', 't': '¿cómo vamos?'},
        {'a': 'b', 't': 'Todo bien.'},
      ]);
    });

    test('al volver a abrir recupera la conversación de hoy', () async {
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado(pares: 2)});
      final c = await _contenedor(_ApiFalsa(const []));
      await _esperar();

      final s = c.read(chatProvider);
      expect(s.mensajes.map((m) => m.texto), ['pregunta 1', 'respuesta 1', 'pregunta 2', 'respuesta 2']);
      expect(s.dia, Fechas.hoy());
    });

    test('la conversación de ayer caduca y se borra', () async {
      final ayer = Fechas.iso(DateTime.parse(Fechas.hoy()).subtract(const Duration(days: 1)));
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado(dia: ayer)});
      final c = await _contenedor(_ApiFalsa(const []));
      await _esperar();

      expect(c.read(chatProvider).mensajes, isEmpty);
      expect(await _leerAlmacen(), isNull);
    });

    test('no muestra la conversación de otro usuario', () async {
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado(usuario: 99)});
      final c = await _contenedor(_ApiFalsa(const []));
      await _esperar();

      expect(c.read(chatProvider).mensajes, isEmpty);
      expect(await _leerAlmacen(), isNull);
    });

    test('al modelo solo van los últimos $chatMaxContexto mensajes', () async {
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado(pares: 10)});
      final api = _ApiFalsa([
        {'type': 'text', 'text': 'ok'},
      ]);
      final c = await _contenedor(api);
      await _esperar();
      await c.read(chatProvider.notifier).enviar('nueva');

      final enviados = (api.enviados.single as Map)['messages'] as List;
      expect(enviados.length, lessThanOrEqualTo(chatMaxContexto));
      expect(enviados.first['role'], 'user');
      expect(enviados.last['content'], 'nueva');
      // En pantalla sigue toda la conversación.
      expect(c.read(chatProvider).mensajes.length, 22);
    });

    test('guarda como máximo $chatMaxGuardados mensajes', () async {
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado(pares: 20)});
      final c = await _contenedor(_ApiFalsa([
        {'type': 'text', 'text': 'ok'},
      ]));
      await _esperar();
      await c.read(chatProvider.notifier).enviar('una más');

      final j = jsonDecode((await _leerAlmacen())!) as Map<String, dynamic>;
      final mensajes = j['mensajes'] as List;
      expect(mensajes.length, chatMaxGuardados);
      expect(mensajes.last, {'a': 'b', 't': 'ok'});
    });

    test('nueva conversación y cerrar sesión borran el historial', () async {
      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado()});
      final c = await _contenedor(_ApiFalsa(const []));
      await _esperar();
      c.read(chatProvider.notifier).nuevaConversacion();
      await _esperar();
      expect(c.read(chatProvider).mensajes, isEmpty);
      expect(await _leerAlmacen(), isNull);

      FlutterSecureStorage.setMockInitialValues({claveHistorialChat: _guardado()});
      await c.read(sessionProvider.notifier).logout();
      expect(await _leerAlmacen(), isNull);
    });
  });
}
