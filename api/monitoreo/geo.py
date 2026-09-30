"""Geometría sobre trazados de ruta, sin dependencias externas.

Las rutas urbanas miden pocos km, así que se proyecta a un plano local
equirectangular (metros) alrededor de la ruta: el error frente a la distancia
geodésica es de centímetros a esta escala y los cálculos quedan triviales.
Las coordenadas se manejan como [lat, lon].
"""
import math

RADIO_TIERRA_M = 6371008.8
_M_POR_GRADO = math.pi / 180 * RADIO_TIERRA_M


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(math.sqrt(a))


class Plano:
    """Proyección local lat/lon → x/y en metros, centrada en `lat0`."""

    def __init__(self, lat0):
        self.kx = _M_POR_GRADO * math.cos(math.radians(lat0))
        self.ky = _M_POR_GRADO

    def xy(self, lat, lon):
        return lon * self.kx, lat * self.ky


def plano_para(*lineas):
    lats = [p[0] for linea in lineas for p in (linea or [])]
    return Plano(sum(lats) / len(lats) if lats else 0.0)


def longitud_m(linea):
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(linea, linea[1:]))


def proyectar(lat, lon, linea, plano):
    """Punto más cercano del trazado al punto dado.
    Devuelve (distancia_m, medida_m, indice_segmento): `medida_m` es la
    distancia recorrida sobre el trazado desde su inicio hasta la proyección."""
    if not linea:
        return None, None, None
    px, py = plano.xy(lat, lon)
    if len(linea) == 1:
        x, y = plano.xy(*linea[0])
        return math.hypot(px - x, py - y), 0.0, 0
    mejor = (float("inf"), 0.0, 0)
    acumulado = 0.0
    ax, ay = plano.xy(*linea[0])
    for i in range(1, len(linea)):
        bx, by = plano.xy(*linea[i])
        dx, dy = bx - ax, by - ay
        largo2 = dx * dx + dy * dy
        t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
        cx, cy = ax + t * dx, ay + t * dy
        d = math.hypot(px - cx, py - cy)
        largo = math.sqrt(largo2)
        if d < mejor[0]:
            mejor = (d, acumulado + t * largo, i - 1)
        acumulado += largo
        ax, ay = bx, by
    return mejor


def distancia_extremos_m(linea_a, linea_b):
    """Distancia entre el final de A y el inicio de B (ida → regreso)."""
    if not linea_a or not linea_b:
        return None
    return haversine_m(linea_a[-1][0], linea_a[-1][1], linea_b[0][0], linea_b[0][1])
