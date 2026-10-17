import 'package:geolocator/geolocator.dart';

class GpsException implements Exception {
  final String message;
  GpsException(this.message);
  @override
  String toString() => message;
}

/// Pide permiso y lee la ubicación actual con alta precisión.
/// Equivale a `navigator.geolocation.getCurrentPosition` de chequeo.html.
Future<Position> ubicacionActual() async {
  if (!await Geolocator.isLocationServiceEnabled()) {
    throw GpsException('Activa la ubicación (GPS) del celular para poder marcar.');
  }
  var permiso = await Geolocator.checkPermission();
  if (permiso == LocationPermission.denied) {
    permiso = await Geolocator.requestPermission();
  }
  if (permiso == LocationPermission.denied) {
    throw GpsException('Se necesita permiso de ubicación para marcar.');
  }
  if (permiso == LocationPermission.deniedForever) {
    throw GpsException(
        'El permiso de ubicación está bloqueado. Actívalo en Ajustes > Aplicaciones > BusControl.');
  }
  try {
    return await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: Duration(seconds: 20),
      ),
    );
  } catch (_) {
    throw GpsException('No se pudo obtener tu ubicación. Sal a un lugar abierto e intenta de nuevo.');
  }
}
