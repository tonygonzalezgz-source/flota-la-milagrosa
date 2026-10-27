"""Terceros del recaudo (Catálogo › Recaudo › Terceros).

Son quienes pagan en la caja por fuera de los buses: el arrendatario de un local,
quien paga servicios, parqueos, lavadas… Es el NIT de los conceptos con tercero
PAGADOR en los pagos diarios y en el archivo plano.

- El dígito de verificación (DV) solo aplica al NIT y lo calcula el servidor con el
  algoritmo de la DIAN; si el usuario lo escribe ("900123456-7") y no coincide, se rechaza.
- Un documento no se repite (la columna NIT del plano lleva solo el número).
- No se borran: se desactivan (los pagos viejos conservan su copia del tercero).
"""
import re

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
    cur = conn.execute(
        """INSERT INTO recaudo_terceros (empresa_id, tipo_documento, documento, dv, nombre, telefono, activo)
           VALUES (?,?,?,?,?,?,?)""",
        (EMPRESA_POR_DEFECTO, t["tipo_documento"], t["documento"], t.get("dv"), t["nombre"],
         t.get("telefono"), t.get("activo", 1)),
    )
    nuevo_id = cur.lastrowid
    auditoria.registrar(
        conn, "recaudo", "tercero", nuevo_id, "crear",
        f"Creó el tercero «{t['nombre']}» ({t['tipo_documento']} {documento_con_dv(t)})",
        {k: t.get(k) for k in _CAMPOS},
    )
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
