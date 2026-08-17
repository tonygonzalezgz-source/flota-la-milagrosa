"""Tool: movilidad_bus(numero, dias?).

Consulta los registros diarios de movilidad de un bus (vueltas, pasajeros,
km recorridos) en los últimos N días. Devuelve totales y detalle por día
con ruta y conductor.
"""
from datetime import date, timedelta

from ai.tools._common import bus_visible


NAME = "movilidad_bus"

DESCRIPTION = (
    "Consulta la movilidad diaria de un bus (vueltas, pasajeros y kilómetros "
    "recorridos) en los últimos N días. Devuelve totales del período y el "
    "detalle por día con ruta y conductor. Úsala cuando el usuario pregunte "
    "por la actividad, vueltas, pasajeros, kilómetros o novedades de un bus "
    "en días recientes."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "numero": {
            "type": "integer",
            "description": "Número interno del bus.",
        },
        "dias": {
            "type": "integer",
            "description": "Cantidad de días hacia atrás desde hoy (default 7, máx 90).",
        },
    },
    "required": ["numero"],
}


def run(args, ctx):
    numero = args.get("numero")
    if numero is None:
        return {"error": "Falta el número interno del bus."}
    try:
        numero = int(numero)
    except (TypeError, ValueError):
        return {"error": f"Número de bus inválido: {numero!r}"}

    try:
        dias = int(args.get("dias") or 7)
    except (TypeError, ValueError):
        dias = 7
    dias = max(1, min(dias, 90))

    hoy = ctx["hoy"]
    try:
        hoy_d = date.fromisoformat(hoy)
    except (TypeError, ValueError):
        hoy_d = date.today()
    desde = (hoy_d - timedelta(days=dias - 1)).isoformat()

    db = ctx["get_db"]()
    try:
        bus = db.execute(
            "SELECT id, numero, placa FROM buses WHERE numero = ?", (numero,)
        ).fetchone()
        if not bus:
            return {
                "encontrado": False,
                "mensaje": f"No existe un bus con número interno {numero}.",
            }
        bus = dict(bus)
        if not bus_visible(db, ctx["user_id"], ctx["rol"], bus["id"]):
            return {
                "acceso": False,
                "mensaje": f"No tienes acceso al bus {numero}.",
            }

        rows = db.execute(
            """
            SELECT rm.fecha, rm.vueltas, rm.pasajeros, rm.km_recorridos,
                   rm.novedades,
                   r.nombre AS ruta, c.nombre AS conductor
            FROM registros_movilidad rm
            LEFT JOIN rutas r       ON r.id = rm.ruta_id
            LEFT JOIN conductores c ON c.id = rm.conductor_id
            WHERE rm.bus_id = ? AND rm.fecha BETWEEN ? AND ?
            ORDER BY rm.fecha DESC
            """,
            (bus["id"], desde, hoy),
        ).fetchall()

        detalle = [dict(r) for r in rows]
        total_vueltas   = sum(int(d["vueltas"] or 0)   for d in detalle)
        total_pasajeros = sum(int(d["pasajeros"] or 0) for d in detalle)
        total_km        = round(sum(float(d["km_recorridos"] or 0) for d in detalle), 2)

        return {
            "encontrado": True,
            "numero": bus["numero"],
            "placa": bus["placa"],
            "periodo": {"desde": desde, "hasta": hoy, "dias": dias},
            "total": {
                "vueltas": total_vueltas,
                "pasajeros": total_pasajeros,
                "km_recorridos": total_km,
                "dias_con_registro": len(detalle),
            },
            "por_dia": detalle,
        }
    except Exception as e:
        return {"error": f"No se pudo consultar la movilidad del bus {numero}: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
