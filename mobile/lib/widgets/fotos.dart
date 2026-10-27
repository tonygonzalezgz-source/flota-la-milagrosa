import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../core/theme.dart';
import 'comunes.dart';

/// Mismo tamaño y calidad que la web (canvas a 1600 px, JPEG 0.7): las fotos
/// pesan lo mismo venga de donde vengan y el backend no nota la diferencia.
const _maxLado = 1600.0;
const _calidad = 70;

/// Convierte bytes JPEG al formato que guarda el backend: un data URL.
String aDataUrl(Uint8List bytes, {String mime = 'image/jpeg'}) =>
    'data:$mime;base64,${base64Encode(bytes)}';

/// Decodifica un data URL (o base64 pelado) a bytes.
Uint8List? deDataUrl(String? s) {
  if (s == null || s.isEmpty) return null;
  final i = s.indexOf('base64,');
  try {
    return base64Decode(i >= 0 ? s.substring(i + 7) : s);
  } catch (_) {
    return null;
  }
}

/// Toma una foto con la cámara o la elige de la galería, ya reducida y comprimida.
Future<String?> tomarFoto(BuildContext context, ImageSource source) async {
  try {
    final x = await ImagePicker().pickImage(
      source: source,
      maxWidth: _maxLado,
      maxHeight: _maxLado,
      imageQuality: _calidad,
    );
    if (x == null) return null;
    return aDataUrl(await x.readAsBytes());
  } catch (e) {
    if (context.mounted) {
      mostrarMensaje(context, 'No se pudo acceder a la cámara: $e', error: true);
    }
    return null;
  }
}

/// Selector de evidencias fotográficas (hasta [maximo]) con miniaturas.
class FotosPicker extends StatelessWidget {
  final List<String> fotos;
  final int maximo;
  final ValueChanged<List<String>> onChanged;

  const FotosPicker({
    super.key,
    required this.fotos,
    required this.onChanged,
    this.maximo = 5,
  });

  Future<void> _agregar(BuildContext context, ImageSource src) async {
    if (fotos.length >= maximo) {
      mostrarMensaje(context, 'Máximo $maximo fotos por registro.', error: true);
      return;
    }
    final f = await tomarFoto(context, src);
    if (f != null) onChanged([...fotos, f]);
  }

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () => _agregar(context, ImageSource.camera),
            icon: const Icon(Icons.photo_camera_outlined),
            label: const Text('Cámara'),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () => _agregar(context, ImageSource.gallery),
            icon: const Icon(Icons.photo_library_outlined),
            label: const Text('Galería'),
          ),
        ),
      ]),
      const SizedBox(height: 6),
      Text('${fotos.length} de $maximo fotos',
          style: const TextStyle(fontSize: 12, color: AppColors.muted)),
      if (fotos.isNotEmpty) ...[
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (var i = 0; i < fotos.length; i++)
            Stack(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: Image.memory(deDataUrl(fotos[i])!,
                    width: 86, height: 86, fit: BoxFit.cover),
              ),
              Positioned(
                right: 2,
                top: 2,
                child: InkWell(
                  onTap: () => onChanged([...fotos]..removeAt(i)),
                  child: const CircleAvatar(
                    radius: 12,
                    backgroundColor: Colors.black54,
                    child: Icon(Icons.close, size: 15, color: Colors.white),
                  ),
                ),
              ),
            ]),
        ]),
      ],
    ]);
  }
}

/// Muestra a pantalla completa las fotos (data URLs) de un registro.
Future<void> verFotos(BuildContext context, List<String> fotos, {String? titulo}) {
  return Navigator.of(context).push(MaterialPageRoute(
    fullscreenDialog: true,
    builder: (_) => Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(title: Text(titulo ?? 'Evidencias')),
      body: fotos.isEmpty
          ? const Center(
              child: Text('Sin fotos', style: TextStyle(color: Colors.white70)))
          : PageView(children: [
              for (final f in fotos)
                InteractiveViewer(
                  child: Center(
                    child: deDataUrl(f) != null
                        ? Image.memory(deDataUrl(f)!)
                        : const Icon(Icons.broken_image, color: Colors.white54),
                  ),
                ),
            ]),
    ),
  ));
}
