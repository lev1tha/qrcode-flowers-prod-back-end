"""
Расчётный движок производства — Python-зеркало frontend/src/utils/costing.js.

Зачем дублировать: фронт считает то же самое для отображения, но списание
сырья и оприходование продукции идут через API, и доверять числам клиента
здесь нельзя — иначе остатки разъедутся с реальностью. Имена функций
намеренно совпадают с JS-версией, чтобы их можно было сверять построчно.

Все внутренние расчёты — в БАЗОВЫХ единицах: кг → гр, л → мл, гр/мл/шт как есть.
"""

# Во сколько базовых единиц превращается 1 закупочная единица.
UNIT_FACTORS = {
    'кг': 1000,
    'л':  1000,
    'гр': 1,
    'мл': 1,
    'шт': 1,
}

# Базовая единица, в которой сырьё расходуется в рецептах.
BASE_UNITS = {
    'кг': 'гр',
    'л':  'мл',
    'гр': 'гр',
    'мл': 'мл',
    'шт': 'шт',
}


def to_base_units(volume, unit):
    """Объём в базовых единицах: 50 кг → 50 000 гр."""
    return (volume or 0) * UNIT_FACTORS.get(unit, 1)


def raw_unit_cost(raw):
    """
    Себестоимость 1 базовой единицы сырья, сом/гр.
    Мешок сахара 50 кг за 3400 сом → 3400 / 50000 = 0.068 сом/гр.
    """
    base_volume = to_base_units(raw.purchase_volume, raw.unit)
    if base_volume <= 0:
        return 0.0
    return (raw.purchase_price or 0) / base_volume


def semi_batch_cost(semi):
    """Себестоимость всего замеса полуфабриката, сом."""
    total = 0.0
    for ing in semi.ingredients.all():
        total += (ing.quantity or 0) * raw_unit_cost(ing.ingredient)
    return total


def semi_unit_cost(semi):
    """Себестоимость 1 гр/мл готового полуфабриката."""
    output = semi.batch_output or 0
    if output <= 0:
        return 0.0
    return semi_batch_cost(semi) / output


def product_cost(product):
    """Полная себестоимость 1 десерта, сом."""
    total = 0.0
    for comp in product.components.all():
        qty = comp.quantity or 0
        if comp.raw_id:
            total += qty * raw_unit_cost(comp.raw)
        elif comp.semi_id:
            total += qty * semi_unit_cost(comp.semi)
    return total


def effective_unit_cost(product):
    """
    Себестоимость 1 шт с учётом позиций без рецептуры.

    Позиции, импортированные из старой Excel-номенклатуры, состава не имеют —
    у них есть только готовая цифра. Считать их по составу нечем, и без
    этой ветки они дали бы себестоимость 0 и фиктивную маржу 100 %.
    """
    if product.components.exists():
        return product_cost(product)
    return product.manual_unit_cost or 0.0


def raw_usage_per_product(product):
    """
    Сколько базовых единиц каждого сырья уходит на 1 десерт:
    напрямую по составу + косвенно через полуфабрикаты.

    Возвращает {raw_id: расход}. Именно по этой карте списывается склад,
    поэтому косвенный расход через замес учитывать обязательно — иначе
    мука, попавшая в десерт только через бисквит, никогда бы не списалась.
    """
    usage = {}
    for comp in product.components.all():
        qty = comp.quantity or 0
        if comp.raw_id:
            usage[comp.raw_id] = usage.get(comp.raw_id, 0.0) + qty
            continue
        if not comp.semi_id:
            continue
        semi = comp.semi
        output = semi.batch_output or 0
        if output <= 0:
            continue
        # На 1 гр полуфабриката уходит quantity/batch_output гр сырья.
        for ing in semi.ingredients.all():
            share = (ing.quantity or 0) / output
            usage[ing.ingredient_id] = usage.get(ing.ingredient_id, 0.0) + qty * share
    return usage


def max_producible(product, raw_balances):
    """
    Сколько штук десерта можно выпустить из текущих остатков сырья.

    raw_balances — {raw_id: остаток в базовых единицах}.
    Ограничитель — самое дефицитное сырьё («бутылочное горлышко»).
    Десерт без состава производить нельзя (0), иначе из воздуха
    выпускались бы бесконечные позиции.
    """
    usage = raw_usage_per_product(product)
    if not usage:
        return 0
    limit = None
    for raw_id, per_unit in usage.items():
        if per_unit <= 0:
            continue
        available = raw_balances.get(raw_id, 0.0)
        possible = int(available // per_unit)
        limit = possible if limit is None else min(limit, possible)
    return max(limit or 0, 0)


def bottleneck(product, raw_balances):
    """
    Какое сырьё первым упрётся в ноль и на сколько штук его хватает.
    Возвращает (raw_id, units) или (None, None) — для подсказки «что докупить».
    """
    usage = raw_usage_per_product(product)
    worst_id, worst_units = None, None
    for raw_id, per_unit in usage.items():
        if per_unit <= 0:
            continue
        units = int(raw_balances.get(raw_id, 0.0) // per_unit)
        if worst_units is None or units < worst_units:
            worst_id, worst_units = raw_id, units
    return worst_id, worst_units
