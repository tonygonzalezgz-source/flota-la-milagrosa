"""Helpers compartidos entre tools del chatbot."""
from datetime import date, datetime
from decimal import Decimal


# ── Retry para errores transitorios de los proveedores de LLM ──────────
#
# 429 = rate limit / cuota agotada, 503 = modelo saturado, 5xx = fallo
# temporal del backend. Estos son recuperables reintentando; el resto
# (400, 401, 403, 404) NO se reintenta porque son errores de nuestro lado.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
RETRYABLE_MARKERS = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded")


def is_retryable_error(exc):
    """True si la excepción del SDK del LLM parece un fallo transitorio."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status in RETRYABLE_STATUS:
        return True
    msg = str(exc)
    if any(m in msg for m in RETRYABLE_MARKERS):
        return True
    return any(f" {s} " in f" {msg} " or f"{s} " in msg[:6] for s in RETRYABLE_STATUS)


def retry_delay_seconds(attempt):
    """Backoff exponencial: 1s, 2s, 4s. Attempt es 0-indexed."""
    return 2 ** attempt


def json_safe(obj):
    """Normaliza recursivamente un valor para que sea JSON-serializable.

    Postgres (psycopg2) devuelve DATE como `datetime.date` y NUMERIC como
    `Decimal`; SQLite devuelve strings. Como las tools construyen sus
    respuestas a partir de filas de la BD, este helper garantiza que el
    resultado final se pueda serializar tanto para el SDK de Anthropic
    (`json.dumps`) como para el de Google (`FunctionResponse`).
    """
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        # Los enteros exactos se preservan como int; el resto como float.
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


# Roles con visibilidad restringida por usuario_buses (mismo criterio que /api/buses).
ROLES_RESTRINGIDOS = ("Propietario", "Técnico Mant.")


def bus_visible(db, user_id, rol, bus_id):
    """True si el usuario puede ver ese bus según su rol (RLS-equivalente)."""
    if rol not in ROLES_RESTRINGIDOS:
        return True
    row = db.execute(
        "SELECT 1 FROM usuario_buses WHERE usuario_id = ? AND bus_id = ?",
        (user_id, bus_id),
    ).fetchone()
    return bool(row)


def _parse_fecha(f):
    """Convierte 'YYYY-MM-DD' (o None) a `date`; None si es inválida o vacía."""
    if not f:
        return None
    try:
        return date.fromisoformat(str(f)[:10])
    except (TypeError, ValueError):
        return None


def dias_restantes(fecha_str, hoy_str):
    """Diferencia en días entre fecha_str y hoy_str; None si fecha_str es inválida."""
    f = _parse_fecha(fecha_str)
    h = _parse_fecha(hoy_str) or date.today()
    if not f:
        return None
    return (f - h).days


def estado_vencimiento(dias):
    """Etiqueta legible según los días restantes."""
    if dias is None:
        return "sin_fecha"
    if dias < 0:
        return "vencido"
    if dias <= 30:
        return "por_vencer"
    return "vigente"


def doc_info(fecha_str, hoy_str):
    """Bloque uniforme para un documento (SOAT, tecnomecánica, etc.)."""
    dias = dias_restantes(fecha_str, hoy_str)
    return {
        "fecha": fecha_str,
        "dias_restantes": dias,
        "estado": estado_vencimiento(dias),
    }


# ── Helpers para comparativas de movilidad ─────────────────────────────

def pct_change(actual, previo):
    """Cambio porcentual (redondeado a 1 decimal); None si el previo es 0/None."""
    if not previo:
        return None
    return round(((actual - previo) / previo) * 100, 1)


def agregar_periodo(rows, label, desde, hasta):
    """Agrega una lista de registros_movilidad en un bloque con totales y promedios."""
    rows = list(rows)
    vueltas   = sum(int(r.get("vueltas") or 0)   for r in rows)
    pasajeros = sum(int(r.get("pasajeros") or 0) for r in rows)
    km        = round(sum(float(r.get("km_recorridos") or 0) for r in rows), 2)
    dias_activos = sum(1 for r in rows if int(r.get("vueltas") or 0) > 0)
    prom_pax_dia = round(pasajeros / dias_activos, 1) if dias_activos else 0
    prom_pax_vuelta = round(pasajeros / vueltas, 1) if vueltas else 0
    return {
        "label": label,
        "desde": desde,
        "hasta": hasta,
        "vueltas": vueltas,
        "pasajeros": pasajeros,
        "km_recorridos": km,
        "dias_activos": dias_activos,
        "prom_pasajeros_por_dia_activo": prom_pax_dia,
        "prom_pasajeros_por_vuelta": prom_pax_vuelta,
    }


def calcular_cambio(actual, previo):
    """Deltas absolutos y porcentuales entre dos bloques agregados."""
    campos = ("vueltas", "pasajeros", "km_recorridos", "dias_activos")
    out = {}
    for c in campos:
        a, p = actual.get(c, 0), previo.get(c, 0)
        out[c] = {"abs": round(a - p, 2), "pct": pct_change(a, p)}
    return out


def observaciones_comparativa(actual, previo, cambio):
    """Frases cortas que le dan al LLM material para explicar el 'por qué'."""
    obs = []
    da, dp = actual["dias_activos"], previo["dias_activos"]
    if da != dp:
        diff = abs(da - dp)
        mas_menos = "menos" if da < dp else "más"
        obs.append(
            f"{mas_menos.capitalize()} días activos: {da} vs {dp} "
            f"({diff} día{'s' if diff != 1 else ''} de diferencia)"
        )
    else:
        obs.append(f"Mismos días activos en ambos períodos: {da}")

    pv_a, pv_p = actual["prom_pasajeros_por_vuelta"], previo["prom_pasajeros_por_vuelta"]
    if pv_a and pv_p:
        pct = pct_change(pv_a, pv_p)
        if pct is None or abs(pct) < 3:
            obs.append(
                f"Ocupación por vuelta prácticamente igual ({pv_a} vs {pv_p} pasajeros/vuelta)"
            )
        else:
            obs.append(
                f"Ocupación por vuelta {'subió' if pct > 0 else 'bajó'} "
                f"{abs(pct)}% ({pv_a} vs {pv_p} pasajeros/vuelta)"
            )

    pd_a, pd_p = actual["prom_pasajeros_por_dia_activo"], previo["prom_pasajeros_por_dia_activo"]
    if pd_a and pd_p and da and dp:
        if pd_a > pd_p * 1.05:
            obs.append(
                f"En los días que operó movilizó MÁS pasajeros por día "
                f"({pd_a} vs {pd_p})"
            )
        elif pd_a < pd_p * 0.95:
            obs.append(
                f"En los días que operó movilizó MENOS pasajeros por día "
                f"({pd_a} vs {pd_p})"
            )

    total_pax_a, total_pax_p = actual["pasajeros"], previo["pasajeros"]
    if total_pax_p and total_pax_a < total_pax_p and da < dp:
        obs.append(
            "La caída total se explica principalmente por menos días de operación, "
            "no por menor ocupación."
        )
    return obs
