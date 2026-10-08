import Flutter
import GoogleMaps
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    if let clave = claveGoogleMaps() {
      GMSServices.provideAPIKey(clave)
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  /// Clave de Google Maps de --dart-define=GOOGLE_MAPS_API_KEY=… (Flutter deja
  /// los dart-defines en base64 separados por comas; Info.plist los expone).
  private func claveGoogleMaps() -> String? {
    guard let lista = Bundle.main.object(forInfoDictionaryKey: "DartDefines") as? String else {
      return nil
    }
    for parte in lista.split(separator: ",") {
      guard let datos = Data(base64Encoded: String(parte)),
        let definicion = String(data: datos, encoding: .utf8)
      else { continue }
      let par = definicion.split(separator: "=", maxSplits: 1).map(String.init)
      if par.count == 2, par[0] == "GOOGLE_MAPS_API_KEY", !par[1].isEmpty {
        return par[1]
      }
    }
    return nil
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
  }
}
