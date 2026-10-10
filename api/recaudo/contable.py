"""Parte contable de la caja: conceptos (cuentas), datos fijos del comprobante y el
ARCHIVO PLANO del día que importa el programa contable de la contadora.

Archivo plano (un comprobante por día, con los cierres de todos los recaudadores):
- Una línea por liquidación con el concepto de uso RECAUDO_VEHICULO ("RECAUDOS CU",
  cuenta 28050504, crédito): NIT = documento del propietario según la tarjeta de
  propiedad del bus, valor = lo recaudado, referencia = número del bus.
- Una línea final con el concepto de uso CIERRE_CAJA ("CIERRE DE CAJA", cuenta 138005,
  débito) por el total, para que el comprobante cuadre.
Los demás conceptos (pagos, abonos, anticipos…) se usarán cuando la caja registre
esos movimientos (siguiente paso).
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

import auditoria

from . import bp
from .comun import EMPRESA_POR_DEFECTO, ROLES_RECAUDO, db, es_pg, rol
from .endpoints import _cargar, _entero, _Rechazo, _texto

ADMIN = ("Administrador",)
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOGOTA = timedelta(hours=5)
TERCEROS = {"PROPIETARIO": "Propietario del vehículo", "PAGADOR": "Pagador",
            "NINGUNO": "Ninguno", "FIJO": "NIT fijo"}
MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")
COLUMNAS_PLANO = ("MONEDA", "TIPO", "NUMERO", "SEQ", "PERIODO", "FECHA", "CUENTA", "CEN COSTO",
                  "SUB CEN", "DESCRIPCION", "SIGNO", "NIT", "DV", "VALOR", "RETENCION", "POSTFE",
                  "FEC-POS", "DCTO REFERENCIA", "PREFIJO", "PRED-DCTO", "NIT CIA")
_CAMPOS = ("nombre", "cuenta", "tercero", "nit_fijo", "signo", "centro_costo", "descripcion",
           "referencia", "activo")
_ETQ = {"nombre": "Concepto", "cuenta": "Cuenta", "tercero": "Tercero (NIT)", "nit_fijo": "NIT fijo",
        "signo": "Signo", "centro_costo": "Centro de costo", "descripcion": "Descripción",
        "referencia": "Referencia", "activo": "Activo"}


def _solo_digitos(v):
    return re.sub(r"\D", "", str(v or ""))


def _conceptos(conn):
    filas = conn.execute(
        "SELECT * FROM recaudo_conceptos WHERE empresa_id = ? ORDER BY orden, nombre",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        d.pop("created_at", None)
        out.append(d)
    return out


def _config(conn):
    filas = conn.execute(
        "SELECT clave, valor FROM recaudo_config WHERE empresa_id = ?", (EMPRESA_POR_DEFECTO,)
    ).fetchall()
    return {dict(f)["clave"]: dict(f)["valor"] for f in filas}


def _validar_concepto(data, actual=None):
    """Valores nuevos del concepto (los que no vienen se conservan)."""
    c = dict(actual or {"tercero": "NINGUNO", "signo": 2, "referencia": "", "activo": 1})
    if "nombre" in data or not actual:
        nombre = " ".join(str(data.get("nombre") or "").split()).upper()[:80]
        if len(nombre) < 3:
            raise _Rechazo("Escribe el nombre del concepto")
        c["nombre"] = nombre
    if "cuenta" in data or not actual:
        cuenta = _solo_digitos(data.get("cuenta"))
        if not 4 <= len(cuenta) <= 12:
            raise _Rechazo("La cuenta contable debe tener entre 4 y 12 dígitos")
        c["cuenta"] = cuenta
    if "tercero" in data:
        if data["tercero"] not in TERCEROS:
            raise _Rechazo("Tercero inválido")
        c["tercero"] = data["tercero"]
    if "nit_fijo" in data:
        c["nit_fijo"] = _solo_digitos(data["nit_fijo"]) or None
    if c["tercero"] == "FIJO" and not c.get("nit_fijo"):
        raise _Rechazo("Escribe el NIT fijo del concepto")
    if c["tercero"] != "FIJO":
        c["nit_fijo"] = None
    if "signo" in data:
        signo = _entero(data["signo"], "El signo")
        if signo not in (1, 2):
            raise _Rechazo("El signo debe ser 1 (débito) o 2 (crédito)")
        c["signo"] = signo
    if "centro_costo" in data:
        c["centro_costo"] = _texto(data["centro_costo"], 20)
    if "descripcion" in data:
        c["descripcion"] = _texto(data["descripcion"], 120)
    if "referencia" in data:
        if data["referencia"] not in ("", "VEHICULO"):
            raise _Rechazo("Referencia inválida")
        c["referencia"] = data["referencia"]
    if "activo" in data:
        c["activo"] = 1 if data["activo"] in (1, True, "1", "true") else 0
    return c


# ──────────────────────────────────────────
#  Conceptos de recaudo (Catálogo)
# ──────────────────────────────────────────

@bp.route("/api/recaudo/conceptos", methods=["GET"])
@rol(*ROLES_RECAUDO)
def listar_conceptos():
    conn = db()
    salida = {"conceptos": _conceptos(conn), "config": _config(conn), "terceros": TERCEROS}
    conn.close()
    return jsonify(salida)


@bp.route("/api/recaudo/conceptos", methods=["POST"])
@rol(*ADMIN)
def crear_concepto():
    data = request.get_json(silent=True) or {}
    conn = db()
    try:
        c = _validar_concepto(data)
        if any(x["nombre"] == c["nombre"] for x in _conceptos(conn)):
            raise _Rechazo(f"Ya existe el concepto «{c['nombre']}»", 409)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    orden = max([x["orden"] for x in _conceptos(conn)] or [0]) + 1
    cur = conn.execute(
        """INSERT INTO recaudo_conceptos
               (empresa_id, nombre, cuenta, tercero, nit_fijo, signo, centro_costo, descripcion,
                referencia, activo, orden)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (EMPRESA_POR_DEFECTO, c["nombre"], c["cuenta"], c["tercero"], c.get("nit_fijo"), c["signo"],
         c.get("centro_costo"), c.get("descripcion"), c.get("referencia", ""), c.get("activo", 1), orden),
    )
    nuevo_id = cur.lastrowid
    auditoria.registrar(
        conn, "recaudo", "concepto", nuevo_id, "crear",
        f"Creó el concepto «{c['nombre']}» (cuenta {c['cuenta']}, {'débito' if c['signo'] == 1 else 'crédito'})",
        {k: c.get(k) for k in _CAMPOS},
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": nuevo_id}), 201


@bp.route("/api/recaudo/conceptos/<int:concepto_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_concepto(concepto_id):
    data = request.get_json(silent=True) or {}
    conn = db()
    actual = next((x for x in _conceptos(conn) if x["id"] == concepto_id), None)
    if not actual:
        conn.close()
        return jsonify({"error": "Concepto no encontrado"}), 404
    try:
        c = _validar_concepto(data, actual)
        if c["nombre"] != actual["nombre"] and any(x["nombre"] == c["nombre"] for x in _conceptos(conn)):
            raise _Rechazo(f"Ya existe el concepto «{c['nombre']}»", 409)
        if actual.get("uso") and not c["activo"]:
            raise _Rechazo("Este concepto lo usa el archivo plano del cierre: no se puede desactivar")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    cambios = auditoria.diferencias(actual, c, _CAMPOS)
    if cambios:
        conn.execute(
            """UPDATE recaudo_conceptos SET nombre = ?, cuenta = ?, tercero = ?, nit_fijo = ?, signo = ?,
                      centro_costo = ?, descripcion = ?, referencia = ?, activo = ?
                WHERE id = ?""",
            (c["nombre"], c["cuenta"], c["tercero"], c.get("nit_fijo"), c["signo"], c.get("centro_costo"),
             c.get("descripcion"), c.get("referencia", ""), c["activo"], concepto_id),
        )
        if set(cambios) == {"activo"}:
            accion = "activar" if c["activo"] else "desactivar"
            texto = f"{'Activó' if c['activo'] else 'Desactivó'} el concepto «{actual['nombre']}»"
        else:
            accion = "editar"
            texto = f"Editó el concepto «{actual['nombre']}»: {auditoria.describir(cambios, _ETQ)}"
        auditoria.registrar(conn, "recaudo", "concepto", concepto_id, accion, texto, cambios)
        conn.commit()
    conn.close()
    return jsonify({"ok": True})


@bp.route("/api/recaudo/config-contable", methods=["PUT"])
@rol(*ADMIN)
def editar_config_contable():
    """Body: {nit_compania?, tipo_comprobante?, moneda?}."""
    data = request.get_json(silent=True) or {}
    nuevos = {}
    if "nit_compania" in data:
        nuevos["nit_compania"] = _solo_digitos(data["nit_compania"])
    if "tipo_comprobante" in data:
        nuevos["tipo_comprobante"] = re.sub(r"[^A-Za-z0-9]", "", str(data["tipo_comprobante"] or "")).upper()[:6]
    if "moneda" in data:
        nuevos["moneda"] = _solo_digitos(data["moneda"])[:3]
    if any(not v for v in nuevos.values()):
        return jsonify({"error": "Los datos contables no pueden quedar vacíos"}), 400
    conn = db()
    actual = _config(conn)
    cambios = {k: [actual.get(k), v] for k, v in nuevos.items() if actual.get(k) != v}
    for k, v in nuevos.items():
        conn.execute(
            """INSERT INTO recaudo_config (empresa_id, clave, valor) VALUES (?,?,?)
               ON CONFLICT(empresa_id, clave) DO UPDATE SET valor = excluded.valor""",
            (EMPRESA_POR_DEFECTO, k, v),
        )
    if cambios:
        auditoria.registrar(
            conn, "recaudo", "config_contable", None, "editar",
            "Editó los datos contables del archivo plano: " + auditoria.describir(
                cambios, {"nit_compania": "NIT de la compañía", "tipo_comprobante": "Tipo de comprobante",
                          "moneda": "Moneda"}),
            cambios,
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Archivo plano del día (comprobante contable)
# ──────────────────────────────────────────

def _limite_utc(fecha_iso, dias_extra=0):
    d = date.fromisoformat(fecha_iso) + timedelta(days=dias_extra)
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + _BOGOTA
    return dt if es_pg() else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _nit(concepto, documento_propietario=None):
    if concepto["tercero"] == "FIJO":
        return concepto.get("nit_fijo") or ""
    if concepto["tercero"] == "PROPIETARIO":
        return _solo_digitos(documento_propietario)
    return ""


@bp.route("/api/recaudo/plano", methods=["GET"])
@rol(*ADMIN)
def archivo_plano():
    """?fecha=AAAA-MM-DD (día del cierre, hora Bogotá). Junta los cierres de ese día
    (no reabiertos) de todos los recaudadores en un solo comprobante."""
    fecha = request.args.get("fecha") or ""
    if not _RE_FECHA.match(fecha):
        return jsonify({"error": "Fecha inválida (use AAAA-MM-DD)"}), 400
    conn = db()
    cierres = [dict(f) for f in conn.execute(
        """SELECT id, usuario_nombre, liquidacion_ids, recaudado FROM recaudo_cierres
            WHERE cerrado_at >= ? AND cerrado_at < ? AND reabierto_at IS NULL ORDER BY id""",
        (_limite_utc(fecha), _limite_utc(fecha, 1)),
    ).fetchall()]
    conceptos = _conceptos(conn)
    config = _config(conn)
    c_recaudo = next((c for c in conceptos if c.get("uso") == "RECAUDO_VEHICULO"), None)
    c_cierre = next((c for c in conceptos if c.get("uso") == "CIERRE_CAJA"), None)
    if not c_recaudo or not c_cierre:
        conn.close()
        return jsonify({"error": "Faltan los conceptos RECAUDOS CU o CIERRE DE CAJA en el catálogo"}), 409

    ids = [i for c in cierres for i in json.loads(c["liquidacion_ids"] or "[]")]
    liqs = _cargar(conn, f"r.id IN ({','.join('?' * len(ids))})", ids) if ids else []
    bus_ids = sorted({l["bus_id"] for l in liqs})
    propietarios = {}
    if bus_ids:
        for f in conn.execute(
            f"""SELECT id, numero, tp_propietario_nombre, tp_propietario_documento FROM buses
                 WHERE id IN ({','.join('?' * len(bus_ids))})""", bus_ids,
        ).fetchall():
            f = dict(f)
            propietarios[f["id"]] = f
    conn.close()

    d = date.fromisoformat(fecha)
    mes = MESES[d.month - 1]
    numero = d.strftime("%Y%m%d")
    base = {"MONEDA": config.get("moneda", "1"), "TIPO": config.get("tipo_comprobante", "CU"),
            "NUMERO": numero, "PERIODO": d.month, "FECHA": numero,
            "NIT CIA": config.get("nit_compania", "")}

    def linea(seq, concepto, descripcion, nit, valor, referencia=""):
        fila = {col: "" for col in COLUMNAS_PLANO}
        fila.update(base)
        fila.update({"SEQ": seq, "CUENTA": concepto["cuenta"], "CEN COSTO": concepto.get("centro_costo") or "",
                     "DESCRIPCION": descripcion, "SIGNO": concepto["signo"], "NIT": nit, "VALOR": valor,
                     "DCTO REFERENCIA": referencia})
        return [fila[col] for col in COLUMNAS_PLANO]

    filas, avisos, total = [], [], 0
    for l in sorted(liqs, key=lambda x: (x["bus_numero"], x["fecha"], x["id"])):
        prop = propietarios.get(l["bus_id"], {})
        nit = _nit(c_recaudo, prop.get("tp_propietario_documento"))
        if c_recaudo["tercero"] == "PROPIETARIO" and not nit:
            avisos.append(f"El bus {l['bus_numero']} no tiene el documento del propietario (tarjeta de propiedad)")
        dia = date.fromisoformat(l["fecha"]).strftime("%d%m%Y")
        filas.append(linea(len(filas) + 1, c_recaudo, f"{c_recaudo['nombre']} {mes} VEH{l['bus_numero']} T{dia}",
                           nit, l["recaudado"], l["bus_numero"] if c_recaudo.get("referencia") == "VEHICULO" else ""))
        total += l["recaudado"]
    if filas:
        filas.append(linea(len(filas) + 1, c_cierre, f"{c_recaudo['nombre']} {mes} {d.day}", _nit(c_cierre), total))

    return jsonify({
        "fecha": fecha, "numero": numero, "columnas": COLUMNAS_PLANO, "filas": filas, "total": total,
        "cierres": [{"id": c["id"], "recaudador": c["usuario_nombre"], "recaudado": c["recaudado"]} for c in cierres],
        "avisos": sorted(set(avisos)),
    })
