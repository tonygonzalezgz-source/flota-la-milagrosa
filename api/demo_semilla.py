"""Datos de ejemplo de la cuenta demo (revisores de Google Play).

La cuenta demo trabaja sobre una base SQLite aparte (ver `_demo_db` en app.py),
nunca sobre la de producción. Esta función la llena con una empresa inventada:
un propietario con dos vehículos (un bus y un micro), conductores, rutas y
~60 días de despacho, movilidad, recaudo y gastos, con fechas relativas a hoy
para que la app siempre muestre la semana y el mes en curso.

Los totales del recaudo siguen las mismas reglas del módulo Recaudo:
producido = pasajeros × tarifa; neto = producido − gastos; diferencia =
recaudado − neto.
"""
import random
from datetime import date, datetime, timedelta, timezone

DIAS = 60

# (numero, placa, modelo, grupo, ruta, km, pasajeros/día, viajes, km por viaje, ACPM)
_BUSES = [
    (901, "DEM901", "Bus 2019", "A", 0, 412_350, (390, 520), (5, 7), 38, (185_000, 230_000)),
    (902, "DEM902", "Micro 2021", "B", 1, 198_740, (250, 360), (6, 8), 29, (120_000, 155_000)),
]
_RUTAS = [("Ruta Centro – Norte", "A", "#2563eb"), ("Ruta Circular Sur", "B", "#f97316")]
_CONDUCTORES = [
    ("Andrés Gómez", "1012345001"), ("Luis Martínez", "1012345002"),
    ("Jorge Rincón", "1012345003"), ("Camilo Ortiz", "1012345004"),
]
# Posiciones de ejemplo en el mapa en vivo (Bogotá).
_POSICIONES = [(4.6486, -74.0628, 28.0, 15.0), (4.6097, -74.0817, 0.0, 210.0)]
_GASTOS_PROPIETARIO = [
    (3, "Cambio de aceite", "Aceite y filtros", "Lubricentro Demo", 380_000),
    (11, "Llantas", "Dos llantas delanteras", "Llantas Demo", 1_450_000),
    (19, "Lavado", "Lavado general", "Lavadero Demo", 45_000),
    (27, "Frenos", "Cambio de bandas", "Taller Demo", 520_000),
    (40, "Eléctrico", "Revisión del alternador", "Taller Demo", 210_000),
    (52, "Repuestos", "Espejo lateral", "Repuestos Demo", 160_000),
]


def sembrar(conn, hoy_iso, clave_hash, usuario):
    """Llena la base demo. `usuario`: el usuario con el que entran los revisores;
    `clave_hash`: su contraseña ya cifrada."""
    hoy = date.fromisoformat(hoy_iso)
    azar = random.Random(hoy_iso)          # mismos datos durante todo el día
    x = conn.execute

    x("UPDATE empresas SET nombre = 'Empresa Demo'")
    x("""INSERT INTO usuarios (username, password, nombre, rol, iniciales, color)
         VALUES (?, ?, 'Propietario Demo', 'Propietario', 'PD', '#2563eb')""", (usuario, clave_hash))
    prop_uid = x("SELECT id FROM usuarios WHERE username = ?", (usuario,)).fetchone()[0]
    # Quien "liquida" en la demo: no puede iniciar sesión (contraseña inservible).
    x("""INSERT INTO usuarios (username, password, nombre, rol, iniciales, color, activo)
         VALUES ('recaudo.demo', '!', 'Recaudo Demo', 'Recaudador', 'RD', '#eab308', 0)""")
    rec_uid = x("SELECT id FROM usuarios WHERE username = 'recaudo.demo'").fetchone()[0]

    x("""INSERT INTO propietarios (nombre, cedula, telefono, email, usuario_id)
         VALUES ('Propietario Demo', '900000001', '3000000000', 'demo@buscontrol.net', ?)""", (prop_uid,))
    prop_id = x("SELECT id FROM propietarios WHERE usuario_id = ?", (prop_uid,)).fetchone()[0]

    rutas = []
    for nombre, grupo, color in _RUTAS:
        x("INSERT INTO rutas (nombre, descripcion, grupo, color) VALUES (?, 'Ruta de demostración', ?, ?)",
          (nombre, grupo, color))
        rutas.append(x("SELECT MAX(id) FROM rutas").fetchone()[0])
    conductores = []
    for nombre, cedula in _CONDUCTORES:
        x("INSERT INTO conductores (nombre, cedula, telefono) VALUES (?, ?, '3000000000')", (nombre, cedula))
        conductores.append(x("SELECT MAX(id) FROM conductores").fetchone()[0])

    tarifas = {r[0]: r[1] for r in x("SELECT grupo, valor FROM recaudo_tarifas").fetchall()}
    tipo = x("SELECT id, nombre FROM recaudo_tipos_gasto ORDER BY "
             "CASE WHEN UPPER(nombre) LIKE 'ACPM%' THEN 0 ELSE 1 END, orden LIMIT 1").fetchone()

    vence = lambda dias: (hoy + timedelta(days=dias)).isoformat()   # noqa: E731
    documentos = [(vence(18), vence(150), vence(240)), (vence(210), vence(25), vence(300))]
    ahora = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for i, (numero, placa, modelo, grupo, r_idx, km, pax_rango, viajes_rango, km_viaje, acpm) in enumerate(_BUSES):
        soat, tecno, tarjeta = documentos[i]
        x("""INSERT INTO buses (numero, placa, modelo, grupo, estado, km_actuales, propietario_id,
                                soat_vencimiento, tecno_vencimiento, tarjeta_op_vencimiento)
             VALUES (?, ?, ?, ?, 'activo', ?, ?, ?, ?, ?)""",
          (numero, placa, modelo, grupo, km, prop_id, soat, tecno, tarjeta))
        bus_id = x("SELECT id FROM buses WHERE numero = ?", (numero,)).fetchone()[0]
        x("INSERT INTO usuario_buses (usuario_id, bus_id) VALUES (?, ?)", (prop_uid, bus_id))

        ruta_id = rutas[r_idx]
        titular, relevista = conductores[2 * i], conductores[2 * i + 1]
        registradora = 125_000 + 40_000 * i
        tarifa = tarifas.get(grupo) or 3000

        for atras in range(DIAS, -1, -1):
            dia = hoy - timedelta(days=atras)
            f = dia.isoformat()
            if i == 0 and atras % 17 == 5:
                estado = "taller"
            elif i == 1 and dia.weekday() == 6:
                estado = "descanso"
            else:
                estado = "trabajando"
            if estado != "trabajando":
                x("""INSERT INTO despacho_diario (bus_id, fecha, estado, ruta_id, despachador_id)
                     VALUES (?, ?, ?, ?, ?)""", (bus_id, f, estado, ruta_id, rec_uid))
                continue
            if atras == 0:
                # Hoy el bus está en la calle: despacho abierto y sin liquidar.
                x("""INSERT INTO despacho_diario (bus_id, fecha, estado, conductor_id, ruta_id,
                                                  registradora_inicio, despachador_id)
                     VALUES (?, ?, 'trabajando', ?, ?, ?, ?)""",
                  (bus_id, f, titular, ruta_id, registradora, rec_uid))
                continue

            pax = azar.randint(*pax_rango) - (60 if dia.weekday() == 6 else 0)
            viajes = azar.randint(*viajes_rango)
            inicio, fin = registradora, registradora + pax
            registradora = fin
            x("""INSERT INTO despacho_diario (bus_id, fecha, estado, conductor_id, ruta_id, viajes_realizados,
                                              registradora_inicio, registradora_fin, despachador_id)
                 VALUES (?, ?, 'trabajando', ?, ?, ?, ?, ?, ?)""",
              (bus_id, f, titular, ruta_id, viajes, inicio, fin, rec_uid))
            x("""INSERT INTO registros_movilidad (bus_id, fecha, vueltas, pasajeros, km_recorridos,
                                                  novedades, conductor_id, ruta_id, usuario_id)
                 VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)""",
              (bus_id, f, viajes, pax, viajes * km_viaje, titular, ruta_id, rec_uid))

            # Liquidación del día; con relevo cada 9 días en el bus.
            gasto = azar.randrange(acpm[0], acpm[1], 1000)
            if i == 0 and atras % 9 == 2:
                corte = inicio + pax // 2
                v1 = viajes // 2
                tramos = [(1, titular, inicio, corte, v1, gasto), (2, relevista, corte, fin, viajes - v1, 0)]
            else:
                tramos = [(1, titular, inicio, fin, viajes, gasto)]
            filas, totales = [], dict(producido=0, total_gastos=0, neto=0, recaudado=0, diferencia=0)
            for orden, cond, ini, fi, vj, g in tramos:
                producido = (fi - ini) * tarifa
                neto = producido - g
                recaudado = neto - (2_000 if azar.random() < .12 else 0)
                t = dict(producido=producido, total_gastos=g, neto=neto,
                         recaudado=recaudado, diferencia=recaudado - neto)
                filas.append((orden, cond, ini, fi, vj, t))
                for k in totales:
                    totales[k] += t[k]
            cur = x("""INSERT INTO recaudos (fecha, bus_id, registradora_inicio, registradora_fin, pasajeros,
                                             tarifa, producido, total_gastos, neto, recaudado, diferencia,
                                             usuario_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f, bus_id, inicio, fin, pax, tarifa, totales["producido"], totales["total_gastos"],
                     totales["neto"], totales["recaudado"], totales["diferencia"], rec_uid, f + " 21:30:00"))
            rid = cur.lastrowid
            for orden, cond, ini, fi, vj, t in filas:
                x("""INSERT INTO recaudo_conductores (recaudo_id, orden, conductor_id, ruta_id, viajes,
                                                      registradora_inicio, registradora_fin, pasajeros,
                                                      producido, total_gastos, neto, recaudado, diferencia)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (rid, orden, cond, ruta_id, vj, ini, fi, fi - ini, t["producido"], t["total_gastos"],
                   t["neto"], t["recaudado"], t["diferencia"]))
            if tipo and gasto:
                x("""INSERT INTO recaudo_gastos (recaudo_id, orden_conductor, tipo_gasto_id, tipo_nombre, valor)
                     VALUES (?, 1, ?, ?, ?)""", (rid, tipo[0], tipo[1], gasto))

        for atras, categoria, descripcion, taller, monto in _GASTOS_PROPIETARIO[i::2]:
            x("""INSERT INTO gastos_mantenimiento (bus_id, fecha, categoria, descripcion, taller, monto, usuario_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (bus_id, (hoy - timedelta(days=atras)).isoformat(), categoria, descripcion, taller, monto, prop_uid))

        lat, lon, vel, rumbo = _POSICIONES[i]
        x("""INSERT INTO gps_equipos (imei, token_hash, bus_id, notas, ultimo_reporte_at, ultima_hora_gps, ultimo_fix)
             VALUES (?, '!', ?, 'Equipo de demostración', ?, ?, 1)""", (f"DEMO{numero}", bus_id, ahora, ahora))
        equipo = x("SELECT id FROM gps_equipos WHERE bus_id = ?", (bus_id,)).fetchone()[0]
        x("""INSERT INTO gps_ultima_posicion (bus_id, equipo_id, lat, lon, velocidad_kmh, rumbo, precision_m,
                                              satelites, hora_gps, ultimo_reporte_at, fix_actual, estado_motor)
             VALUES (?, ?, ?, ?, ?, ?, 5, 12, ?, ?, 1, ?)""",
          (bus_id, equipo, lat, lon, vel, rumbo, ahora, ahora, "encendido" if vel else "apagado"))
    conn.commit()
