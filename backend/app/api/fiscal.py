from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract
from typing import Optional
from datetime import datetime
from ..database import get_db
from ..models import Transaction, TransactionType, User, Stock
from ..utils.auth import get_current_user

router = APIRouter()

# ---------------------------------------------------------------------------
# Tramos Global Complementario Chile 2025
# Basado en tabla SII:  Impuesto = Renta_Anual × Tasa − Factor
# Las rentas se expresan en CLP. UTM referencial ~$67,294 (Feb 2026)
# UTA = 12 × UTM ≈ $807,528 CLP
# ---------------------------------------------------------------------------
UTA_CLP = 807_528  # UTA referencial 2025 – el usuario puede ajustar

GC_TRAMOS = [
    # (límite_superior_UTA, tasa, factor_CLP_por_UTA, descripción)
    (13.5,   0.00,  0,                  "Exento"),
    (30.0,   0.04,  13.5 * 0.04,        "4%"),
    (50.0,   0.08,  30.0 * 0.04 + (50.0-30.0)*0.0,  "8%"),
    (70.0,   0.135, 0,                  "13.5%"),
    (90.0,   0.23,  0,                  "23%"),
    (120.0,  0.304, 0,                  "30.4%"),
    (150.0,  0.35,  0,                  "35%"),
    (float('inf'), 0.40, 0,             "40%"),
]

def calcular_tramo(renta_clp: float, uta_clp: float = UTA_CLP):
    """
    Calcula el impuesto Global Complementario chileno usando el método de tramos
    escalonados (sistema de tasas marginales, no de tramo único).
    Returns: (impuesto_total, detalle_por_tramo, tasa_efectiva)
    """
    renta_uta = renta_clp / uta_clp
    impuesto = 0.0
    detalle = []

    limites_clp = [
        (0,              13.5 * uta_clp, 0.00,  "Exento"),
        (13.5 * uta_clp, 30.0 * uta_clp, 0.04,  "4%"),
        (30.0 * uta_clp, 50.0 * uta_clp, 0.08,  "8%"),
        (50.0 * uta_clp, 70.0 * uta_clp, 0.135, "13.5%"),
        (70.0 * uta_clp, 90.0 * uta_clp, 0.23,  "23%"),
        (90.0 * uta_clp, 120.0 * uta_clp, 0.304,"30.4%"),
        (120.0 * uta_clp, 150.0 * uta_clp, 0.35,"35%"),
        (150.0 * uta_clp, float('inf'),    0.40, "40%"),
    ]

    for inf, sup, tasa, etiqueta in limites_clp:
        if renta_clp <= inf:
            break
        base = min(renta_clp, sup) - inf
        impuesto_tramo = base * tasa
        impuesto += impuesto_tramo
        detalle.append({
            "tramo": etiqueta,
            "base_clp": round(base),
            "tasa": tasa,
            "impuesto_clp": round(impuesto_tramo),
        })
        if renta_clp <= sup:
            break

    tasa_efectiva = (impuesto / renta_clp * 100) if renta_clp > 0 else 0
    return round(impuesto), detalle, round(tasa_efectiva, 2)


def sugerencias_optimizacion(
    capital_gains: float,
    premium_income: float,
    dividends: float,
    impuesto_clp: float,
    tasa_efectiva: float,
    renta_clp: float,
    uta_clp: float,
) -> list:
    tips = []

    # Pérdidas de capital compensables
    tips.append({
        "categoria": "💡 Compensación de pérdidas",
        "titulo": "Realiza pérdidas para compensar ganancias",
        "detalle": (
            "Si tienes posiciones con pérdida latente, considera venderlas antes del 31 de "
            "diciembre para compensar tus ganancias de capital. En Chile, las pérdidas de "
            "capital del mismo año fiscal reducen directamente la base imponible."
        ),
        "impacto": "Alto" if capital_gains > 0 else "Bajo",
    })

    # Diferimiento de ventas
    tips.append({
        "categoria": "📅 Timing de ventas",
        "titulo": "Difiere ventas a enero del año siguiente",
        "detalle": (
            "Si estás a punto de cerrar una posición rentable y ya tienes altos ingresos este año, "
            "considera esperar hasta enero para que la ganancia tribute en el ejercicio siguiente. "
            "Esto puede reducir el efecto de los tramos más altos del Global Complementario."
        ),
        "impacto": "Medio",
    })

    # Covered Calls conservadoras
    if premium_income > 0:
        tips.append({
            "categoria": "📊 Gestión de primas",
            "titulo": "Modera las primas cobradas hacia fin de año",
            "detalle": (
                "Las primas cobradas (Covered Calls y Cash-Secured Puts) se gravan como renta. "
                "Si tu tasa marginal ya es alta, considera reducir la frecuencia de venta de opciones "
                "en el último trimestre para no escalar a un tramo superior."
            ),
            "impacto": "Medio" if tasa_efectiva > 20 else "Bajo",
        })

    # Dividendos
    if dividends > 0:
        tips.append({
            "categoria": "💰 Dividendos",
            "titulo": "Solicita desembolso de dividendos en cuotas",
            "detalle": (
                "Los dividendos de acciones extranjeras pagan retención en USA (generalmente 30%). "
                "Declara el crédito por impuestos pagados en el exterior ante el SII para evitar "
                "doble tributación (Artículo 41 A de la LIR)."
            ),
            "impacto": "Alto" if dividends > 1_000_000 else "Medio",
        })

    # Crédito por impuestos en el extranjero
    tips.append({
        "categoria": "🌐 Crédito exterior",
        "titulo": "Usa el crédito por impuestos pagados en USA",
        "detalle": (
            "Las retenciones de EE.UU. (ej: 30% sobre dividendos) pueden usarse como crédito "
            "contra tu Global Complementario. Solicita el formulario 1042-S a tu broker y "
            "decláralo en el F22 bajo el Art. 41 A letra D."
        ),
        "impacto": "Alto",
    })

    # Ahorro previsional voluntario
    if renta_clp > 30 * uta_clp:
        tips.append({
            "categoria": "🏦 APV / APVC",
            "titulo": "Aporta al Ahorro Previsional Voluntario (APV) Modalidad B",
            "detalle": (
                "Puedes depositar hasta 600 UF anuales en APV bajo Régimen B y deducirlos "
                "directamente de tu base imponible del Global Complementario. Con una tasa "
                f"marginal del {tasa_efectiva:.0f}%, el ahorro real es significativo."
            ),
            "impacto": "Alto",
        })

    return tips


def analisis_spa(renta_clp: float, impuesto_clp: float, uta_clp: float) -> dict:
    """
    Analiza si conviene migrar a SpA (Sociedad por Acciones) para manejar
    las inversiones bursátiles en Chile.
    """
    # La SpA paga IDPC: 27% (sobre $10M+ de renta líquida imponible) o 25% (régimen general)
    # El dueño paga GC sobre dividendos efectivos, con crédito IDPC
    idpc_rate = 0.27
    impuesto_idpc = renta_clp * idpc_rate
    # Los dividendos al dueño tienen crédito de 27% del IDPC
    # Tasa efectiva total (empresa + persona) suele ser similar al GC alto, pero el dinero
    # acumula en la empresa sin pagar GC hasta que se retire
    renta_uta = renta_clp / uta_clp

    conviene = renta_uta >= 90  # Sobre 90 UTA la tasa GC es 30.4%, la SpA puede convenir
    muy_conveniente = renta_uta >= 120  # Sobre 120 UTA tasa GC es 35-40%

    ahorro_estimado = max(0, impuesto_clp - impuesto_idpc)

    nivel = "🟢 No conviene aún" if renta_uta < 70 else ("🟡 Zona gris – evalúa con contador" if renta_uta < 90 else ("🟠 Conviene estudiar la migración" if renta_uta < 120 else "🔴 Migración a SpA muy recomendada"))

    return {
        "nivel": nivel,
        "conviene": conviene,
        "muy_conveniente": muy_conveniente,
        "renta_uta": round(renta_uta, 1),
        "impuesto_persona_clp": impuesto_clp,
        "impuesto_estimado_spa_clp": round(impuesto_idpc),
        "ahorro_estimado_clp": round(ahorro_estimado),
        "umbral_estudio_uta": 70,
        "umbral_migracion_uta": 90,
        "explicacion": (
            "Una SpA inversionista paga Impuesto de Primera Categoría (IDPC) al 27% sobre las "
            "utilidades. Al retirar dividendos, el dueño paga Global Complementario pero con un "
            "crédito equivalente al IDPC pagado. La ventaja real es el DIFERIMIENTO: las "
            "utilidades que quedan en la sociedad no pagan GC hasta ser retiradas, permitiendo "
            "reinvertir el 73% en vez del ~60-65% que queda tras el GC en tramos altos."
        ),
        "pasos": [
            "1. Constituye una SpA ante notario (costo ~$200-400 USD equivalente).",
            "2. Abre cuenta de corretaje a nombre de la SpA (Interactive Brokers acepta sociedades chilenas).",
            "3. Transfiere gradualmente las posiciones – ojo con el costo tributario de las plusvalías latentes al transferir.",
            "4. Contrata un contador especialista en rentas del exterior (Circular 12/2015 SII).",
            "5. Declara el F22 de la SpA (Abril) y el F22 personal con los dividendos efectivos retirados.",
        ],
    }


@router.get("/report")
async def get_fiscal_report(
    year: int = Query(datetime.now().year - 1, description="Año tributario"),
    dolar_observado: float = Query(950.0, description="Dólar observado promedio del año (CLP)"),
    sueldo_bruto_clp: float = Query(0.0, description="Sueldo bruto anual CLP (suma de todas las liquidaciones del año)"),
    iusc_pagado_clp: float = Query(0.0, description="Impuesto Único de Segunda Categoría pagado en el año (aparece en tus liquidaciones como 'Impuesto a la Renta')"),
    otros_ingresos_clp: float = Query(0.0, description="Otros ingresos del año en CLP (honorarios, arriendos, etc.)"),
    retencion_dividendos_usd: float = Query(0.0, description="Retención de impuestos pagada en USA sobre dividendos (Form 1042-S / 30%)"),
    uta_clp: float = Query(UTA_CLP, description="Valor UTA en CLP (por defecto 2025)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Informe fiscal anual para personas naturales chilenas con inversiones en USA.
    Calcula: ganancias de capital, primas de opciones, dividendos, estimado Global
    Complementario con créditos IUSC y Art.41A (impuestos pagados en exterior).
    """
    # -------------------------------------------------------------------
    # 1. Obtener transacciones del año
    # -------------------------------------------------------------------
    transactions = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == current_user.id,
            extract("year", Transaction.transaction_date) == year,
        )
        .order_by(Transaction.transaction_date)
        .all()
    )

    # -------------------------------------------------------------------
    # 2. Clasificar por tipo de renta
    # -------------------------------------------------------------------
    ventas_acciones = []       # SELL_STOCK
    compras_acciones = []      # BUY_STOCK  (para calcular costo base simplificado)
    primas_cobradas = []       # SELL_CALL, SELL_PUT  → ingreso
    opciones_cerradas = []     # BUY_CALL, BUY_PUT    → gasto (cierre de posición larga)
    dividendos = []            # DIVIDEND
    asignaciones = []          # ASSIGNMENT

    for t in transactions:
        tt = t.transaction_type
        if tt == TransactionType.SELL_STOCK:
            ventas_acciones.append(t)
        elif tt == TransactionType.BUY_STOCK:
            compras_acciones.append(t)
        elif tt in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            primas_cobradas.append(t)
        elif tt in (TransactionType.BUY_CALL, TransactionType.BUY_PUT):
            opciones_cerradas.append(t)
        elif tt == TransactionType.DIVIDEND:
            dividendos.append(t)
        elif tt == TransactionType.ASSIGNMENT:
            asignaciones.append(t)

    # -------------------------------------------------------------------
    # 3. Calcular montos en USD y CLP
    # -------------------------------------------------------------------
    def usd_to_clp(usd: float) -> int:
        return round(usd * dolar_observado)

    # Ganancias de capital brutas (ventas – para el cálculo exacto se necesita costo base)
    ingresos_ventas_usd = sum(abs(t.total_amount) for t in ventas_acciones)
    # Costo de compras del mismo año (proxy simplificado; el real requiere FIFO / costo promedio)
    costo_compras_usd = sum(abs(t.total_amount) for t in compras_acciones)

    # Ganancia de capital neta aproximada (puede ser negativa = pérdida)
    ganancia_capital_usd = ingresos_ventas_usd - costo_compras_usd
    ganancia_capital_clp = usd_to_clp(ganancia_capital_usd)

    # Primas netas (cobradas − pagadas por cierres)
    primas_usd = sum(abs(t.total_amount) for t in primas_cobradas)
    cierres_usd = sum(abs(t.total_amount) for t in opciones_cerradas)
    primas_netas_usd = primas_usd - cierres_usd
    primas_netas_clp = usd_to_clp(primas_netas_usd)

    dividendos_usd = sum(abs(t.total_amount) for t in dividendos)
    dividendos_clp = usd_to_clp(dividendos_usd)

    # Comisiones totales (deducibles)
    comisiones_usd = sum(t.commission for t in transactions)
    comisiones_clp = usd_to_clp(comisiones_usd)

    # -------------------------------------------------------------------
    # 4. Base imponible total
    # -------------------------------------------------------------------
    # Solo se grava la ganancia de capital positiva; pérdida = 0 para efectos GC
    renta_inversiones_clp = max(0, ganancia_capital_clp) + max(0, primas_netas_clp) + dividendos_clp
    # Sueldo + otros ingresos
    renta_trabajo_clp = sueldo_bruto_clp + otros_ingresos_clp
    renta_total_clp = renta_inversiones_clp + renta_trabajo_clp

    # -------------------------------------------------------------------
    # 5. Cálculo Global Complementario bruto
    # -------------------------------------------------------------------
    impuesto_bruto_clp, desglose_tramos, tasa_efectiva = calcular_tramo(renta_total_clp, uta_clp)

    # -------------------------------------------------------------------
    # 6. Créditos que reducen el GC
    # -------------------------------------------------------------------

    # Crédito 1: IUSC (Impuesto Único de Segunda Categoría)
    # El impuesto retenido mensualmente por el empleador es crédito directo contra el GC.
    # Si IUSC > GC, el exceso se devuelve (reliquidación anual SII).
    credito_iusc_clp = round(min(iusc_pagado_clp, impuesto_bruto_clp))

    # Crédito 2: Impuestos pagados en el exterior (Art. 41 A LIR)
    # Aplica sobre rentas de fuente extranjera (dividendos, ganancias capital en USA).
    # Límite: el crédito no puede exceder la tasa efectiva del GC aplicada sobre esa renta.
    #
    # ✅ TRATADO CHILE-USA VIGENTE desde el 19 de diciembre de 2023 (efectos desde 01.01.2024).
    #    Publicado en Diario Oficial de Chile el 27 de enero de 2024.
    #    Fuente oficial SII: https://www.sii.cl/normativa_legislacion/convenios_internacionales.html
    #
    # Tasas del tratado (Art. 10 – Dividendos):
    #   - 5%  si el beneficiario es empresa con ≥10% derechos de voto
    #   - 15% para dividendos de portafolio (inversores individuales)
    #
    # ⚠️ Para acceder a la tasa reducida del 15% (en vez del 30% estándar NRA),
    #    el inversor DEBE presentar el formulario W-8BEN a su broker (IB) declarando
    #    ser residente chileno y reclamar los beneficios del convenio.
    #    Si no lo has presentado, IB sigue reteniendo el 30% por defecto.
    #
    # En cualquier caso, la retención pagada (ya sea 15% o 30%) es crédito Art.41A contra el GC.
    retencion_dividendos_clp = round(retencion_dividendos_usd * dolar_observado)
    # Tope del crédito = tasa_efectiva_GC × renta_extranjera_total
    renta_extranjera_clp = renta_inversiones_clp  # toda la renta de inversiones es de fuente USA
    tope_credito_exterior = round(tasa_efectiva / 100 * renta_extranjera_clp)
    credito_art41a_clp = min(retencion_dividendos_clp, tope_credito_exterior)

    # GC neto a pagar = GC bruto − crédito IUSC − crédito Art.41A
    impuesto_neto_clp = max(0, impuesto_bruto_clp - credito_iusc_clp - credito_art41a_clp)

    # Saldo a favor (devolución) si IUSC > GC bruto
    devolucion_clp = max(0, iusc_pagado_clp - impuesto_bruto_clp)

    # -------------------------------------------------------------------
    # 7. Sugerencias y análisis SpA
    # -------------------------------------------------------------------
    tips = sugerencias_optimizacion(
        capital_gains=max(0, ganancia_capital_clp),
        premium_income=max(0, primas_netas_clp),
        dividends=dividendos_clp,
        impuesto_clp=impuesto_bruto_clp,
        tasa_efectiva=tasa_efectiva,
        renta_clp=renta_total_clp,
        uta_clp=uta_clp,
    )
    spa = analisis_spa(renta_total_clp, impuesto_bruto_clp, uta_clp)

    # -------------------------------------------------------------------
    # 8. Detalle de transacciones enriquecido
    # -------------------------------------------------------------------
    def tx_to_dict(t: Transaction):
        return {
            "id": t.id,
            "fecha": t.transaction_date.strftime("%Y-%m-%d"),
            "ticker": t.ticker,
            "tipo": t.transaction_type.value,
            "cantidad": t.quantity,
            "precio_usd": round(t.price, 4),
            "total_usd": round(abs(t.total_amount), 2),
            "total_clp": usd_to_clp(abs(t.total_amount)),
            "comision_usd": round(t.commission, 2),
            "notas": t.notes or "",
        }

    return {
        "anio": year,
        "dolar_observado": dolar_observado,
        "uta_clp": uta_clp,
        "resumen_usd": {
            "ingresos_ventas_acciones": round(ingresos_ventas_usd, 2),
            "costo_compras_acciones": round(costo_compras_usd, 2),
            "ganancia_capital_neta": round(ganancia_capital_usd, 2),
            "primas_cobradas": round(primas_usd, 2),
            "cierres_opciones": round(cierres_usd, 2),
            "primas_netas": round(primas_netas_usd, 2),
            "dividendos": round(dividendos_usd, 2),
            "comisiones_totales": round(comisiones_usd, 2),
        },
        "resumen_clp": {
            "ganancia_capital": ganancia_capital_clp,
            "primas_netas": primas_netas_clp,
            "dividendos": dividendos_clp,
            "sueldo_bruto": round(sueldo_bruto_clp),
            "otros_ingresos": round(otros_ingresos_clp),
            "renta_trabajo": round(renta_trabajo_clp),
            "renta_inversiones": renta_inversiones_clp,
            "renta_total_base_imponible": round(renta_total_clp),
            "comisiones_deducibles": comisiones_clp,
        },
        "impuesto_global_complementario": {
            "impuesto_bruto_clp": impuesto_bruto_clp,
            "credito_iusc_clp": credito_iusc_clp,
            "credito_art41a_clp": credito_art41a_clp,
            "retencion_dividendos_clp": retencion_dividendos_clp,
            "tope_credito_exterior_clp": tope_credito_exterior,
            "impuesto_neto_clp": impuesto_neto_clp,
            "devolucion_clp": devolucion_clp,
            "tasa_efectiva_pct": tasa_efectiva,
            "desglose_tramos": desglose_tramos,
            "nota_tratado": (
                "✅ El Convenio de doble tributación Chile-USA SÍ está VIGENTE desde el "
                "19 de diciembre de 2023 (efectos desde 01.01.2024). Publicado en el "
                "Diario Oficial de Chile el 27 de enero de 2024 (Decreto Supremo N°200). "
                "Fuente: SII convenios internacionales. "
                "Tasa tratado para dividendos de portafolio (Art.10): 15% (vs 30% estándar NRA). "
                "IMPORTANTE: para acceder a la tasa reducida del 15%, debes presentar el "
                "formulario W-8BEN a Interactive Brokers declarando ser residente chileno y "
                "reclamando los beneficios del convenio. Sin el W-8BEN, IB retiene el 30% por defecto. "
                "En ambos casos, la retención pagada es crédito Art.41A LIR contra tu GC."
            ),
            "advertencia": (
                "Este es un ESTIMADO referencial. El cálculo oficial del SII puede diferir "
                "según créditos, deducciones y el costo base real de las posiciones. "
                "Consulta siempre a un contador especialista en rentas del exterior."
            ),
        },
        "conteo_operaciones": {
            "total": len(transactions),
            "ventas_acciones": len(ventas_acciones),
            "compras_acciones": len(compras_acciones),
            "primas_cobradas": len(primas_cobradas),
            "opciones_cerradas": len(opciones_cerradas),
            "dividendos": len(dividendos),
            "asignaciones": len(asignaciones),
        },
        "transacciones": [tx_to_dict(t) for t in transactions],
        "sugerencias_optimizacion": tips,
        "analisis_spa": spa,
    }


@router.get("/years")
async def get_fiscal_years(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna los años con transacciones registradas"""
    from sqlalchemy import func
    rows = (
        db.query(func.extract("year", Transaction.transaction_date).label("yr"))
        .filter(Transaction.user_id == current_user.id)
        .distinct()
        .order_by(func.extract("year", Transaction.transaction_date).desc())
        .all()
    )
    years = [int(r.yr) for r in rows if r.yr]
    if not years:
        years = [datetime.now().year - 1]
    return {"years": years}
