import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config.dart';
import '../../core/session.dart';
import '../../widgets/marca.dart';

/// Login con el estilo "Cabina Neón" (propuesta A).
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

  /// Entrada escalonada: campos, botón y pie aparecen subiendo.
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

  /// Etiqueta en mayúsculas encima de un campo de vidrio. La etiqueta va
  /// fuera del campo para que nunca quede montada sobre el borde.
  Widget _campo({
    required String etiqueta,
    required IconData icono,
    required TextEditingController controller,
    required String pista,
    bool oculto = false,
    Widget? sufijo,
    TextInputAction? accion,
    ValueChanged<String>? alEnviar,
  }) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(etiqueta,
          style: const TextStyle(
            fontFamily: Marca.cuerpo,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 2,
            color: Marca.apagado,
          )),
      const SizedBox(height: 8),
      TextField(
        controller: controller,
        obscureText: oculto,
        autocorrect: false,
        enableSuggestions: false,
        textInputAction: accion,
        onSubmitted: alEnviar,
        cursorColor: Marca.cian,
        style: const TextStyle(fontFamily: Marca.cuerpo, color: Marca.texto, fontSize: 16, fontWeight: FontWeight.w500),
        decoration: InputDecoration(
          hintText: pista,
          hintStyle: const TextStyle(fontFamily: Marca.cuerpo, color: Color(0xFF5F7790)),
          prefixIcon: Icon(icono, color: Marca.cian),
          suffixIcon: sufijo,
          filled: true,
          fillColor: Colors.white.withValues(alpha: .04),
          contentPadding: const EdgeInsets.symmetric(vertical: 17, horizontal: 16),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: BorderSide(color: Marca.cian.withValues(alpha: .28)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(14),
            borderSide: const BorderSide(color: Marca.cian, width: 1.4),
          ),
        ),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final host = Uri.tryParse(AppConfig.apiUrl)?.host ?? AppConfig.apiUrl;
    return Scaffold(
      body: FondoAnimado(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  // Logo, nombre y subtítulo "viajan" desde la intro hasta aquí
                  // (Hero), así que no llevan animación de entrada propia.
                  const Center(child: Hero(tag: 'logo-buscontrol', child: LogoBusControl(tamano: 124))),
                  const SizedBox(height: 20),
                  const Hero(tag: 'nombre-buscontrol', child: NombreBusControl()),
                  const SizedBox(height: 6),
                  const Hero(tag: 'sub-buscontrol', child: SubtituloBusControl()),
                  const SizedBox(height: 40),
                  _paso(.3, .75, _campo(
                    etiqueta: 'USUARIO',
                    pista: 'Tu usuario',
                    icono: Icons.person_outline,
                    controller: _user,
                    accion: TextInputAction.next,
                  )),
                  const SizedBox(height: 16),
                  _paso(.4, .85, _campo(
                    etiqueta: 'CONTRASEÑA',
                    pista: 'Tu contraseña',
                    icono: Icons.lock_outline,
                    controller: _pass,
                    oculto: !_verPass,
                    alEnviar: (_) => _entrar(),
                    sufijo: IconButton(
                      color: Marca.apagado,
                      tooltip: _verPass ? 'Ocultar contraseña' : 'Mostrar contraseña',
                      icon: Icon(_verPass ? Icons.visibility_off_outlined : Icons.visibility_outlined),
                      onPressed: () => setState(() => _verPass = !_verPass),
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
                                style: const TextStyle(fontFamily: Marca.cuerpo, color: Color(0xFFFCA5A5))),
                          ),
                  ),
                  const SizedBox(height: 26),
                  _paso(.5, .95, _BotonNeon(cargando: _cargando, onPressed: _entrar)),
                  const SizedBox(height: 28),
                  _paso(.6, 1, Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: const BoxDecoration(
                        color: Marca.verde,
                        shape: BoxShape.circle,
                        boxShadow: [BoxShadow(color: Marca.verde, blurRadius: 10)],
                      ),
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text('Conexión cifrada con $host',
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontFamily: Marca.cuerpo, fontSize: 12, color: Color(0xFF6F87A0))),
                    ),
                  ])),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Botón principal cian con resplandor.
class _BotonNeon extends StatelessWidget {
  final bool cargando;
  final VoidCallback onPressed;
  const _BotonNeon({required this.cargando, required this.onPressed});

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          boxShadow: [BoxShadow(color: Marca.cian.withValues(alpha: .5), blurRadius: 28)],
        ),
        child: FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Marca.cian,
            foregroundColor: Marca.sobreCian,
            disabledBackgroundColor: Marca.cian.withValues(alpha: .5),
            minimumSize: const Size.fromHeight(58),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            textStyle: const TextStyle(fontFamily: Marca.display, fontSize: 16, fontWeight: FontWeight.w700, letterSpacing: 3),
          ),
          onPressed: cargando ? null : onPressed,
          child: cargando
              ? const SizedBox(
                  height: 22, width: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.5, color: Marca.sobreCian))
              : const Row(mainAxisSize: MainAxisSize.min, children: [
                  Text('INGRESAR'),
                  SizedBox(width: 12),
                  Icon(Icons.arrow_forward, size: 20),
                ]),
        ),
      );
}
