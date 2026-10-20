import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/fechas.dart';
import '../../core/session.dart';

/// Mensajes que se guardan en el celular (unas 20 preguntas con su respuesta).
const chatMaxGuardados = 40;

/// Mensajes de la conversación que acompañan cada pregunta al modelo. El resto
/// se sigue viendo en pantalla pero no se manda, para no gastar más tokens
/// (el servidor además corta en 10).
const chatMaxContexto = 8;

enum Autor { usuario, asistente, error }

class MensajeChat {
  final Autor autor;
  final String texto;
  const MensajeChat(this.autor, this.texto);
}

class EstadoChat {
  final List<MensajeChat> mensajes;

  /// Día (Bogotá, YYYY-MM-DD) en que empezó la conversación; caduca al
  /// cambiar el día.
  final String dia;

  /// Esperando respuesta del asistente (se bloquea el envío).
  final bool respondiendo;

  /// El asistente está consultando la base de datos (evento `tool`).
  final bool consultando;

  const EstadoChat({this.mensajes = const [], this.dia = '', this.respondiendo = false, this.consultando = false});

  EstadoChat copyWith({List<MensajeChat>? mensajes, String? dia, bool? respondiendo, bool? consultando}) => EstadoChat(
        mensajes: mensajes ?? this.mensajes,
        dia: dia ?? this.dia,
        respondiendo: respondiendo ?? this.respondiendo,
        consultando: consultando ?? this.consultando,
      );
}

/// El asistente se ofrece donde la web lo muestra (dashboard del administrador
/// y Mis Buses del propietario) y solo si el backend lo tiene encendido
/// (`FEATURE_CHATBOT` → `chatbot_enabled` en `/api/me`).
final chatDisponibleProvider = FutureProvider<bool>((ref) async {
  final user = ref.watch(sessionProvider.select((s) => s.value));
  if (user == null) return false;
  if (!user.allowedViews.contains('dashboard') && !user.allowedViews.contains('propietario')) {
    return false;
  }
  try {
    final me = await ref.read(apiClientProvider).get('/me');
    return me is Map && me['chatbot_enabled'] == true;
  } catch (_) {
    // Sin red o error: el botón simplemente no aparece, como en la web.
    return false;
  }
});

/// Conversación con el asistente (`/api/chat`).
///
/// Historial: se guarda solo en el celular, cifrado (Keychain / Keystore), nunca
/// en la base de datos. Dura el día: a la medianoche (hora Colombia) empieza
/// una conversación nueva, porque las respuestas hablan de "hoy" y "esta
/// semana". Se borra también al cerrar sesión o con "Nueva conversación".
final chatProvider = NotifierProvider<ChatController, EstadoChat>(ChatController.new);

class ChatController extends Notifier<EstadoChat> {
  @override
  EstadoChat build() {
    final uid = ref.watch(sessionProvider.select((s) => s.value?.id));
    if (uid != null) Future.microtask(() => _cargar(uid));
    return const EstadoChat();
  }

  Future<void> _cargar(int uid) async {
    final almacen = ref.read(secureStorageProvider);
    try {
      final raw = await almacen.read(key: claveHistorialChat);
      if (raw == null || !ref.mounted || state.mensajes.isNotEmpty) return;
      final j = jsonDecode(raw) as Map<String, dynamic>;
      if (j['usuario'] != uid || j['dia'] != Fechas.hoy()) {
        // Es de otro usuario o de otro día: ya caducó.
        await almacen.delete(key: claveHistorialChat);
        return;
      }
      final mensajes = [
        for (final m in j['mensajes'] as List)
          MensajeChat(m['a'] == 'u' ? Autor.usuario : Autor.asistente, m['t'] as String),
      ];
      if (ref.mounted && state.mensajes.isEmpty) {
        state = EstadoChat(mensajes: mensajes, dia: j['dia'] as String);
      }
    } catch (_) {
      // Un historial ilegible no debe impedir usar el asistente.
    }
  }

  Future<void> _guardar() async {
    final uid = ref.read(sessionProvider).value?.id;
    if (uid == null) return;
    final dialogo = [for (final m in state.mensajes) if (m.autor != Autor.error) m];
    final ultimos = dialogo.length > chatMaxGuardados ? dialogo.sublist(dialogo.length - chatMaxGuardados) : dialogo;
    try {
      await ref.read(secureStorageProvider).write(
            key: claveHistorialChat,
            value: jsonEncode({
              'usuario': uid,
              'dia': state.dia,
              'mensajes': [
                for (final m in ultimos) {'a': m.autor == Autor.usuario ? 'u' : 'b', 't': m.texto},
              ],
            }),
          );
    } catch (_) {}
  }

  /// Si la conversación es de un día anterior, la cierra y empieza una nueva.
  void revisarVigencia() {
    if (!state.respondiendo && state.mensajes.isNotEmpty && state.dia != Fechas.hoy()) {
      state = const EstadoChat();
      ref.read(secureStorageProvider).delete(key: claveHistorialChat).ignore();
    }
  }

  Future<void> enviar(String texto) async {
    texto = texto.trim();
    if (texto.isEmpty || state.respondiendo) return;
    revisarVigencia();

    state = state.copyWith(
      mensajes: [...state.mensajes, MensajeChat(Autor.usuario, texto)],
      dia: Fechas.hoy(),
      respondiendo: true,
    );
    // Al modelo solo van los últimos mensajes del diálogo (sin los avisos de
    // error) y siempre empezando por una pregunta.
    var contexto = [for (final m in state.mensajes) if (m.autor != Autor.error) m];
    if (contexto.length > chatMaxContexto) contexto = contexto.sublist(contexto.length - chatMaxContexto);
    while (contexto.first.autor != Autor.usuario) {
      contexto = contexto.sublist(1);
    }
    final historial = [
      for (final m in contexto) {'role': m.autor == Autor.usuario ? 'user' : 'assistant', 'content': m.texto},
    ];

    var respuesta = '';
    var indice = -1; // posición de la burbuja del asistente en curso
    try {
      await for (final ev in ref.read(apiClientProvider).postEventos('/chat', body: {'messages': historial})) {
        if (!ref.mounted) return;
        switch (ev['type']) {
          case 'text':
            respuesta += (ev['text'] ?? '').toString();
            final lista = [...state.mensajes];
            if (indice < 0) {
              indice = lista.length;
              lista.add(MensajeChat(Autor.asistente, respuesta));
            } else {
              lista[indice] = MensajeChat(Autor.asistente, respuesta);
            }
            state = state.copyWith(mensajes: lista, consultando: false);
          case 'tool':
            state = state.copyWith(consultando: true);
          case 'error':
            _error((ev['error'] ?? 'El asistente tuvo un problema al responder. Intenta de nuevo.').toString());
          case 'done':
            state = state.copyWith(consultando: false);
        }
      }
    } on ApiException catch (e) {
      if (!ref.mounted) return;
      _error(e.statusCode == 404 ? 'El asistente no está habilitado en este momento.' : e.message);
    } catch (_) {
      if (!ref.mounted) return;
      _error('Error de conexión con el asistente.');
    }
    if (!ref.mounted) return;
    state = state.copyWith(respondiendo: false, consultando: false);
    await _guardar();
  }

  void _error(String texto) => state = state.copyWith(
        mensajes: [...state.mensajes, MensajeChat(Autor.error, texto)],
        consultando: false,
      );

  void nuevaConversacion() {
    if (state.respondiendo) return;
    state = const EstadoChat();
    ref.read(secureStorageProvider).delete(key: claveHistorialChat).ignore();
  }
}
