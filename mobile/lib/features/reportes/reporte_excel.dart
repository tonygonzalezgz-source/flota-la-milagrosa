import 'package:excel/excel.dart';

import '../../core/fechas.dart';
import '../../core/modelos.dart';
import '../../core/movilidad.dart';
import '../../core/reportes.dart';

/// Libro de Excel del reporte (lo que en la web es "Descargar Excel"), con tres
/// hojas: Resumen (por bus, ruta y conductor), Detalle (día a día) y Días
/// (estado de cada bus en cada fecha).
List<int> excelReporte(Reporte r) {
  final libro = Excel.createExcel();
  libro.rename(libro.getDefaultSheet() ?? 'Sheet1', 'Resumen');

  final titulo = CellStyle(bold: true, fontSize: 14);
  final encabezado = CellStyle(
    bold: true,
    fontColorHex: ExcelColor.white,
    backgroundColorHex: ExcelColor.fromHexString('#2F5BFF'),
  );
  final totalEstilo = CellStyle(bold: true, backgroundColorHex: ExcelColor.fromHexString('#E8EDFF'));

  TextCellValue t(String s) => TextCellValue(s);
  IntCellValue n(int v) => IntCellValue(v);
  DoubleCellValue d(double v, [int dec = 1]) => DoubleCellValue(double.parse(v.toStringAsFixed(dec)));

  void fila(Sheet hoja, List<CellValue?> valores, [CellStyle? estilo]) {
    hoja.appendRow(valores);
    if (estilo == null) return;
    final i = hoja.maxRows - 1;
    for (var c = 0; c < valores.length; c++) {
      hoja.cell(CellIndex.indexByColumnRow(columnIndex: c, rowIndex: i)).cellStyle = estilo;
    }
  }

  // ── Resumen ──
  final res = libro['Resumen'];
  fila(res, [t('Reporte de movilidad — Flota La Milagrosa')], titulo);
  fila(res, [t('Periodo'), t('${Fechas.corta(r.rango.desde)} a ${Fechas.corta(r.rango.hasta)}'), t('${r.diasPeriodo} días')]);
  fila(res, [t('Valor del pasaje'), n(tarifaPasaje)]);
  if (!r.conDespacho) {
    fila(res, [t('Sin datos de despacho: los días sin movilidad figuran como "Sin registro".')]);
  }
  res.appendRow([t('')]);
  fila(res, [
    t('Bus'), t('Placa'), t('Días trabajados'), t('Taller'), t('Descanso'), t('Sin registro'),
    t('Vueltas'), t('Pasajeros'), t('Km'), t('IPK'), t('Pasajeros por vuelta'), t('Dinero bruto'),
  ], encabezado);
  for (final b in r.buses) {
    fila(res, [
      t(b.numero), t(b.placa), n(b.cuantos(EstadoDia.trabajado)), n(b.cuantos(EstadoDia.taller)),
      n(b.cuantos(EstadoDia.descanso)), n(b.cuantos(EstadoDia.sinRegistro)), n(b.totales.vueltas),
      n(b.totales.pasajeros), d(b.totales.km), d(b.totales.ipkValor, 2), d(b.totales.pasajerosPorVuelta),
      n(b.totales.dinero),
    ]);
  }
  fila(res, [
    t('TOTAL'), t(''), n(r.cuantos(EstadoDia.trabajado)), n(r.cuantos(EstadoDia.taller)),
    n(r.cuantos(EstadoDia.descanso)), n(r.cuantos(EstadoDia.sinRegistro)), n(r.total.vueltas),
    n(r.total.pasajeros), d(r.total.km), d(r.total.ipkValor, 2), d(r.total.pasajerosPorVuelta), n(r.total.dinero),
  ], totalEstilo);

  res.appendRow([t('')]);
  fila(res, [t('Ruta'), t('Días'), t('Buses'), t('Vueltas'), t('Pasajeros'), t('Km'), t('Dinero bruto')], encabezado);
  for (final e in r.porRuta.entries) {
    final v = e.value;
    fila(res, [t(e.key), n(v.dias.length), n(v.buses.length), n(v.vueltas), n(v.pasajeros), d(v.km), n(v.dinero)]);
  }

  res.appendRow([t('')]);
  fila(res, [t('Conductor'), t('Días'), t('Vueltas'), t('Pasajeros'), t('Pasajeros por vuelta'), t('Dinero bruto')],
      encabezado);
  for (final e in r.porConductor.entries) {
    final v = e.value;
    fila(res, [t(e.key), n(v.dias.length), n(v.vueltas), n(v.pasajeros), d(v.pasajerosPorVuelta), n(v.dinero)]);
  }
  for (final (c, ancho) in [(0, 26.0), (1, 22.0), (2, 15.0), (10, 20.0), (11, 16.0)]) {
    res.setColumnWidth(c, ancho);
  }

  // ── Detalle día a día (más antiguo primero, como la web) ──
  final det = libro['Detalle'];
  fila(det, [
    t('Fecha'), t('Bus'), t('Placa'), t('Conductor'), t('Ruta'), t('Vueltas'), t('Pasajeros'), t('Km'),
    t('IPK'), t('Dinero bruto'), t('Estado despacho'), t('Novedades'),
  ], encabezado);
  for (final f in r.diario.reversed) {
    final pax = asInt(f['pasajeros']) ?? 0;
    final km = asDouble(f['km_recorridos']) ?? 0;
    fila(det, [
      t(Fechas.corta(f['fecha'])), t(asStr(f['numero'])), t(asStr(f['placa'])), t(conductorReporte(f)),
      t(rutaReporte(f)), n(asInt(f['vueltas']) ?? 0), n(pax), d(km), d(ipk(pax, km), 2), n(dineroLiquidar(pax)),
      t(asStr(f['despacho_estado'])), t(asStr(f['novedades']).trim()),
    ]);
  }
  for (final (c, ancho) in [(0, 12.0), (3, 26.0), (4, 26.0), (9, 14.0), (10, 16.0), (11, 40.0)]) {
    det.setColumnWidth(c, ancho);
  }

  // ── Días: estado de cada bus en cada fecha ──
  final dias = libro['Días'];
  fila(dias, [t('Fecha'), for (final b in r.buses) t('Bus ${b.numero}')], encabezado);
  for (final fecha in r.fechas) {
    fila(dias, [t(Fechas.corta(fecha)), for (final b in r.buses) t(b.dias[fecha]?.nombre ?? '')]);
  }
  dias.setColumnWidth(0, 12);

  libro.setDefaultSheet('Resumen');
  return libro.encode()!;
}

/// Nombre del archivo: "Reporte BusControl 2026-10-01 a 2026-10-08.xlsx".
String nombreExcel(Reporte r) {
  final quien = r.buses.length == 1 ? ' Bus ${r.buses.first.numero}' : '';
  return 'Reporte BusControl$quien ${r.rango.desde} a ${r.rango.hasta}.xlsx';
}
