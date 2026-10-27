import 'package:flutter/material.dart';

/// Markdown mínimo del asistente, igual al de la web: párrafos, viñetas,
/// listas numeradas, títulos (como negrita), **negrita**, *cursiva* y `código`.
/// Así no se ven los asteriscos crudos.
class TextoMarkdown extends StatelessWidget {
  final String texto;
  final TextStyle estilo;
  const TextoMarkdown(this.texto, {super.key, required this.estilo});

  static final _vineta = RegExp(r'^\s*[-*•]\s+(.*)$');
  static final _numerada = RegExp(r'^\s*(\d+)[.)]\s+(.*)$');
  static final _titulo = RegExp(r'^\s*#{1,6}\s+(.*)$');

  @override
  Widget build(BuildContext context) {
    var src = texto;
    // Mientras llega la respuesta puede quedar un ** sin cerrar: se oculta
    // para que el texto no parpadee.
    if ('**'.allMatches(src).length.isOdd) {
      final i = src.lastIndexOf('**');
      src = src.substring(0, i) + src.substring(i + 2);
    }

    final bloques = <Widget>[];
    for (final linea in src.split('\n')) {
      if (linea.trim().isEmpty) continue;
      final v = _vineta.firstMatch(linea);
      final n = _numerada.firstMatch(linea);
      final t = _titulo.firstMatch(linea);
      if (v != null || n != null) {
        bloques.add(Padding(
          padding: const EdgeInsets.only(left: 2),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 18, child: Text(v != null ? '•' : '${n!.group(1)}.', style: estilo)),
            Expanded(child: Text.rich(TextSpan(children: spansMarkdown(v?.group(1) ?? n!.group(2)!)), style: estilo)),
          ]),
        ));
      } else if (t != null) {
        bloques.add(Text.rich(
          TextSpan(children: spansMarkdown(t.group(1)!)),
          style: estilo.copyWith(fontWeight: FontWeight.w700),
        ));
      } else {
        bloques.add(Text.rich(TextSpan(children: spansMarkdown(linea)), style: estilo));
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < bloques.length; i++) ...[
          if (i > 0) const SizedBox(height: 6),
          bloques[i],
        ],
      ],
    );
  }
}

final _enLinea = RegExp(r'\*\*([^*]+)\*\*|\*([^*\n]+)\*|`([^`]+)`');

/// Negrita, cursiva y código dentro de una línea.
List<InlineSpan> spansMarkdown(String linea) {
  final out = <InlineSpan>[];
  var desde = 0;
  for (final m in _enLinea.allMatches(linea)) {
    if (m.start > desde) out.add(TextSpan(text: linea.substring(desde, m.start)));
    if (m.group(1) != null) {
      out.add(TextSpan(text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w700)));
    } else if (m.group(2) != null) {
      out.add(TextSpan(text: m.group(2), style: const TextStyle(fontStyle: FontStyle.italic)));
    } else {
      out.add(TextSpan(
        text: m.group(3),
        style: const TextStyle(fontFamily: 'monospace', backgroundColor: Color(0x140F1A33)),
      ));
    }
    desde = m.end;
  }
  if (desde < linea.length) out.add(TextSpan(text: linea.substring(desde)));
  return out;
}
