"""Tool: vencimientos_bus(numero).

Devuelve las fechas de vencimiento de SOAT, tecnomecánica y tarjeta de
operación de un bus, con los días restantes calculados y una etiqueta
legible (vigente / por_vencer / vencido / sin_fecha).
"""
from ai.tools._common import bus_visible, doc_info

NAME = "vencimientos_bus"

DESCRIPTION = (
    "Consulta las fechas de vencimiento del SOAT, tecnomecánica y tarjeta de "
    "operación de un bus por su número interno, calcula cuántos días faltan "
    "(o cuántos lleva vencido) y clasifica cada documento como vigente, "
    "por_vencer (≤30 días) o vencido. Úsala cuando el usuario pregunte "
    "cuándo vence el SOAT, la tecno mecánica, la tarjeta de operación o los "
    "documentos de un bus concreto."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "numero": {
            "type": "integer",
            "description": "Número interno del bus (p. ej. 5, 12, 103).",
        }
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

    db = ctx["get_db"]()
    try:
        bus = db.execute(
            "SELECT id, numero, placa, soat_vencimiento, tecno_vencimiento, "
            "tarjeta_op_vencimiento FROM buses WHERE numero = ?",
            (numero,),
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

        hoy = ctx["hoy"]
        return {
            "encontrado": True,
            "numero": bus["numero"],
            "placa": bus["placa"],
            "hoy": hoy,
            "soat": doc_info(bus["soat_vencimiento"], hoy),
            "tecnomecanica": doc_info(bus["tecno_vencimiento"], hoy),
            "tarjeta_operacion": doc_info(bus["tarjeta_op_vencimiento"], hoy),
        }
    except Exception as e:
        return {"error": f"No se pudo consultar los vencimientos del bus {numero}: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
