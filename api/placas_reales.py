"""
Placas reales de la flota La Milagrosa (fuente: PLACAS 2026 FM).
Mapa: número de vehículo → placa real.

Es la fuente única de verdad para las placas. La usan tanto el seed inicial
(setup_db.py) como el script de actualización (actualizar_placas.py).
"""

PLACAS_REALES = {
    1: "TSK929",  2: "TPU831",  3: "TSF428",  4: "TSF045",  5: "TPZ218",
    6: "EQS967",  7: "TPT402",  8: "TPU080",  9: "TRE350", 10: "TRG882",
    11: "TPV721", 12: "TPX127", 13: "TPY942", 14: "TPN598", 15: "TSJ108",
    16: "TPZ164", 17: "EQT518", 18: "TSH779", 19: "TPY796", 20: "TSI660",
    21: "TPX562", 22: "TPV607", 23: "TPQ978", 24: "TPU472", 25: "FWM248",
    26: "TSH088", 27: "FVY804", 28: "TNF665", 29: "EQS920", 30: "TSF050",
    31: "TTN531", 32: "TPU791", 33: "TSE043", 34: "SMU746", 35: "TPQ625",
    36: "TPV358", 37: "TPS856", 38: "TPV609", 39: "TPY771", 40: "TSI537",
    41: "TPY797", 42: "TPY105", 43: "TSE241", 44: "TSJ827", 45: "TSJ802",
    46: "FWL040", 47: "TPT496", 48: "TPX966", 49: "TPZ348", 50: "TSE261",
    51: "FWM026", 52: "TPU701", 53: "TPW052", 54: "TPW016", 55: "TPZ309",
    56: "TPS690", 57: "TPV417", 58: "TPT950", 59: "TPW082", 60: "TSH365",
    61: "TSI560", 62: "FWL244", 63: "TSF892", 64: "SMT895", 65: "SMT657",
    66: "TSJ252", 67: "TSJ251", 68: "TPR086", 69: "EQW112", 70: "FWL248",
    71: "TKH699", 72: "TSJ697", 73: "FWM158", 74: "TSJ346", 75: "TSH190",
    76: "TSJ427", 77: "SMU056", 78: "TSJ475", 79: "TSE840", 80: "TSJ472",
    81: "TSE156", 82: "TPZ811", 83: "TPU202", 84: "WDY800", 85: "TSJ926",
    86: "WDX506", 87: "TSE853", 88: "SMU203", 89: "TSJ635", 90: "TSJ464",
    91: "TPZ127", 92: "TSJ971", 93: "FWK136", 94: "TPZ084",
}
