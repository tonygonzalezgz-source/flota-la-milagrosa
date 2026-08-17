"""Tool: comparativa_movilidad_flota(dias?).

Compara la movilidad AGREGADA de la flota visible al usuario entre los
últimos N días y los N días inmediatamente anteriores. Devuelve totales,
promedios, deltas y los top 3 buses que más subieron y bajaron en
pasajeros. Respeta la RLS.
"""
from datetime import date, timedelta

from ai.tools._common import (
    ROLES_RESTRINGIDOS,
    agregar_periodo,
    calcular_cambio,
    pct_change,
)


NAME = "comparativa_movilidad_flota"

DESCRIPTION = (
    "Compara la movilidad AGREGADA de la flota (todos los buses visibles al "
    "usuario) en los últimos N días vs los N días previos. Devuelve totales "
    "globales de cada período, deltas absolutos y porcentuales, y los top 3 "
    "buses que MÁS subieron y los top 3 que MÁS bajaron en pasajeros. Úsala "
    "cuando el usuario pida panorama, resumen, tendencia o comparativa de "
    "toda la flota (o de sus buses, en caso del propietario)."
)

PARAMETERS = {
    "type": "object",
    "properties": {
        "dias": {
            "type": "integer",
            "description": "Tamaño de cada período en días (default 7, máx 90).",
        }
    },
}


def _rows(db, bus_ids, desde, hasta):
    if not bus_ids:
        return []
    ph = ",".join("?" * len(bus_ids))
    return [dict(r) for r in db.execute(
        f"SELECT bus_id, vueltas, pasajeros, km_recorridos "
        f"FROM registros_movilidad "
        f"WHERE bus_id IN ({ph}) AND fecha BETWEEN ? AND ?",
        list(bus_ids) + [desde, hasta],
    ).fetchall()]


def _by_bus(rows):
    """Agrupa filas por bus_id y suma pasajeros."""
    out = {}
    for r in rows:
        b = r["bus_id"]
        out[b] = out.get(b, 0) + int(r.get("pasajeros") or 0)
    return out


def run(args, ctx):
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
        # Buses visibles según RLS.
        if ctx["rol"] in ROLES_RESTRINGIDOS:
            buses = [dict(r) for r in db.execute(
                """SELECT b.id, b.numero, b.placa
                   FROM buses b JOIN usuario_buses ub ON ub.bus_id = b.id
                   WHERE ub.usuario_id = ? ORDER BY b.numero""",
                (ctx["user_id"],),
            ).fetchall()]
            scope = "tus buses"
        else:
            buses = [dict(r) for r in db.execute(
                "SELECT id, numero, placa FROM buses ORDER BY numero"
            ).fetchall()]
            scope = "toda la flota"
        bus_ids = [b["id"] for b in buses]
        meta = {b["id"]: b for b in buses}

        rows_a = _rows(db, bus_ids, desde_a, hasta_a)
        rows_b = _rows(db, bus_ids, desde_b, hasta_b)

        label_a = f"últimos {dias} días" if dias != 7 else "esta semana (7 días)"
        label_b = f"{dias} días previos" if dias != 7 else "semana anterior (7 días)"
        actual = agregar_periodo(rows_a, label_a, desde_a, hasta_a)
        previo = agregar_periodo(rows_b, label_b, desde_b, hasta_b)
        cambio = calcular_cambio(actual, previo)

        # Top movers por bus (delta de pasajeros).
        pax_a = _by_bus(rows_a)
        pax_b = _by_bus(rows_b)
        deltas = []
        for bid in set(pax_a) | set(pax_b):
            m = meta.get(bid)
            if not m:
                continue
            a, p = pax_a.get(bid, 0), pax_b.get(bid, 0)
            deltas.append({
                "numero": m["numero"], "placa": m["placa"],
                "pasajeros_actual": a, "pasajeros_previo": p,
                "delta_pasajeros": a - p, "pct": pct_change(a, p),
            })
        deltas.sort(key=lambda d: d["delta_pasajeros"], reverse=True)
        top_subieron = [d for d in deltas if d["delta_pasajeros"] > 0][:3]
        top_bajaron  = [d for d in deltas if d["delta_pasajeros"] < 0][-3:][::-1]

        return {
            "scope": scope,
            "total_buses_visibles": len(buses),
            "buses_con_registro_actual": len(pax_a),
            "buses_con_registro_previo": len(pax_b),
            "periodo_actual": actual,
            "periodo_previo": previo,
            "cambio": cambio,
            "top_subieron": top_subieron,
            "top_bajaron": top_bajaron,
        }
    except Exception as e:
        return {"error": f"No se pudo calcular la comparativa de flota: {e}"}
    finally:
        db.close()


TOOL = {
    "name": NAME,
    "description": DESCRIPTION,
    "parameters": PARAMETERS,
    "run": run,
}
