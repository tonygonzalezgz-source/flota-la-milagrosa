"""Tool: vencimientos_flota_proximos(dias?).

Lista los buses cuyo SOAT, tecnomecánica o tarjeta de operación vence
dentro de N días o ya está vencido. Respeta la RLS: un Propietario ve
solo sus buses; el Administrador ve toda la flota.
"""
from ai.tools._common import ROLES_RESTRINGIDOS, dias_restantes, estado_vencimiento


NAME = "vencimientos_flota_proximos"

DESCRIPTION = (
    "Lista los buses de la flota que tienen SOAT, tecnomecánica o tarjeta de "
    "operación venciendo dentro de N días (default 30) o ya vencidos. "
    "Devuelve por bus qué documento está en riesgo y cuántos días faltan. "
    "Úsala cuando el usuario pregunte cosas como '¿qué buses tienen SOAT "
    "por vencer?', '¿cuáles vencen esta semana / este mes?' o quiera un "
    "panorama de vencimientos próximos."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "dias": {
            "type": "integer",
            "description": "Ventana en días desde hoy (default 30, máx 180). Incluye documentos ya vencidos.",
        }
    },
}


def run(args, ctx):
    try:
        dias = int(args.get("dias") or 30)
    except (TypeError, ValueError):
        dias = 30
    dias = max(1, min(dias, 180))

    hoy = ctx["hoy"]
    db = ctx["get_db"]()
    try:
        if ctx["rol"] in ROLES_RESTRINGIDOS:
            # Propietario / Técnico Mant.: solo sus buses.
            rows = db.execute(
                """SELECT b.numero, b.placa,
                          b.soat_vencimiento, b.tecno_vencimiento, b.tarjeta_op_vencimiento
                   FROM buses b
                   JOIN usuario_buses ub ON ub.bus_id = b.id
                   WHERE ub.usuario_id = ?
                   ORDER BY b.numero""",
                (ctx["user_id"],),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT numero, placa,
                          soat_vencimiento, tecno_vencimiento, tarjeta_op_vencimiento
                   FROM buses ORDER BY numero"""
            ).fetchall()

        DOCS = (
            ("soat",              "soat_vencimiento"),
            ("tecnomecanica",     "tecno_vencimiento"),
            ("tarjeta_operacion", "tarjeta_op_vencimiento"),
        )
        buses = []
        for r in rows:
            r = dict(r)
            docs_afectados = []
            for etiqueta, col in DOCS:
                dias_r = dias_restantes(r[col], hoy)
                if dias_r is None:
                    continue  # sin fecha registrada → no cuenta
                if dias_r <= dias:  # vencido o dentro de la ventana
                    docs_afectados.append({
                        "tipo": etiqueta,
                        "fecha": r[col],
                        "dias_restantes": dias_r,
                        "estado": estado_vencimiento(dias_r),
                    })
            if docs_afectados:
                buses.append({
                    "numero": r["numero"],
                    "placa": r["placa"],
                    "documentos": docs_afectados,
                })

        return {
            "hoy": hoy,
            "dias_umbral": dias,
            "total_buses_afectados": len(buses),
            "buses": buses,
        }
    except Exception as e:
        return {"error": f"No se pudo consultar los vencimientos próximos: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
