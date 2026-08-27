"""Tool: chequeos_despachadores(desde?, hasta?, dias?, despachador?).

Historial de chequeos (llegada/salida en puestos de trabajo) de los
despachadores en un rango de fechas. Sirve para preguntas del tipo
'¿quién trabajó y en qué puesto la semana pasada?' o
'¿cuántos días trabajó Fulano este mes?'.

Solo Administrador y Jefe de Ruta ven todos los chequeos (mismo criterio
que `/api/chequeo/historial`). Otros roles reciben `acceso: false`.
"""
from datetime import date, timedelta

from ai.tools._common import _parse_fecha


NAME = "chequeos_despachadores"

DESCRIPTION = (
    "Historial de chequeos GPS de los despachadores en un rango de fechas: "
    "qué días trabajó cada uno, en qué puesto, a qué hora llegó y salió y "
    "cuántos minutos trabajó. Úsala para preguntas como '¿quién trabajó la "
    "semana pasada?', '¿en qué puesto estuvo Fulano ayer?' o '¿cuántos días "
    "trabajó Perez este mes?'. Puedes filtrar por rango de fechas o por "
    "nombre/apellido del despachador. Solo está disponible para "
    "Administrador y Jefe de Ruta."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "desde": {
            "type": "string",
            "description": (
                "Fecha inicial del rango en formato YYYY-MM-DD. Si se omite "
                "junto con `hasta`, se usan los últimos `dias` días (default 7)."
            ),
        },
        "hasta": {
            "type": "string",
            "description": (
                "Fecha final del rango en formato YYYY-MM-DD (inclusive). "
                "Si se omite, se usa la fecha de hoy."
            ),
        },
        "dias": {
            "type": "integer",
            "description": (
                "Cantidad de días hacia atrás desde hoy (usado solo cuando no "
                "se pasan `desde` ni `hasta`). Default 7. Para 'la semana "
                "pasada' o 'esta semana' usa 7, para 'este mes' usa 30."
            ),
        },
        "despachador": {
            "type": "string",
            "description": (
                "Filtro opcional por nombre o apellido del despachador "
                "(coincidencia parcial). Si se omite, devuelve todos."
            ),
        },
    },
    "required": [],
}


ROLES_PERMITIDOS = ("Administrador", "Jefe de Ruta")


def _rango(args, hoy_str):
    """Resuelve (desde, hasta) como strings YYYY-MM-DD.

    Prioriza los parámetros explícitos y respeta un rango parcial (solo
    `desde` o solo `hasta`); si ninguno viene, retrocede `dias` días
    (default 7) desde hoy.
    """
    hoy = _parse_fecha(hoy_str) or date.today()
    desde = _parse_fecha(args.get("desde"))
    hasta = _parse_fecha(args.get("hasta"))
    if not desde and not hasta:
        try:
            dias = int(args.get("dias") or 7)
        except (TypeError, ValueError):
            dias = 7
        dias = max(1, min(dias, 120))
        desde = hoy - timedelta(days=dias - 1)
        hasta = hoy
    else:
        desde = desde or (hasta - timedelta(days=6))
        hasta = hasta or hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde.isoformat(), hasta.isoformat()


def run(args, ctx):
    rol = ctx["rol"]
    if rol not in ROLES_PERMITIDOS:
        return {
            "acceso": False,
            "mensaje": (
                "Solo Administrador o Jefe de Ruta pueden consultar el "
                "historial de chequeos de los despachadores."
            ),
        }

    desde, hasta = _rango(args, ctx["hoy"])
    filtro_extra = ""
    params = [desde, hasta]
    despachador = (args.get("despachador") or "").strip()
    if despachador:
        filtro_extra = " AND (u.nombre LIKE ? OR u.username LIKE ?)"
        like = f"%{despachador}%"
        params += [like, like]

    db = ctx["get_db"]()
    try:
        rows = db.execute(
            f"""
            SELECT c.fecha, c.hora_llegada, c.hora_salida, c.minutos_trabajados,
                   u.nombre AS despachador, u.username,
                   p.nombre AS puesto
            FROM chequeos_despachador c
            JOIN usuarios u ON u.id = c.usuario_id
            LEFT JOIN puestos_trabajo p ON p.id = c.puesto_id
            WHERE c.fecha BETWEEN ? AND ?{filtro_extra}
            ORDER BY c.fecha DESC, c.hora_llegada
            """,
            params,
        ).fetchall()

        chequeos = []
        # Resumen por despachador: días trabajados y total de minutos.
        por_persona = {}
        for r in rows:
            d = dict(r)
            fecha = d["fecha"]
            if hasattr(fecha, "isoformat"):
                fecha = fecha.isoformat()
            estado = "cerrado" if d["hora_salida"] else "en_turno"
            item = {
                "fecha": fecha,
                "despachador": d["despachador"],
                "puesto": d["puesto"],
                "hora_llegada": d["hora_llegada"][:5] if d["hora_llegada"] else None,
                "hora_salida": d["hora_salida"][:5] if d["hora_salida"] else None,
                "minutos_trabajados": d["minutos_trabajados"],
                "estado": estado,
            }
            chequeos.append(item)
            resumen = por_persona.setdefault(d["despachador"], {
                "despachador": d["despachador"],
                "dias_trabajados": 0,
                "minutos_totales": 0,
                "puestos": set(),
            })
            resumen["dias_trabajados"] += 1
            resumen["minutos_totales"] += int(d["minutos_trabajados"] or 0)
            if d["puesto"]:
                resumen["puestos"].add(d["puesto"])

        resumen_lista = []
        for r in por_persona.values():
            r["puestos"] = sorted(r["puestos"])
            r["horas_totales"] = round(r["minutos_totales"] / 60, 1)
            resumen_lista.append(r)
        resumen_lista.sort(key=lambda x: (-x["dias_trabajados"], x["despachador"]))

        return {
            "desde": desde,
            "hasta": hasta,
            "filtro_despachador": despachador or None,
            "total_chequeos": len(chequeos),
            "resumen_por_despachador": resumen_lista,
            "chequeos": chequeos,
        }
    except Exception as e:
        return {"error": f"No se pudo consultar el historial de chequeos: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
