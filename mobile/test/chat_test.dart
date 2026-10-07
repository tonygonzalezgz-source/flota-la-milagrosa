import 'package:buscontrol/core/api_client.dart';
import 'package:buscontrol/core/session.dart';
import 'package:buscontrol/features/chat/chat_controller.dart';
import 'package:buscontrol/features/chat/texto_markdown.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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

void main() {
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
}
