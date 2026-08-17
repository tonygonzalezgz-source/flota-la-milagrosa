"""Tool: estado_actual_bus(numero).

Devuelve el estado operativo del día de un bus por su número interno:
despacho de hoy (estado, ruta, conductor, si está cerrado) además de sus
datos básicos.

Respeta el mismo filtro que /api/buses: un Propietario o Técnico Mant. solo
puede consultar los buses vinculados a su usuario en `usuario_buses`; un
Administrador ve toda la flota.

`ctx` es un dict provisto por el endpoint con:
  - user_id : id del usuario autenticado (del JWT)
  - rol     : rol del usuario (del JWT)
  - get_db  : factoría de conexión a BD (misma que usa app.py)
  - hoy     : fecha de hoy en Bogotá 'YYYY-MM-DD' (hoy_bogota())
"""

# Definición neutral de la tool (independiente del proveedor de LLM).
NAME = "estado_actual_bus"

DESCRIPTION = (
    "Consulta el estado operativo de HOY de un bus de la flota a partir de su "
    "número interno: si está trabajando, en taller o en descanso, su ruta y "
    "conductor asignados y si el despacho ya fue cerrado. Úsala cuando el "
    "usuario pregunte por el estado, la ruta, el conductor o el despacho de un "
    "bus identificándolo por su número."
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
    """Ejecuta la consulta. Retorna un dict serializable (nunca lanza)."""
    numero = args.get("numero")
    if numero is None:
        return {"error": "Falta el número interno del bus."}
    try:
        numero = int(numero)
    except (TypeError, ValueError):
        return {"error": f"Número de bus inválido: {numero!r}"}

    get_db = ctx["get_db"]
    user_id = ctx["user_id"]
    rol = ctx["rol"]
    hoy = ctx["hoy"]

    db = get_db()
    try:
        bus = db.execute(
            "SELECT id, numero, placa, modelo, grupo, estado FROM buses WHERE numero = ?",
            (numero,),
        ).fetchone()
        if not bus:
            return {
                "encontrado": False,
                "mensaje": f"No existe un bus con número interno {numero}.",
            }
        bus = dict(bus)

        # RLS-equivalente: Propietario / Técnico Mant. solo ven sus buses.
        if rol in ("Propietario", "Técnico Mant."):
            permitido = db.execute(
                "SELECT 1 FROM usuario_buses WHERE usuario_id = ? AND bus_id = ?",
                (user_id, bus["id"]),
            ).fetchone()
            if not permitido:
                return {
                    "acceso": False,
                    "mensaje": f"No tienes acceso al bus {numero}.",
                }

        despacho = db.execute(
            """
            SELECT d.estado, d.cerrado,
                   r.nombre AS ruta,
                   c.nombre AS conductor
            FROM despacho_diario d
            LEFT JOIN rutas r       ON r.id = d.ruta_id
            LEFT JOIN conductores c ON c.id = d.conductor_id
            WHERE d.bus_id = ? AND d.fecha = ?
            """,
            (bus["id"], hoy),
        ).fetchone()

        result = {
            "encontrado": True,
            "numero": bus["numero"],
            "placa": bus["placa"],
            "modelo": bus["modelo"],
            "grupo": bus["grupo"],
            "estado_general": bus["estado"],
            "fecha": hoy,
        }
        if despacho:
            despacho = dict(despacho)
            result.update({
                "tiene_despacho_hoy": True,
                "estado_dia": despacho["estado"],
                "ruta": despacho.get("ruta"),
                "conductor": despacho.get("conductor"),
                "despacho_cerrado": bool(despacho["cerrado"]),
            })
        else:
            result["tiene_despacho_hoy"] = False
            result["mensaje"] = (
                f"El bus {numero} no tiene despacho registrado hoy ({hoy})."
            )
        return result
    except Exception as e:  # nunca romper el loop del LLM por un error de BD
        return {"error": f"No se pudo consultar el bus {numero}: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
