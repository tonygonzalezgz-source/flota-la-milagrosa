"""Motor de análisis de recorridos.

Con las posiciones GPS de un bus en un día y la ruta que le asignó el despacho
calcula:

  • pasos por los puntos de control (entrada, salida y hora de paso), agrupados
    en vueltas que empiezan cuando el bus sale de un terminal; con los minutos
    objetivo de cada punto da el atraso (+) o adelanto (−);
  • excesos de velocidad, con los umbrales de aviso y crítico de la ruta (o de
    un tramo con límite propio);
  • abandonos de ruta: el bus fuera del corredor de la ruta. Solo cuentan
    después de que el bus entró a la ruta ese día (antes viene del patio).

Es puro (no toca la BD): lo usan los reportes sobre el histórico y lo podrá
usar el motor en vivo con las mismas reglas.

Con un reporte cada 30 s un bus a 40 km/h avanza ~330 m entre posiciones, así
que un punto de control de 50 m de radio puede quedar "entre" dos posiciones:
el paso se detecta con el segmento que une posiciones consecutivas (no solo con
las posiciones) y la hora se interpola sobre ese segmento.
"""
import bisect
import math
from datetime import timedelta

from . import geo

CELDA_M = 100                 # índice espacial de los trazados
MAX_HUECO_PASO_S = 300        # más separadas que esto no se interpola el camino entre ellas
SEPARACION_VISITAS_S = 120    # dos toques al mismo punto más cercanos = una sola visita
MAX_HUECO_EXCESO_S = 180      # un exceso se corta tras 3 min sin datos
VUELTA_MINIMA_S = 600         # salida y regreso al terminal sin pasar por ningún control
RUMBO_MIN_KMH = 5             # más despacio el rumbo del GPS no es confiable
MOVIMIENTO_RUMBO_M = 20       # desplazamiento mínimo para calcular el rumbo entre posiciones
DIFERENCIA_RUMBO_GRADOS = 45  # para decidir el sentido en tramos compartidos
ANGULO_SENTIDO_GRADOS = 60    # rumbo del bus vs. el del trazado para aceptar un cambio de sentido
MAX_SALTO_KMH = 200           # saltos más rápidos que esto no suman kilómetros


def _angulo(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def _rumbo_xy(ax, ay, bx, by):
    return math.degrees(math.atan2(bx - ax, by - ay)) % 360


def _simplificar(xy, tolerancia):
    """Douglas-Peucker iterativo: los KML traen muchos vértices casi alineados
    que no cambian la geometría pero multiplican el trabajo."""
    if len(xy) <= 2:
        return xy
    conservar = [False] * len(xy)
    conservar[0] = conservar[-1] = True
    pila = [(0, len(xy) - 1)]
    while pila:
        i, j = pila.pop()
        (ax, ay), (bx, by) = xy[i], xy[j]
        dx, dy = bx - ax, by - ay
        largo = math.hypot(dx, dy)
        peor, k_peor = -1.0, None
        for k in range(i + 1, j):
            px, py = xy[k]
            d = (abs(dy * (px - ax) - dx * (py - ay)) / largo) if largo else math.hypot(px - ax, py - ay)
            if d > peor:
                peor, k_peor = d, k
        if k_peor is not None and peor > tolerancia:
            conservar[k_peor] = True
            pila += [(i, k_peor), (k_peor, j)]
    return [p for p, c in zip(xy, conservar) if c]


class Trazado:
    """Un sentido de la ruta con índice espacial por celdas, para proyectar
    miles de posiciones sin recorrer todos los vértices cada vez."""

    TOLERANCIA_M = 2.0

    def __init__(self, linea, plano):
        self.linea = linea
        self.plano = plano
        self.xy = _simplificar([plano.xy(lat, lon) for lat, lon in linea], self.TOLERANCIA_M)
        self.acum = [0.0]
        self.rumbos = []
        self.celdas = {}
        for i in range(len(self.xy) - 1):
            (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
            self.acum.append(self.acum[-1] + math.hypot(bx - ax, by - ay))
            self.rumbos.append(_rumbo_xy(ax, ay, bx, by))
            for cx in range(math.floor(min(ax, bx) / CELDA_M), math.floor(max(ax, bx) / CELDA_M) + 1):
                for cy in range(math.floor(min(ay, by) / CELDA_M), math.floor(max(ay, by) / CELDA_M) + 1):
                    self.celdas.setdefault((cx, cy), []).append(i)

    def _segmento(self, i, px, py):
        (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
        dx, dy = bx - ax, by - ay
        largo2 = dx * dx + dy * dy
        t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), self.acum[i] + t * math.sqrt(largo2)

    def cercano(self, lat, lon, radio):
        """(distancia_m, medida_m, segmento) del tramo más cercano a <= radio, o None."""
        px, py = self.plano.xy(lat, lon)
        candidatos = set()
        for cx in range(math.floor((px - radio) / CELDA_M), math.floor((px + radio) / CELDA_M) + 1):
            for cy in range(math.floor((py - radio) / CELDA_M), math.floor((py + radio) / CELDA_M) + 1):
                candidatos.update(self.celdas.get((cx, cy), ()))
        mejor = None
        for i in candidatos:
            d, m = self._segmento(i, px, py)
            if d <= radio and (mejor is None or d < mejor[0]):
                mejor = (d, m, i)
        return mejor

    def distancia(self, lat, lon):
        """Distancia al trazado recorriéndolo entero (para las pocas posiciones fuera de ruta)."""
        px, py = self.plano.xy(lat, lon)
        return min(self._segmento(i, px, py)[0] for i in range(len(self.xy) - 1))


class Ruta:
    """Geometría de una ruta lista para el motor (los índices se construyen una vez)."""

    def __init__(self, ruta_id, nombre, trazados, puntos, tramos=()):
        self.id = ruta_id
        self.nombre = nombre
        lineas = [l for l in trazados.values() if l]
        self.plano = geo.plano_para(*lineas) if lineas else geo.Plano(0.0)
        self.trazados = {s: Trazado(l, self.plano) for s, l in trazados.items() if l and len(l) >= 2}
        self.puntos = []
        for p in sorted(puntos, key=lambda q: q.get("orden") or 0):
            x, y = self.plano.xy(p["lat"], p["lon"])
            self.puntos.append({**p, "_x": x, "_y": y})
        self.tramos = list(tramos)

    @property
    def tiene_terminal(self):
        return any(p["tipo"] == "terminal" for p in self.puntos)


# ══════════════════════════════════════════
#  Estado de cada posición frente a la ruta
# ══════════════════════════════════════════

def _estados(pos, ruta, cfg):
    """Por posición: en_ruta, sentido, medida (m sobre el trazado) y si su
    precisión es dudosa. El sentido se decide por cercanía; donde ida y regreso
    comparten calle, por el rumbo del bus; si aún es ambiguo, se mantiene el anterior."""
    corredor = cfg["corredor_m"]
    prec_max = cfg["precision_max_m"]
    anterior = None
    previa = None
    for p in pos:
        p["dudosa"] = p["precision"] is not None and p["precision"] > prec_max
        p["en_ruta"], p["sentido"], p["medida"] = False, None, None
        if not ruta or not ruta.trazados:
            continue
        cand = {}
        for s, t in ruta.trazados.items():
            c = t.cercano(p["lat"], p["lon"], corredor)
            if c:
                cand[s] = c
        p["en_ruta"] = bool(cand)
        rumbo = None
        if p["vel"] is not None and p["vel"] >= RUMBO_MIN_KMH and p["rumbo"] is not None:
            rumbo = p["rumbo"]
        elif previa is not None:
            ax, ay = ruta.plano.xy(previa["lat"], previa["lon"])
            bx, by = ruta.plano.xy(p["lat"], p["lon"])
            if math.hypot(bx - ax, by - ay) >= MOVIMIENTO_RUMBO_M:
                rumbo = _rumbo_xy(ax, ay, bx, by)
        sentido = None
        if len(cand) == 1:
            sentido = next(iter(cand))
            # Cruzando de través (o en contravía) la calle del otro sentido: no cambia de sentido.
            if (rumbo is not None and anterior and anterior != sentido and
                    _angulo(rumbo, ruta.trazados[sentido].rumbos[cand[sentido][2]]) > ANGULO_SENTIDO_GRADOS):
                p["sentido"] = anterior
                previa = p
                continue
        elif len(cand) > 1:
            if rumbo is not None:
                dif = sorted((_angulo(rumbo, ruta.trazados[s].rumbos[c[2]]), s) for s, c in cand.items())
                if dif[1][0] - dif[0][0] >= DIFERENCIA_RUMBO_GRADOS:
                    sentido = dif[0][1]
            if sentido is None:
                sentido = anterior if anterior in cand else min(cand, key=lambda s: cand[s][0])
        if sentido:
            p["sentido"], p["medida"] = sentido, cand[sentido][1]
            anterior = sentido
        previa = p


# ══════════════════════════════════════════
#  Excesos de velocidad
# ══════════════════════════════════════════

def _limites(p, ruta, cfg):
    if ruta and p["sentido"] and p["medida"] is not None:
        for t in ruta.tramos:
            if t["sentido"] == p["sentido"] and t["desde_m"] <= p["medida"] <= t["hasta_m"]:
                return t["vel_aviso_kmh"], t["vel_critica_kmh"], t.get("nombre") or "Tramo"
    return cfg["vel_aviso_kmh"], cfg["vel_critica_kmh"], None


def _excesos(pos, ruta, cfg):
    excesos, actual = [], None

    def cerrar():
        e = actual
        m = e["max"]
        excesos.append({
            "inicio": e["inicio"], "fin": e["fin"],
            "duracion_s": int((e["fin"] - e["inicio"]).total_seconds()),
            "posiciones": e["n"], "vel_max": round(m["vel"], 1),
            "limite_aviso": e["aviso"], "limite_critico": e["critica"],
            "exceso_kmh": round(m["vel"] - e["aviso"], 1),
            "nivel": "critico" if m["vel"] > e["critica"] else "aviso",
            "lat": m["lat"], "lon": m["lon"], "hora_max": m["t"],
            "sentido": m["sentido"], "tramo": e["tramo"], "en_ruta": m["en_ruta"],
        })

    for p in pos:
        if p["vel"] is None:
            continue
        aviso, critica, tramo = _limites(p, ruta, cfg)
        if p["vel"] > aviso:
            if actual and (p["t"] - actual["fin"]).total_seconds() <= MAX_HUECO_EXCESO_S:
                actual["fin"] = p["t"]
                actual["n"] += 1
                if p["vel"] > actual["max"]["vel"]:
                    actual.update(max=p, aviso=aviso, critica=critica, tramo=tramo)
            else:
                if actual:
                    cerrar()
                actual = {"inicio": p["t"], "fin": p["t"], "n": 1, "max": p,
                          "aviso": aviso, "critica": critica, "tramo": tramo}
        elif actual:
            cerrar()
            actual = None
    if actual:
        cerrar()
    return excesos


# ══════════════════════════════════════════
#  Abandonos de ruta
# ══════════════════════════════════════════

def _en_encierro(p, zonas):
    for z in zonas:
        if geo.haversine_m(p["lat"], p["lon"], z["lat"], z["lon"]) <= z["radio_m"]:
            return z
    return None


def _largo_m(camino):
    total = 0.0
    for a, b in zip(camino, camino[1:]):
        d = geo.haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        dt = (b["t"] - a["t"]).total_seconds()
        if dt > 0 and d / dt * 3.6 <= MAX_SALTO_KMH:
            total += d
    return total


def _abandonos(pos, ruta, cfg, zonas):
    """Episodios fuera del corredor después de haber entrado a la ruta.
    Empieza con `posiciones_fuera` posiciones seguidas fuera (las de precisión
    dudosa no cuentan) y termina con la primera de vuelta en la ruta."""
    if not ruta or not ruta.trazados:
        return [], None
    episodios, fuera, actual = [], [], None
    ultima_en_ruta = None
    inicio_ruta = None

    def cerrar(regreso):
        out = actual["fuera"]
        camino = ([actual["desde"]] if actual["desde"] else []) + out + ([regreso] if regreso else [])
        dist_max, punto_max = -1.0, out[0]
        for p in out:
            d = min(t.distancia(p["lat"], p["lon"]) for t in ruta.trazados.values())
            if d > dist_max:
                dist_max, punto_max = d, p
        zona = next((z for z in (_en_encierro(p, zonas) for p in out) if z), None)
        fin = regreso["t"] if regreso else out[-1]["t"]
        episodios.append({
            "inicio": out[0]["t"], "fin": regreso["t"] if regreso else None,
            "duracion_s": int((fin - out[0]["t"]).total_seconds()),
            "posiciones": len(out),
            "distancia_max_m": round(dist_max),
            "km_fuera": round(_largo_m(camino) / 1000, 2),
            "salida_lat": out[0]["lat"], "salida_lon": out[0]["lon"],
            "max_lat": punto_max["lat"], "max_lon": punto_max["lon"],
            "regreso_lat": regreso["lat"] if regreso else None,
            "regreso_lon": regreso["lon"] if regreso else None,
            "regreso": regreso is not None,
            "sentido_previo": actual["desde"]["sentido"] if actual["desde"] else None,
            "tipo": "encierro" if zona else "abandono",
            "encierro": zona["nombre"] if zona else None,
        })

    for p in pos:
        if p["dudosa"]:
            continue
        if p["en_ruta"]:
            if actual:
                cerrar(p)
                actual = None
            fuera = []
            ultima_en_ruta = p
            inicio_ruta = inicio_ruta or p["t"]
            continue
        if inicio_ruta is None:
            continue   # "Sin iniciar recorrido": aún viene del patio
        if actual:
            actual["fuera"].append(p)
            continue
        fuera.append(p)
        if len(fuera) >= cfg["posiciones_fuera"]:
            actual = {"desde": ultima_en_ruta, "fuera": fuera}
            fuera = []
    if actual:
        cerrar(None)
    return episodios, inicio_ruta


# ══════════════════════════════════════════
#  Pasos por puntos de control y vueltas
# ══════════════════════════════════════════

def _toques(pos, punto):
    """Intervalos [entrada, salida] en que el camino del bus está dentro del
    radio del punto, con la hora y distancia de máximo acercamiento.
    Cada posición trae `_xy` en el plano de la ruta."""
    r = punto["radio_m"]
    px, py = punto["_x"], punto["_y"]
    toques = []
    prev = None
    for p in pos:
        bx, by = p["_xy"]
        if prev is None or (p["t"] - prev["t"]).total_seconds() > MAX_HUECO_PASO_S:
            # Sin camino conocido desde la posición anterior: solo cuenta la posición.
            d = math.hypot(bx - px, by - py)
            if d <= r:
                toques.append((p["t"], p["t"], p["t"], d))
            prev = p
            continue
        ax, ay = prev["_xy"]
        if (min(ax, bx) - r > px or max(ax, bx) + r < px or
                min(ay, by) - r > py or max(ay, by) + r < py):
            prev = p
            continue
        dx, dy = bx - ax, by - ay
        fx, fy = ax - px, ay - py
        a = dx * dx + dy * dy
        dt = (p["t"] - prev["t"]).total_seconds()
        if a == 0:
            d = math.hypot(fx, fy)
            if d <= r:
                toques.append((prev["t"], p["t"], prev["t"], d))
            prev = p
            continue
        b = 2 * (fx * dx + fy * dy)
        c = fx * fx + fy * fy - r * r
        disc = b * b - 4 * a * c
        if disc >= 0:
            raiz = math.sqrt(disc)
            s1, s2 = max(0.0, (-b - raiz) / (2 * a)), min(1.0, (-b + raiz) / (2 * a))
            if s1 <= s2:
                sm = max(0.0, min(1.0, -(fx * dx + fy * dy) / a))
                d = math.hypot(fx + sm * dx, fy + sm * dy)
                t0 = prev["t"]
                toques.append((t0 + timedelta(seconds=s1 * dt), t0 + timedelta(seconds=s2 * dt),
                               t0 + timedelta(seconds=sm * dt), d))
        prev = p
    return toques


def _visitas(toques):
    visitas = []
    for t_in, t_out, t_paso, d in sorted(toques):
        v = visitas[-1] if visitas else None
        if v and (t_in - v["salida"]).total_seconds() <= SEPARACION_VISITAS_S:
            v["salida"] = max(v["salida"], t_out)
            if d < v["distancia_m"]:
                v["paso"], v["distancia_m"] = t_paso, d
        else:
            visitas.append({"entrada": t_in, "salida": t_out, "paso": t_paso, "distancia_m": d})
    return visitas


def _sentido_en(pos, tiempos, t):
    """Sentido del bus en el instante t (el último conocido hasta ese momento)."""
    i = bisect.bisect_right(tiempos, t) - 1
    while i >= 0:
        if pos[i]["sentido"]:
            return pos[i]["sentido"]
        i -= 1
    return None


def _minutos(segundos):
    return round(segundos / 60, 1)


def _pasos_y_vueltas(pos, ruta):
    if not ruta or not ruta.puntos or not pos:
        return [], []
    for p in pos:
        p["_xy"] = ruta.plano.xy(p["lat"], p["lon"])
    tiempos = [p["t"] for p in pos]
    pasos = []
    for punto in ruta.puntos:
        for v in _visitas(_toques(pos, punto)):
            sentido_bus = _sentido_en(pos, tiempos, v["paso"])
            # Un control de un solo sentido no cuenta cuando el bus va en el
            # otro (calles paralelas o doble vía a menos del radio).
            if (punto["tipo"] == "control" and punto["sentido"] in ("ida", "regreso")
                    and sentido_bus and sentido_bus != punto["sentido"]):
                continue
            pasos.append({**v, "distancia_m": round(v["distancia_m"]), "punto": punto,
                          "sentido_bus": sentido_bus, "vuelta": None, "vuelta_llegada": None,
                          "vuelta_salida": None, "transcurrido_min": None, "desvio_min": None})
    pasos.sort(key=lambda x: (x["entrada"], x["punto"].get("orden") or 0))

    vueltas, actual, n = [], None, 0

    def cerrar(llegada=None):
        nonlocal n
        sin_controles = not actual["pasos"]
        dur = (llegada["entrada"] - actual["salida"]).total_seconds() if llegada else None
        if sin_controles and (dur is None or dur < VUELTA_MINIMA_S):
            # Salió y volvió al terminal sin hacer recorrido (o salió al patio): no es vuelta.
            return
        n += 1
        actual["n"] = n
        actual["paso_salida"]["vuelta_salida"] = n
        for paso in actual["pasos"]:
            paso["vuelta"] = n
        if llegada:
            llegada["vuelta_llegada"] = n
            obj = llegada["punto"].get("minutos_objetivo")
            actual.update(llegada=llegada["entrada"], terminal_llegada=llegada["punto"],
                          duracion_min=_minutos(dur),
                          objetivo_llegada_min=obj,
                          desvio_llegada_min=round(dur / 60 - obj) if obj else None)
        vueltas.append(actual)

    for paso in pasos:
        punto = paso["punto"]
        if punto["tipo"] == "terminal":
            if actual:
                cerrar(paso)
            actual = {"salida": paso["salida"], "terminal_salida": punto, "paso_salida": paso, "llegada": None,
                      "terminal_llegada": None, "duracion_min": None, "objetivo_llegada_min": None,
                      "desvio_llegada_min": None, "pasos": []}
            continue
        if actual:
            seg = (paso["paso"] - actual["salida"]).total_seconds()
            paso["transcurrido_min"] = _minutos(seg)
            obj = punto.get("minutos_objetivo")
            if obj is not None:
                paso["desvio_min"] = round(seg / 60 - obj)
            actual["pasos"].append(paso)
    if actual:
        cerrar(None)
    return pasos, vueltas


# ══════════════════════════════════════════
#  Entrada principal
# ══════════════════════════════════════════

def _resumen(pos):
    camino = [p for p in pos if not p["dudosa"]]
    vels = [p["vel"] for p in pos if p["vel"] is not None]
    return {
        "posiciones": len(pos),
        "primera": pos[0]["t"] if pos else None,
        "ultima": pos[-1]["t"] if pos else None,
        "km": round(_largo_m(camino) / 1000, 1),
        "vel_max": round(max(vels), 1) if vels else None,
    }


def analizar(posiciones, ruta, cfg, zonas=()):
    """posiciones: [{t (datetime UTC), lat, lon, vel, rumbo, precision}] con fix.
    ruta: Ruta o None (sin ruta solo se evalúan los excesos con los límites por defecto).
    cfg: parámetros del motor de la ruta (ver rutas.CONFIG_POR_DEFECTO)."""
    pos = sorted((dict(p) for p in posiciones), key=lambda p: p["t"])
    # Posiciones repetidas (el equipo reenvía su cola) no aportan nada.
    unicas = []
    for p in pos:
        if not unicas or p["t"] != unicas[-1]["t"]:
            unicas.append(p)
    pos = unicas

    _estados(pos, ruta, cfg)
    zonas_ruta = [z for z in zonas if z.get("ruta_id") in (None, ruta.id if ruta else None)]
    abandonos, inicio_ruta = _abandonos(pos, ruta, cfg, zonas_ruta)
    pasos, vueltas = _pasos_y_vueltas(pos, ruta)
    return {
        "resumen": {**_resumen(pos), "inicio_ruta": inicio_ruta},
        "excesos": _excesos(pos, ruta, cfg),
        "abandonos": abandonos,
        "pasos": pasos,
        "vueltas": vueltas,
    }
