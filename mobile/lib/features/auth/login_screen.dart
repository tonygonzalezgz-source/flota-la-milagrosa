import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../../widgets/marca.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> with SingleTickerProviderStateMixin {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _cargando = false;
  bool _verPass = false;
  String? _error;

  /// Entrada escalonada: logo, nombre, campos y botón aparecen subiendo.
  late final AnimationController _entrada =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..forward();

  @override
  void dispose() {
    _entrada.dispose();
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _entrar() async {
    if (_user.text.trim().isEmpty || _pass.text.isEmpty) {
      setState(() => _error = 'Por favor completa ambos campos.');
      return;
    }
    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider.notifier).login(_user.text, _pass.text);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  /// Envuelve [child] para que aparezca entre [desde] y [hasta] (0–1) de la entrada.
  Widget _paso(double desde, double hasta, Widget child) {
    final a = CurvedAnimation(parent: _entrada, curve: Interval(desde, hasta, curve: Curves.easeOutCubic));
    return FadeTransition(
      opacity: a,
      child: SlideTransition(
        position: Tween(begin: const Offset(0, .25), end: Offset.zero).animate(a),
        child: child,
      ),
    );
  }

  /// Campo "vidrio" del login web. Se usa hintText (no labelText) para que el
  /// texto quede centrado dentro del campo y no flote sobre el borde.
  InputDecoration _campo(String hint, IconData icono, {Widget? sufijo}) => InputDecoration(
        hintText: hint,
        hintStyle: TextStyle(color: Marca.texto.withValues(alpha: .55)),
        prefixIcon: Icon(icono, color: Marca.cian),
        suffixIcon: sufijo,
        filled: true,
        fillColor: Colors.white.withValues(alpha: .07),
        contentPadding: const EdgeInsets.symmetric(vertical: 18, horizontal: 16),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: Marca.cian.withValues(alpha: .25)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide(color: Marca.cian.withValues(alpha: .25)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: Marca.cian, width: 1.6),
        ),
      );

  @override
  Widget build(BuildContext context) {
    const estiloTexto = TextStyle(color: Colors.white, fontSize: 16);
    return Scaffold(
      body: FondoAnimado(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  // Logo, nombre y subtítulo "viajan" desde la intro hasta aquí
                  // (Hero), así que no llevan animación de entrada propia.
                  const Center(child: Hero(tag: 'logo-buscontrol', child: LogoBusControl(tamano: 116))),
                  const SizedBox(height: 22),
                  const Hero(tag: 'nombre-buscontrol', child: NombreBusControl()),
                  const SizedBox(height: 4),
                  const Hero(tag: 'sub-buscontrol', child: SubtituloBusControl()),
                  const SizedBox(height: 36),
                  _paso(.35, .8, TextField(
                    controller: _user,
                    autocorrect: false,
                    enableSuggestions: false,
                    textInputAction: TextInputAction.next,
                    style: estiloTexto,
                    cursorColor: Marca.cian,
                    decoration: _campo('Usuario', Icons.person_outline),
                  )),
                  const SizedBox(height: 14),
                  _paso(.45, .9, TextField(
                    controller: _pass,
                    obscureText: !_verPass,
                    onSubmitted: (_) => _entrar(),
                    style: estiloTexto,
                    cursorColor: Marca.cian,
                    decoration: _campo(
                      'Contraseña',
                      Icons.lock_outline,
                      sufijo: IconButton(
                        color: Marca.texto,
                        icon: Icon(_verPass ? Icons.visibility_off : Icons.visibility),
                        onPressed: () => setState(() => _verPass = !_verPass),
                      ),
                    ),
                  )),
                  AnimatedSize(
                    duration: const Duration(milliseconds: 200),
                    child: _error == null
                        ? const SizedBox(width: double.infinity)
                        : Padding(
                            padding: const EdgeInsets.only(top: 14),
                            child: Text(_error!,
                                textAlign: TextAlign.center,
                                style: const TextStyle(color: Color(0xFFFCA5A5))),
                          ),
                  ),
                  const SizedBox(height: 24),
                  _paso(.55, 1, FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: Marca.azul,
                      disabledBackgroundColor: Marca.azul.withValues(alpha: .5),
                      minimumSize: const Size.fromHeight(54),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                    onPressed: _cargando ? null : _entrar,
                    child: _cargando
                        ? const SizedBox(
                            height: 22, width: 22,
                            child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                        : const Text('Ingresar'),
                  )),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
