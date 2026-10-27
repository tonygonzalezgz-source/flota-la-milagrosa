import 'dart:ui';

import 'package:buscontrol/features/monitoreo/rutas_mapa.dart';
import 'package:flutter_test/flutter_test.dart';

const _lista = [
  {'id': 1, 'nombre': 'Ruta 1 — Centro › Norte', 'color': '#22C55E'},
  {'id': 2, 'nombre': 'Ruta 2 — Centro › Sur', 'color': '#22c55e'}, // repite color
  {'id': 3, 'nombre': 'Ruta 3', 'color': 'verde'}, // color inválido
  {'id': 4, 'nombre': 'Ruta 4 (sin trazado)', 'color': null},
];

const _geometria = [
  {
    'ruta_id': 1,
    'nombre': 'Ruta 1 — Centro › Norte',
    'color': '#22C55E',
    'trazados': {
      'ida': {
        'puntos': [
          [4.60, -74.08],
          [4.61, -74.07],
        ],
      },
      'regreso': {
        'puntos': [
          [4.61, -74.07],
          [4.60, -74.08],
        ],
      },
    },
    'puntos': [
      {'id': 7, 'orden': 1, 'nombre': 'Portal', 'lat': 4.60, 'lon': -74.08, 'radio_m': 80, 'sentido': 'ambos', 'tipo': 'terminal'},
    ],
  },
  {
    'ruta_id': 2,
    'nombre': 'Ruta 2 — Centro › Sur',
    'trazados': {
      'ida': {
        'puntos': [
          [4.58, -74.10],
        ],
      },
    },
    'puntos': [],
  },
];

const _buses = [
  {'bus_id': 1, 'numero': 1, 'ruta_id': 1},
  {'bus_id': 2, 'numero': 2, 'ruta_id': 2},
  {'bus_id': 3, 'numero': 3, 'ruta_id': 1},
  {'bus_id': 4, 'numero': 4, 'ruta_id': null}, // sin despacho hoy
];

void main() {
  test('une la lista de rutas con sus trazados y puntos de control', () {
    final rutas = RutaMapa.desde(_lista, _geometria);
    expect(rutas.map((r) => r.id), [1, 2, 3, 4]);
    expect(rutas[0].trazados.keys, ['ida', 'regreso']);
    expect(rutas[0].trazados['ida']!.last, (lat: 4.61, lon: -74.07));
    expect(rutas[0].puntos.single['nombre'], 'Portal');
    expect(rutas[1].trazados.keys, ['ida']);
    expect(rutas[3].tieneTrazado, isFalse); // aparece en el selector aunque no tenga trazado
  });

  test('si falla la lista de rutas se usan las de la geometría', () {
    final rutas = RutaMapa.desde(const [], _geometria);
    expect(rutas.map((r) => r.nombre), ['Ruta 1 — Centro › Norte', 'Ruta 2 — Centro › Sur']);
  });

  test('colores: el propio si es válido y único; si no, el primero libre de la paleta', () {
    final c = coloresRutas(RutaMapa.desde(_lista, const []));
    expect(c[1], const Color(0xFF22C55E));
    expect(c[2], paletaRutas[0]); // repetía el color de la ruta 1
    expect(c[3], paletaRutas[1]); // color inválido
    expect(c[4], paletaRutas[2]); // sin color
    expect(c.values.toSet().length, 4);
  });

  test('el regreso va en el tono claro del color de la ruta', () {
    final claro = aclarar(const Color(0xFF2563EB), .45);
    expect(claro, const Color(0xFF87A9F4)); // mismo cálculo que aclarar() de la web
    expect(aclarar(const Color(0xFF000000), 0), const Color(0xFF000000));
    expect(aclarar(const Color(0xFF000000), 1), const Color(0xFFFFFFFF));
  });

  test('con una ruta elegida solo se ven los buses despachados hoy en ella', () {
    expect(busesDeRuta(_buses, null).length, 4);
    expect(busesDeRuta(_buses, 1).map((b) => b['numero']), [1, 3]);
    expect(busesDeRuta(_buses, 4), isEmpty);
    expect(busesPorRuta(_buses), {1: 2, 2: 1});
  });
}
