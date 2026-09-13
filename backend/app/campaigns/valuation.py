"""Read-only marks; missing or stale quotes never become a zero liability."""
from datetime import datetime, timedelta, timezone
from math import isfinite

from ..models import Option, OptionStatus, CycleStatus, Stock
from ..providers.cboe_chains import CboeChainsProvider


def option_marks(db, campaigns, provider=None):
    provider = provider or CboeChainsProvider()
    cycles = [cycle for campaign in campaigns for cycle in campaign.cycles if cycle.status == CycleStatus.OPEN]
    ids = [cycle.option_id for cycle in cycles if cycle.option_id is not None]
    options = {o.id: o for o in db.query(Option).filter(Option.id.in_(ids)).all()} if ids else {}
    chains = {}
    marks = {}
    if campaigns and getattr(campaigns[0], "user_id", None) is not None:
        active = db.query(Option).join(Stock).filter(Stock.user_id == campaigns[0].user_id, Option.status == OptionStatus.OPEN).all()
        for campaign in campaigns:
            linked = {cycle.option_id for cycle in campaign.cycles}
            for option in active:
                if option.ticker != campaign.ticker:
                    continue
                opened = option.opened_at.replace(tzinfo=None)
                if opened < campaign.opened_at.replace(tzinfo=None):
                    continue
                if campaign.closed_at and opened > campaign.closed_at.replace(tzinfo=None):
                    continue
                if option.id not in linked:
                    marks[("campaign", campaign.id)] = "Reconstruye las campañas: hay contratos nuevos sin incorporar."

    for cycle in cycles:
        option = options.get(cycle.option_id)
        if option is None or option.status != OptionStatus.OPEN:
            marks[cycle.id] = {"error": "Reconstruye las campañas: cambió el contrato de origen."}
            continue
        stored_open = getattr(cycle, "open_premium", None)
        if stored_open is not None and abs(stored_open - option.total_premium) > .01:
            marks[cycle.id] = {"error": "Reconstruye las campañas: cambió el tamaño de la posición."}
            continue
        if cycle.ticker not in chains:
            try:
                quotes, underlying = provider.get_chain(cycle.ticker)
                stamp = underlying.as_of
                stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
                chains[cycle.ticker] = (quotes, stamp) if stamp >= datetime.now(timezone.utc) - timedelta(hours=24) else None
            except Exception:
                chains[cycle.ticker] = None
        chain = chains[cycle.ticker]
        if chain is None:
            marks[cycle.id] = {"error": "Sin cotización de opciones de las últimas 24 horas."}
            continue
        quotes, stamp = chain
        right = "C" if option.option_type.value == "CALL" else "P"
        quote = next((q for q in quotes if q.right == right and q.expiration == option.expiration_date.date()
                      and abs(q.strike - option.strike_price) < 1e-8 and q.multiplier == 100), None)
        if quote is None or quote.ask is None or not isfinite(quote.ask) or quote.ask < 0 or (quote.bid is not None and quote.ask < quote.bid):
            marks[cycle.id] = {"error": "Falta un ask válido para valorar la recompra."}
            continue
        marks[cycle.id] = {"ask": quote.ask, "liability": quote.ask * option.contracts * 100,
                           "as_of": stamp.isoformat(), "error": None}
    return marks
