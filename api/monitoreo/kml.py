"""Lectura y escritura de KML/KMZ (Google Earth) para las rutas geográficas.

Solo biblioteca estándar: zipfile + ElementTree. El archivo lo sube un
administrador, pero igual se acota el tamaño y se rechazan DTD/entidades
(evita ataques de expansión de entidades en XML).
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

MAX_BYTES = 8 * 1024 * 1024

_RE_IDA = re.compile(r"\bIDA\b", re.I)
_RE_REGRESO = re.compile(r"\b(REGRESO|VUELTA|RETORNO)\b", re.I)


class KmlError(ValueError):
    pass


def _xml_de_archivo(datos):
    if len(datos) > MAX_BYTES:
        raise KmlError("El archivo supera 8 MB.")
    if zipfile.is_zipfile(io.BytesIO(datos)):
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kmls:
                raise KmlError("El KMZ no contiene ningún archivo .kml.")
            # Google Earth guarda el principal como doc.kml en la raíz.
            kmls.sort(key=lambda n: (n.lower() != "doc.kml", n.count("/"), n))
            info = z.getinfo(kmls[0])
            if info.file_size > MAX_BYTES:
                raise KmlError("El KML dentro del KMZ es demasiado grande.")
            datos = z.read(info)
    texto = datos.decode("utf-8", "replace")
    if "<!DOCTYPE" in texto or "<!ENTITY" in texto:
        raise KmlError("El archivo trae declaraciones XML no permitidas.")
    return texto


def _tag(el):
    return el.tag.rsplit("}", 1)[-1]


def _hijo(el, nombre):
    for h in el:
        if _tag(h) == nombre:
            return h
    return None


def _coords(texto):
    """'lon,lat[,alt] lon,lat …' → [[lat, lon], …]"""
    puntos = []
    for tupla in (texto or "").split():
        partes = tupla.split(",")
        if len(partes) < 2:
            continue
        try:
            lon, lat = float(partes[0]), float(partes[1])
        except ValueError:
            continue
        if abs(lat) <= 90 and abs(lon) <= 180:
            puntos.append([round(lat, 7), round(lon, 7)])
    return puntos


def sugerir_sentido(nombre):
    if _RE_REGRESO.search(nombre or ""):
        return "regreso"
    if _RE_IDA.search(nombre or ""):
        return "ida"
    return None


def leer(datos):
    """Bytes de un .kml o .kmz → {nombre, lineas:[{nombre, puntos}], puntos:[{nombre, lat, lon}]}"""
    try:
        raiz = ET.fromstring(_xml_de_archivo(datos))
    except ET.ParseError as e:
        raise KmlError(f"El archivo no es un KML válido ({e}).")

    nombre_ruta = None
    for el in raiz.iter():
        if _tag(el) in ("Folder", "Document"):
            n = _hijo(el, "name")
            if n is not None and (n.text or "").strip():
                nombre_ruta = n.text.strip()
                if _tag(el) == "Folder":
                    break

    lineas, puntos = [], []
    for pm in raiz.iter():
        if _tag(pm) != "Placemark":
            continue
        n = _hijo(pm, "name")
        nombre = (n.text or "").strip() if n is not None else ""
        for geom in pm.iter():
            t = _tag(geom)
            if t == "LineString":
                c = _hijo(geom, "coordinates")
                pts = _coords(c.text if c is not None else "")
                if len(pts) >= 2:
                    lineas.append({"nombre": nombre or f"Línea {len(lineas) + 1}", "puntos": pts})
            elif t == "Point":
                c = _hijo(geom, "coordinates")
                pts = _coords(c.text if c is not None else "")
                if pts:
                    puntos.append({"nombre": nombre or f"Punto {len(puntos) + 1}",
                                   "lat": pts[0][0], "lon": pts[0][1]})
    if not lineas:
        raise KmlError("El archivo no trae ningún trazado (LineString).")
    return {"nombre": nombre_ruta, "lineas": lineas, "puntos": puntos}


def escribir(nombre_ruta, trazados, puntos):
    """Genera un KML con la misma estructura que se importa: un Folder con las
    líneas de ida/regreso y un Placemark por punto de control."""
    def coords(pts):
        return " ".join(f"{p[1]},{p[0]},0" for p in pts)

    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f"<name>{escape(nombre_ruta)}</name>",
        '<Style id="ida"><LineStyle><color>ffe16a2f</color><width>4</width></LineStyle></Style>',
        '<Style id="regreso"><LineStyle><color>ff2f8ae1</color><width>4</width></LineStyle></Style>',
        f"<Folder><name>{escape(nombre_ruta)}</name>",
    ]
    for sentido in ("ida", "regreso"):
        t = trazados.get(sentido)
        if t:
            partes.append(
                f"<Placemark><name>{escape(nombre_ruta)} {sentido.upper()}</name>"
                f"<styleUrl>#{sentido}</styleUrl><LineString><tessellate>1</tessellate>"
                f"<coordinates>{coords(t)}</coordinates></LineString></Placemark>"
            )
    for p in puntos:
        partes.append(
            f"<Placemark><name>{escape(p['nombre'])}</name>"
            f"<description>Radio {int(p['radio_m'])} m</description>"
            f"<Point><coordinates>{p['lon']},{p['lat']},0</coordinates></Point></Placemark>"
        )
    partes.append("</Folder></Document></kml>")
    return "\n".join(partes)
