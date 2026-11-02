"""Terceros del recaudo (Catálogo › Recaudo › Terceros).

Son quienes pagan en la caja por fuera de los buses: el arrendatario de un local,
quien paga servicios, parqueos, lavadas… Es el NIT de los conceptos con tercero
PAGADOR en los pagos diarios y en el archivo plano.

- El dígito de verificación (DV) solo aplica al NIT y lo calcula el servidor con el
  algoritmo de la DIAN; si el usuario lo escribe ("900123456-7") y no coincide, se rechaza.
- Un documento no se repite (la columna NIT del plano lleva solo el número).
- No se borran: se desactivan (los pagos viejos conservan su copia del tercero).
- En "Quién paga" también salen los conductores y los propietarios de los buses (los
  de la tarjeta de propiedad), para no volver a digitarlos: el que se elija y aún no
  sea tercero se crea al registrar el pago (pedido del usuario 2026-11-02).
"""
import re
import unicodedata

from flask import jsonify, request

import auditoria

from . import bp
from .comun import EMPRESA_POR_DEFECTO, ROLES_RECAUDO, db, rol
from .endpoints import _Rechazo

ADMIN = ("Administrador",)
TIPOS_DOCUMENTO = {
    "NIT": "NIT",
    "CC": "Cédula de ciudadanía",
    "CE": "Cédula de extranjería",
    "TI": "Tarjeta de identidad",
    "PA": "Pasaporte",
    "PPT": "Permiso por protección temporal",
}
_SOLO_NUMEROS = ("NIT", "CC", "TI")
_PESOS_DV = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
_CAMPOS = ("nombre", "tipo_documento", "documento", "dv", "telefono", "activo")
_ETQ = {"nombre": "Nombre", "tipo_documento": "Tipo de documento", "documento": "Documento",
        "dv": "DV", "telefono": "Teléfono", "activo": "Activo"}


def digito_verificacion(nit):
    """Dígito de verificación de un NIT (algoritmo de la DIAN, módulo 11)."""
    digitos = re.sub(r"\D", "", str(nit or ""))
    suma = sum(int(d) * _PESOS_DV[i] for i, d in enumerate(reversed(digitos)))
    resto = suma % 11
    return str(resto if resto < 2 else 11 - resto)


def documento_con_dv(t):
    """'900123456-7' para NIT; el número solo para los demás."""
    if not t or not t.get("documento"):
        return ""
    return f"{t['documento']}-{t['dv']}" if t.get("dv") else t["documento"]


def _fila(r):
    d = dict(r)
    d.pop("created_at", None)
    return d


def listar(conn, solo_activos=False):
    filtro = " AND activo = 1" if solo_activos else ""
    return [_fila(r) for r in conn.execute(
        f"SELECT * FROM recaudo_terceros WHERE empresa_id = ?{filtro} ORDER BY nombre",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()]


def buscar(conn, tercero_id):
    fila = conn.execute("SELECT * FROM recaudo_terceros WHERE id = ? AND empresa_id = ?",
                        (tercero_id, EMPRESA_POR_DEFECTO)).fetchone()
    return _fila(fila) if fila else None


def _validar(data, actual=None):
    """Valores nuevos del tercero (los que no vienen se conservan). El DV no se recibe:
    se calcula."""
    t = dict(actual or {"activo": 1})
    if "nombre" in data or not actual:
        nombre = " ".join(str(data.get("nombre") or "").split()).upper()[:120]
        if len(nombre) < 3:
            raise _Rechazo("Escribe el nombre o la razón social del tercero")
        t["nombre"] = nombre
    if "tipo_documento" in data or not actual:
        tipo = str(data.get("tipo_documento") or "").upper()
        if tipo not in TIPOS_DOCUMENTO:
            raise _Rechazo("Elige el tipo de documento")
        t["tipo_documento"] = tipo
    if "documento" in data or "tipo_documento" in data or not actual:
        crudo = str(data.get("documento", t.get("documento")) or "").strip()
        dv_escrito = None
        if t["tipo_documento"] == "NIT" and "-" in crudo:
            crudo, dv_escrito = crudo.rsplit("-", 1)
            dv_escrito = re.sub(r"\D", "", dv_escrito)
        if t["tipo_documento"] in _SOLO_NUMEROS:
            documento = re.sub(r"[\s.,]", "", crudo)
            if not documento.isdigit() or not 5 <= len(documento) <= 15:
                raise _Rechazo("El número de documento debe tener entre 5 y 15 dígitos")
        else:
            documento = re.sub(r"[^A-Za-z0-9]", "", crudo).upper()
            if not 3 <= len(documento) <= 20:
                raise _Rechazo("El número de documento debe tener entre 3 y 20 letras o números")
        t["documento"] = documento
        t["dv"] = digito_verificacion(documento) if t["tipo_documento"] == "NIT" else None
        if dv_escrito and dv_escrito != t["dv"]:
            raise _Rechazo(f"El dígito de verificación no corresponde: para el NIT {documento} es {t['dv']}")
    if "telefono" in data:
        tel = re.sub(r"\D", "", str(data.get("telefono") or ""))
        if tel and not 7 <= len(tel) <= 15:
            raise _Rechazo("El teléfono debe tener entre 7 y 15 dígitos")
        t["telefono"] = tel or None
    if "activo" in data:
        t["activo"] = 1 if data["activo"] in (1, True, "1", "true") else 0
    return t


def _repetido(conn, documento, excluir_id=0):
    fila = conn.execute(
        "SELECT nombre FROM recaudo_terceros WHERE empresa_id = ? AND documento = ? AND id <> ?",
        (EMPRESA_POR_DEFECTO, documento, excluir_id),
    ).fetchone()
    return dict(fila)["nombre"] if fila else None


def _insertar(conn, t, desde=""):
    """Crea el tercero ya validado y lo deja en la auditoría. Devuelve su id (sin commit)."""
    cur = conn.execute(
        """INSERT INTO recaudo_terceros (empresa_id, tipo_documento, documento, dv, nombre, telefono, activo)
           VALUES (?,?,?,?,?,?,?)""",
        (EMPRESA_POR_DEFECTO, t["tipo_documento"], t["documento"], t.get("dv"), t["nombre"],
         t.get("telefono"), t.get("activo", 1)),
    )
    nuevo_id = cur.lastrowid
    auditoria.registrar(
        conn, "recaudo", "tercero", nuevo_id, "crear",
        f"Creó el tercero «{t['nombre']}» ({t['tipo_documento']} {documento_con_dv(t)}){desde}",
        {k: t.get(k) for k in _CAMPOS},
    )
    return nuevo_id


# ──────────────────────────────────────────
#  Quién paga: terceros + conductores + propietarios de los buses
# ──────────────────────────────────────────

def _documento_catalogo(crudo, puede_ser_nit=False):
    """(tipo, número) de un documento de los catálogos de la flota, que no guardan el
    tipo; (None, None) si no hay uno válido. Con letras es de extranjería. Un propietario
    puede ser empresa: 9 dígitos que empiezan por 8 o 9 son NIT (con el DV pegado, 10)."""
    texto = re.sub(r"[\s.,]", "", str(crudo or "")).upper()
    if not texto:
        return None, None
    if not re.fullmatch(r"[\d-]+", texto):
        doc = re.sub(r"[^A-Z0-9]", "", texto)
        return ("CE", doc) if 3 <= len(doc) <= 20 else (None, None)
    doc = texto.replace("-", "")
    if puede_ser_nit and doc[:1] in ("8", "9"):
        if len(doc) == 9:
            return "NIT", doc
        if len(doc) == 10 and digito_verificacion(doc[:9]) == doc[9]:
            return "NIT", doc[:9]
    return ("CC", doc) if 5 <= len(doc) <= 15 else (None, None)


def _personas_flota(conn):
    """(clave, origen, nombre, documento crudo, bus) de conductores activos, propietarios
    con cédula y dueños según la tarjeta de propiedad de cada bus. La clave dice de dónde
    sale: 'c12' conductor, 'p3' propietario, 'm7' tarjeta de propiedad del bus id 7."""
    for r in conn.execute("SELECT id, nombre, cedula FROM conductores WHERE activo = 1").fetchall():
        r = dict(r)
        yield f"c{r['id']}", "conductor", r["nombre"], r.get("cedula"), None
    for r in conn.execute(
        """SELECT id, numero, tp_propietario_nombre, tp_propietario_documento FROM buses
            WHERE COALESCE(tp_propietario_nombre, '') <> '' OR COALESCE(tp_propietario_documento, '') <> ''
         ORDER BY numero"""
    ).fetchall():
        r = dict(r)
        yield f"m{r['id']}", "propietario", r["tp_propietario_nombre"], r["tp_propietario_documento"], r["numero"]
    for r in conn.execute(
        "SELECT id, nombre, cedula FROM propietarios WHERE activo = 1 AND COALESCE(cedula, '') <> ''"
    ).fetchall():
        r = dict(r)
        yield f"p{r['id']}", "propietario", r["nombre"], r["cedula"], None


def pagadores(conn):
    """Lista única para "Quién paga": terceros activos y las personas de la flota. Un
    mismo documento sale una vez (manda el tercero, que ya tiene su tipo y DV) y se
    busca por todos sus nombres. Los que no tienen documento también salen, para que
    el recaudador sepa que existen y qué falta completar."""
    lista, por_doc = [], {}
    for t in listar(conn, solo_activos=True):
        x = {"clave": f"t{t['id']}", "nombre": t["nombre"], "nombres": [t["nombre"]],
             "tipo_documento": t["tipo_documento"], "documento": t["documento"], "dv": t.get("dv"),
             "origenes": ["tercero"], "buses": []}
        lista.append(x)
        por_doc[t["documento"]] = x
    for clave, origen, nombre, crudo, bus in _personas_flota(conn):
        nombre = " ".join(str(nombre or "").split()).upper()
        tipo, doc = _documento_catalogo(crudo, puede_ser_nit=origen == "propietario")
        if not nombre and not doc:
            continue
        llave = doc or f"sin:{origen}:{nombre}"
        x = por_doc.get(llave)
        if not x:
            x = {"clave": clave, "nombre": nombre, "nombres": [], "tipo_documento": tipo, "documento": doc,
                 "dv": digito_verificacion(doc) if tipo == "NIT" else None, "origenes": [], "buses": []}
            lista.append(x)
            por_doc[llave] = x
        if nombre and nombre not in x["nombres"]:
            x["nombres"].append(nombre)
        if not x["nombre"]:
            x["nombre"] = nombre
        if origen not in x["origenes"]:
            x["origenes"].append(origen)
        if bus is not None and bus not in x["buses"]:
            x["buses"].append(bus)
    for x in lista:
        x["nombre"] = x["nombre"] or f"(SIN NOMBRE) {x['documento']}"
    # Sin tildes para ordenar: "ÁLVARO" va con la A, no después de la Z
    return sorted(lista, key=lambda x: unicodedata.normalize("NFD", x["nombre"]).encode("ascii", "ignore"))


def tercero_de_pagador(conn, clave):
    """El tercero para la clave elegida en "Quién paga" (ver `pagadores`). Si es una
    persona de la flota, se busca en Terceros por su documento y, si no está, se crea.
    El nombre y el documento salen siempre del catálogo, nunca de la petición."""
    m = re.fullmatch(r"([tcpm])(\d+)", str(clave or ""))
    if not m:
        raise _Rechazo("Quién paga no es válido: vuelve a elegirlo de la lista")
    origen, rid = m.group(1), int(m.group(2))
    if origen == "t":
        t = buscar(conn, rid)
        if not t or not t.get("activo"):
            raise _Rechazo("El tercero no existe o está inactivo")
        return t

    if origen == "m":
        fila = conn.execute(
            "SELECT numero, tp_propietario_nombre, tp_propietario_documento FROM buses WHERE id = ?", (rid,)
        ).fetchone()
        if not fila:
            raise _Rechazo("El vehículo no existe", 404)
        fila = dict(fila)
        nombre, crudo = fila["tp_propietario_nombre"], fila["tp_propietario_documento"]
        desde = f" desde la tarjeta de propiedad del vehículo {fila['numero']}"
        falta = (f"El vehículo {fila['numero']} no tiene el documento del propietario (tarjeta de "
                 "propiedad). Complétalo en Catálogo › Buses o créalo con «+ Nuevo tercero».")
        if len(" ".join(str(nombre or "").split())) < 3:
            raise _Rechazo(f"El vehículo {fila['numero']} no tiene el nombre del propietario (tarjeta "
                           "de propiedad). Complétalo en Catálogo › Buses o créalo con «+ Nuevo tercero».")
    else:
        tabla, cual, donde = (("conductores", "conductor", "Conductores") if origen == "c"
                              else ("propietarios", "propietario", "Propietarios"))
        fila = conn.execute(f"SELECT nombre, cedula FROM {tabla} WHERE id = ? AND activo = 1", (rid,)).fetchone()
        if not fila:
            raise _Rechazo(f"El {cual} no existe o está inactivo", 404)
        fila = dict(fila)
        nombre, crudo = fila["nombre"], fila["cedula"]
        desde = f" desde Catálogo › {donde}"
        falta = (f"El {cual} {nombre} no tiene la cédula en el catálogo. "
                 "Complétala allá o créalo con «+ Nuevo tercero».")

    tipo, doc = _documento_catalogo(crudo, puede_ser_nit=origen != "c")
    if not doc:
        raise _Rechazo(falta)
    existente = conn.execute(
        "SELECT * FROM recaudo_terceros WHERE empresa_id = ? AND documento = ?", (EMPRESA_POR_DEFECTO, doc)
    ).fetchone()
    if existente:
        t = _fila(existente)
        if not t.get("activo"):
            raise _Rechazo(f"El tercero «{t['nombre']}» con el documento {doc} está inactivo. "
                           "Actívalo en Catálogo › Recaudo › Terceros.")
        return t
    t = _validar({"nombre": nombre, "tipo_documento": tipo, "documento": doc})
    nuevo_id = _insertar(conn, t, desde + " al registrar un pago")
    return buscar(conn, nuevo_id)


@bp.route("/api/recaudo/terceros", methods=["GET"])
@rol(*ROLES_RECAUDO)
def listar_terceros():
    conn = db()
    salida = {"terceros": listar(conn), "tipos_documento": TIPOS_DOCUMENTO}
    conn.close()
    return jsonify(salida)


@bp.route("/api/recaudo/terceros", methods=["POST"])
@rol(*ROLES_RECAUDO)
def crear_tercero():
    """También desde Pagos diarios ("+ Nuevo tercero"), para no salir del formulario."""
    data = request.get_json(silent=True) or {}
    conn = db()
    try:
        t = _validar(data)
        otro = _repetido(conn, t["documento"])
        if otro:
            raise _Rechazo(f"Ya existe el tercero «{otro}» con ese documento", 409)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    nuevo_id = _insertar(conn, t)
    conn.commit()
    tercero = buscar(conn, nuevo_id)
    conn.close()
    return jsonify({"ok": True, "id": nuevo_id, "tercero": tercero}), 201


@bp.route("/api/recaudo/terceros/<int:tercero_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_tercero(tercero_id):
    data = request.get_json(silent=True) or {}
    conn = db()
    actual = buscar(conn, tercero_id)
    if not actual:
        conn.close()
        return jsonify({"error": "Tercero no encontrado"}), 404
    try:
        t = _validar(data, actual)
        otro = _repetido(conn, t["documento"], tercero_id)
        if otro:
            raise _Rechazo(f"Ya existe el tercero «{otro}» con ese documento", 409)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    cambios = auditoria.diferencias(actual, t, _CAMPOS)
    if cambios:
        conn.execute(
            """UPDATE recaudo_terceros SET tipo_documento = ?, documento = ?, dv = ?, nombre = ?,
                      telefono = ?, activo = ?
                WHERE id = ?""",
            (t["tipo_documento"], t["documento"], t.get("dv"), t["nombre"], t.get("telefono"),
             t["activo"], tercero_id),
        )
        if set(cambios) == {"activo"}:
            accion = "activar" if t["activo"] else "desactivar"
            texto = f"{'Activó' if t['activo'] else 'Desactivó'} el tercero «{actual['nombre']}»"
        else:
            accion = "editar"
            texto = f"Editó el tercero «{actual['nombre']}»: {auditoria.describir(cambios, _ETQ)}"
        auditoria.registrar(conn, "recaudo", "tercero", tercero_id, accion, texto, cambios)
        conn.commit()
    tercero = buscar(conn, tercero_id)
    conn.close()
    return jsonify({"ok": True, "tercero": tercero})
