"""Coverage includes overdue contracts until settlement is confirmed."""
from sqlalchemy import func
from ..models import Option, OptionType, OptionStatus


def available_call_contracts(db, stock, exclude_option_id=None):
    query = db.query(func.coalesce(func.sum(Option.contracts), 0)).filter(
        Option.stock_id == stock.id, Option.option_type == OptionType.CALL, Option.status == OptionStatus.OPEN,
    )
    if exclude_option_id is not None:
        query = query.filter(Option.id != exclude_option_id)
    reserved = int(query.scalar())
    return max(0, int(stock.shares // 100) - reserved)
