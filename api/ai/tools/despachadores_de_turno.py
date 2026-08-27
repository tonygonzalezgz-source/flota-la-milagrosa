"""Tool: despachadores_de_turno().

Devuelve los despachadores que marcaron chequeo hoy: su puesto, la hora de
llegada, si ya cerraron su turno y los minutos trabajados.

Solo Administrador y Jefe de Ruta ven todos los chequeos (mismo criterio que
`/api/chequeo/historial` cuando lo consulta un rol de mando). Cualquier otro
rol recibe un `acceso: false` para que el LLM lo comunique con naturalidad.
"""

NAME = "despachadores_de_turno"

DESCRIPTION = (
    "Lista los despachadores que hoy marcaron chequeo GPS de llegada al "
    "puesto: quiénes están en turno ahora mismo, en qué puesto, a qué hora "
    "llegaron y cuáles ya cerraron su turno. Úsala cuando el usuario "
    "pregunte '¿quién está de turno?', '¿quién está trabajando hoy?', "
    "'¿quiénes marcaron llegada?' o cosas similares del día actual. Solo "
    "está disponible para Administrador y Jefe de Ruta."
)

PARAMETERS = {
    "type": "object",
    "properties": {},
    "required": [],
}


ROLES_PERMITIDOS = ("Administrador", "Jefe de Ruta")


def _resumen(hora_llegada, hora_salida, minutos):
    """Etiqueta de estado y minutos legibles."""
    if hora_salida:
        return "cerrado", minutos
    # En turno: minutos "aún trabajando" no los devolvemos precalculados; el
    # LLM tiene la hora de llegada y sabe que sigue abierto.
    return "en_turno", None


def run(args, ctx):
    rol = ctx["rol"]
    if rol not in ROLES_PERMITIDOS:
        return {
            "acceso": False,
            "mensaje": (
                "Solo Administrador o Jefe de Ruta pueden consultar el "
                "chequeo de los despachadores."
            ),
        }

    hoy = ctx["hoy"]
    db = ctx["get_db"]()
    try:
        rows = db.execute(
            """
            SELECT c.hora_llegada, c.hora_salida, c.minutos_trabajados,
                   u.nombre AS despachador, u.username,
                   p.nombre AS puesto
            FROM chequeos_despachador c
            JOIN usuarios u ON u.id = c.usuario_id
            LEFT JOIN puestos_trabajo p ON p.id = c.puesto_id
            WHERE c.fecha = ?
            ORDER BY c.hora_llegada
            """,
            (hoy,),
        ).fetchall()

        turnos = []
        en_turno = 0
        cerrados = 0
        for r in rows:
            d = dict(r)
            estado, minutos = _resumen(
                d["hora_llegada"], d["hora_salida"], d["minutos_trabajados"]
            )
            if estado == "en_turno":
                en_turno += 1
            else:
                cerrados += 1
            turnos.append({
                "despachador": d["despachador"],
                "username": d["username"],
                "puesto": d["puesto"],
                "hora_llegada": d["hora_llegada"][:5] if d["hora_llegada"] else None,
                "hora_salida": d["hora_salida"][:5] if d["hora_salida"] else None,
                "minutos_trabajados": minutos,
                "estado": estado,
            })

        return {
            "fecha": hoy,
            "total": len(turnos),
            "en_turno": en_turno,
            "cerrados": cerrados,
            "turnos": turnos,
        }
    except Exception as e:
        return {"error": f"No se pudo consultar el chequeo de hoy: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
