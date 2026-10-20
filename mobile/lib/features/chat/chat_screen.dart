import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme.dart';
import '../../widgets/aurora.dart';
import 'chat_controller.dart';
import 'texto_markdown.dart';

const _sugerencias = [
  '¿Cómo nos fue esta semana frente a la pasada?',
  '¿Qué buses subieron o bajaron más esta semana?',
  '¿Qué documentos vencen en los próximos 30 días?',
];

/// Botón flotante que abre el asistente; no aparece si el chatbot está
/// apagado en el servidor o el rol no lo tiene.
class BotonAsistente extends ConsumerWidget {
  const BotonAsistente({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ref.watch(chatDisponibleProvider).value != true) return const SizedBox.shrink();
    return FloatingActionButton.extended(
      heroTag: 'asistente',
      backgroundColor: AppColors.primary,
      foregroundColor: Colors.white,
      elevation: 6,
      shape: const StadiumBorder(),
      icon: const Icon(Icons.auto_awesome),
      label: const Text('Asistente', style: TextStyle(fontWeight: FontWeight.w700)),
      onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ChatScreen())),
    );
  }
}

/// Chat con el asistente de BusControl (mismo `/api/chat` de la web).
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _texto = TextEditingController();

  @override
  void initState() {
    super.initState();
    // Si quedó abierta una conversación de ayer, ya caducó: se empieza otra.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) ref.read(chatProvider.notifier).revisarVigencia();
    });
  }

  @override
  void dispose() {
    _texto.dispose();
    super.dispose();
  }

  void _enviar([String? sugerencia]) {
    final t = (sugerencia ?? _texto.text).trim();
    if (t.isEmpty || ref.read(chatProvider).respondiendo) return;
    _texto.clear();
    ref.read(chatProvider.notifier).enviar(t);
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider);
    final esperando = chat.respondiendo && (chat.consultando || chat.mensajes.last.autor == Autor.usuario);

    // La lista va invertida para que siempre quede pegada al último mensaje,
    // también mientras la respuesta se va escribiendo.
    final items = <Widget>[
      const Center(
        child: Text(
          'Hoy · la conversación se guarda en este celular hasta la medianoche',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 11, color: AppColors.muted),
        ),
      ),
      _burbuja(const MensajeChat(
        Autor.asistente,
        'Hola 👋 Soy el asistente de BusControl. Pregúntame por tus buses: '
        'movilidad, comparativos, documentos por vencer o cómo está un bus por su número.',
      )),
      if (chat.mensajes.isEmpty) _sugerenciasView(),
      for (final m in chat.mensajes) _burbuja(m),
      if (esperando) _indicador(chat.consultando),
    ].reversed.toList();

    return Scaffold(
      backgroundColor: AppColors.bgLight,
      body: Column(children: [
        _cabecera(chat),
        Expanded(
          child: ListView.separated(
            reverse: true,
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
            itemCount: items.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (_, i) => items[i],
          ),
        ),
        _entrada(chat.respondiendo),
      ]),
    );
  }

  Widget _cabecera(EstadoChat chat) => CabeceraAurora(
        traslape: 20,
        child: Row(children: [
          BotonCabecera(icono: Icons.arrow_back, tooltip: 'Volver', onPressed: () => Navigator.of(context).pop()),
          const SizedBox(width: 12),
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(15)),
            child: const Icon(Icons.auto_awesome, color: AppColors.primary),
          ),
          const SizedBox(width: 12),
          const Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                'Asistente',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontFamily: Fuentes.titulo, fontSize: 19, fontWeight: FontWeight.w700, color: Colors.white),
              ),
              Text(
                'Consulta el estado de tus buses',
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, color: Color(0xFF9FB2E8)),
              ),
            ]),
          ),
          if (chat.mensajes.isNotEmpty)
            BotonCabecera(
              icono: Icons.add_comment_outlined,
              tooltip: 'Nueva conversación',
              onPressed: chat.respondiendo ? null : () => ref.read(chatProvider.notifier).nuevaConversacion(),
            ),
        ]),
      );

  Widget _burbuja(MensajeChat m) {
    const radio = Radius.circular(20);
    const pico = Radius.circular(6);
    switch (m.autor) {
      case Autor.usuario:
        return Align(
          alignment: Alignment.centerRight,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * .8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: const BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.only(topLeft: radio, topRight: radio, bottomLeft: radio, bottomRight: pico),
              ),
              child: Text(m.texto, style: const TextStyle(color: Colors.white, fontSize: 15, height: 1.4)),
            ),
          ),
        );
      case Autor.asistente:
        return Align(
          alignment: Alignment.centerLeft,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * .86),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
              decoration: const BoxDecoration(
                color: Colors.white,
                boxShadow: sombraSuave,
                borderRadius: BorderRadius.only(topLeft: radio, topRight: radio, bottomLeft: pico, bottomRight: radio),
              ),
              child: TextoMarkdown(
                m.texto,
                estilo: const TextStyle(color: AppColors.texto, fontSize: 15, height: 1.45),
              ),
            ),
          ),
        );
      case Autor.error:
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: const Color(0xFFFDECEC), borderRadius: BorderRadius.circular(16)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.error_outline, size: 18, color: Color(0xFFC0262D)),
              const SizedBox(width: 8),
              Flexible(
                child: Text(m.texto, style: const TextStyle(fontSize: 14, color: Color(0xFF7A1A1F))),
              ),
            ]),
          ),
        );
    }
  }

  /// Preguntas de ejemplo en pastillas que pueden partirse en dos líneas.
  Widget _sugerenciasView() => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final s in _sugerencias)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Material(
              color: AppColors.primarySoft,
              borderRadius: BorderRadius.circular(18),
              child: InkWell(
                borderRadius: BorderRadius.circular(18),
                onTap: () => _enviar(s),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  child: Text(
                    s,
                    style: const TextStyle(fontSize: 13, color: AppColors.primaryDark, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
            ),
          ),
      ]);

  Widget _indicador(bool consultando) => Align(
        alignment: Alignment.centerLeft,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 10),
            Text(
              consultando ? 'Consultando datos…' : 'Escribiendo…',
              style: const TextStyle(fontSize: 13, color: AppColors.muted, fontStyle: FontStyle.italic),
            ),
          ]),
        ),
      );

  Widget _entrada(bool respondiendo) => Container(
        decoration: const BoxDecoration(
          color: Colors.white,
          boxShadow: [BoxShadow(color: Color(0x140F1A33), blurRadius: 20, offset: Offset(0, -4))],
        ),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: TextField(
                  controller: _texto,
                  minLines: 1,
                  maxLines: 4,
                  textCapitalization: TextCapitalization.sentences,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _enviar(),
                  decoration: InputDecoration(
                    hintText: 'Ej: ¿cómo está el bus 5?',
                    contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(24),
                      borderSide: const BorderSide(color: AppColors.primary, width: 1.4),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                tooltip: 'Enviar',
                onPressed: respondiendo ? null : _enviar,
                style: IconButton.styleFrom(
                  fixedSize: const Size(48, 48),
                  backgroundColor: AppColors.primary,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: AppColors.primary.withValues(alpha: .4),
                  disabledForegroundColor: Colors.white,
                ),
                icon: const Icon(Icons.send_rounded),
              ),
            ]),
          ),
        ),
      );
}
