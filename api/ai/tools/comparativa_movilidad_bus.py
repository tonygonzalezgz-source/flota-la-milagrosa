"""Tool: comparativa_movilidad_bus(numero, dias?).

Compara la movilidad de un bus entre los últimos N días y los N días
inmediatamente anteriores. Devuelve totales, promedios, deltas absolutos
y porcentuales, y observaciones que ayudan a explicar el porqué de las
diferencias.
"""
from datetime import date, timedelta

from ai.tools._common import (
    bus_visible,
    agregar_periodo,
    calcular_cambio,
    observaciones_comparativa,
)


NAME = "comparativa_movilidad_bus"

DESCRIPTION = (
    "Compara la movilidad de un bus en los últimos N días (default 7) contra "
    "los N días inmediatamente anteriores. Devuelve totales de cada período, "
    "días activos, promedios de pasajeros por vuelta y por día, deltas y "
    "observaciones que explican de dónde viene la diferencia. Úsala cuando "
    "el usuario pregunte por comparativas, tendencias o quiera saber por qué "
    "un bus movilizó más o menos que antes (p.ej. 'esta semana vs la pasada')."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "numero": {"type": "integer", "description": "Número interno del bus."},
        "dias": {
            "type": "integer",
            "description": "Tamaño de cada período en días (default 7, máx 90). "
                           "El 'período actual' son los últimos N días; el "
                           "'período previo' los N días inmediatamente anteriores.",
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
    desde_a = (hoy_d - timedelta(days=dias - 1)).isoformat()
    hasta_a = hoy
    hasta_b = (hoy_d - timedelta(days=dias)).isoformat()
    desde_b = (hoy_d - timedelta(days=2 * dias - 1)).isoformat()

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
            return {"acceso": False, "mensaje": f"No tienes acceso al bus {numero}."}

        def _rows(desde, hasta):
            return [dict(r) for r in db.execute(
                "SELECT vueltas, pasajeros, km_recorridos "
                "FROM registros_movilidad "
                "WHERE bus_id = ? AND fecha BETWEEN ? AND ?",
                (bus["id"], desde, hasta),
            ).fetchall()]

        label_a = f"últimos {dias} días" if dias != 7 else "esta semana (7 días)"
        label_b = f"{dias} días previos" if dias != 7 else "semana anterior (7 días)"
        actual = agregar_periodo(_rows(desde_a, hasta_a), label_a, desde_a, hasta_a)
        previo = agregar_periodo(_rows(desde_b, hasta_b), label_b, desde_b, hasta_b)
        cambio = calcular_cambio(actual, previo)

        if not actual["dias_activos"] and not previo["dias_activos"]:
            return {
                "encontrado": True,
                "numero": bus["numero"],
                "placa": bus["placa"],
                "mensaje": (
                    f"No hay registros de movilidad para el bus {numero} en "
                    f"ninguno de los dos períodos ({desde_b} a {hasta_a})."
                ),
            }

        return {
            "encontrado": True,
            "numero": bus["numero"],
            "placa": bus["placa"],
            "periodo_actual": actual,
            "periodo_previo": previo,
            "cambio": cambio,
            "observaciones": observaciones_comparativa(actual, previo, cambio),
        }
    except Exception as e:
        return {"error": f"No se pudo calcular la comparativa del bus {numero}: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
