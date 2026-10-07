import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/session.dart';

enum Autor { usuario, asistente, error }

class MensajeChat {
  final Autor autor;
  final String texto;
  const MensajeChat(this.autor, this.texto);
}

class EstadoChat {
  final List<MensajeChat> mensajes;

  /// Esperando respuesta del asistente (se bloquea el envío).
  final bool respondiendo;

  /// El asistente está consultando la base de datos (evento `tool`).
  final bool consultando;

  const EstadoChat({this.mensajes = const [], this.respondiendo = false, this.consultando = false});

  EstadoChat copyWith({List<MensajeChat>? mensajes, bool? respondiendo, bool? consultando}) => EstadoChat(
        mensajes: mensajes ?? this.mensajes,
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

/// Conversación con el asistente (`/api/chat`). Vive mientras la app esté
/// abierta y se borra al cambiar de usuario, igual que en la web.
final chatProvider = NotifierProvider<ChatController, EstadoChat>(ChatController.new);

class ChatController extends Notifier<EstadoChat> {
  @override
  EstadoChat build() {
    ref.watch(sessionProvider.select((s) => s.value?.id));
    return const EstadoChat();
  }

  Future<void> enviar(String texto) async {
    texto = texto.trim();
    if (texto.isEmpty || state.respondiendo) return;

    state = state.copyWith(
      mensajes: [...state.mensajes, MensajeChat(Autor.usuario, texto)],
      respondiendo: true,
    );
    // Al backend solo va el diálogo; los avisos de error se quedan en pantalla.
    final historial = [
      for (final m in state.mensajes)
        if (m.autor != Autor.error)
          {'role': m.autor == Autor.usuario ? 'user' : 'assistant', 'content': m.texto},
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
    if (ref.mounted) state = state.copyWith(respondiendo: false, consultando: false);
  }

  void _error(String texto) => state = state.copyWith(
        mensajes: [...state.mensajes, MensajeChat(Autor.error, texto)],
        consultando: false,
      );

  void nuevaConversacion() {
    if (!state.respondiendo) state = const EstadoChat();
  }
}
