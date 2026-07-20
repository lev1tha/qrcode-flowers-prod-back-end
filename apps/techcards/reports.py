"""
ОПиУ и ОДДС — управленческая отчётность цеха.

Главный принцип (как в исходной Excel-модели):
  ОПиУ — по НАЧИСЛЕНИЮ: когда операция состоялась.
  ОДДС — по ФАКТУ ДЕНЕГ: когда деньги реально пришли или ушли.
Поэтому аренда, начисленная в июне и оплаченная в июле, попадёт
в разные месяцы разных отчётов. Это не расхождение, а смысл двух отчётов.

Источники данных (вариант «отчёты питаются документами»):
  выручка и себестоимость → накладные (Invoice/InvoiceLine)
  брак/списание           → Disposal
  всё остальное           → журнал операций (Operation)

Дублирования быть не может: продажи вводятся только накладной,
а вид операции «Себестоимость проданной продукции» в журнал не заводится.
"""
from collections import defaultdict
from datetime import date

from django.db.models import Sum

from .models import Disposal, Invoice, Operation, OperationType


# Статьи ОПиУ в порядке вывода. Названия совпадают с исходной Excel-моделью,
# чтобы отчёт читался теми же людьми без переобучения.
PNL_INCOME   = ['Выручка', 'Прочие доходы']
PNL_COGS     = ['Себестоимость']
PNL_OPEX     = [
    'ФОТ', 'Аренда', 'Коммунальные услуги', 'Упаковка и маркировка',
    'Маркетинг', 'Доставка/логистика', 'Возвраты/скидки', 'Брак/списание',
    'Налоги', 'Проценты по кредиту', 'Прочие расходы',
]

CF_SECTIONS = ['Операционная деятельность', 'Инвестиционная деятельность',
               'Финансовая деятельность']


def month_key(d):
    """Дата → первое число месяца. Ключ группировки во всех отчётах."""
    return date(d.year, d.month, 1)


def months_of(year):
    return [date(year, m, 1) for m in range(1, 13)]


def _blank(months):
    return {m: 0.0 for m in months}


# ── ОПиУ ──────────────────────────────────────────────────────

def pnl(shop, year):
    """
    Отчёт о прибылях и убытках по месяцам года.

    Возвращает статьи со значениями по месяцам плюс итог за год.
    """
    months = months_of(year)
    articles = defaultdict(lambda: _blank(months))

    # Выручка и себестоимость — из накладных, по дате документа.
    lines = (Invoice.objects
             .filter(shop=shop, date__year=year)
             .prefetch_related('lines'))
    for inv in lines:
        m = month_key(inv.date)
        articles['Выручка'][m]        += inv.revenue_total
        articles['Себестоимость'][m]  += inv.cost_total

    # Брак/списание — из документов списания, по себестоимости.
    for d in Disposal.objects.filter(shop=shop, created_at__year=year):
        articles['Брак/списание'][month_key(d.created_at.date())] += d.loss_amount

    # Всё остальное — журнал операций. Виды с «Не влияет на ОПиУ»
    # (закуп сырья, займы, капвложения) сюда осознанно не попадают.
    ops = Operation.objects.filter(shop=shop, date__year=year).select_related('op_type')
    for op in ops:
        if not op.op_type.affects_pnl:
            continue
        articles[op.op_type.pnl_article][month_key(op.date)] += op.accrual

    def row(name):
        vals = articles.get(name, _blank(months))
        return {'article': name,
                'values': [round(vals[m], 2) for m in months],
                'total': round(sum(vals.values()), 2)}

    def total_of(names):
        vals = {m: sum(articles.get(n, {}).get(m, 0.0) for n in names) for m in months}
        return {'values': [round(vals[m], 2) for m in months],
                'total': round(sum(vals.values()), 2)}

    income = total_of(PNL_INCOME)
    cogs   = total_of(PNL_COGS)
    opex   = total_of(PNL_OPEX)

    gross  = [round(i - c, 2) for i, c in zip(income['values'], cogs['values'])]
    ebt    = [round(g - o, 2) for g, o in zip(gross, opex['values'])]

    settings = getattr(shop, 'finance_settings', None)
    rate = settings.tax_rate if settings else 0.0
    # Резерв начисляем только на прибыльные месяцы: с убытка налога нет.
    tax  = [round(max(v, 0) * rate, 2) for v in ebt]
    net  = [round(e - t, 2) for e, t in zip(ebt, tax)]

    def pct(num, den):
        return [round(n / d * 100, 2) if d else 0.0 for n, d in zip(num, den)]

    return {
        'year': year,
        'months': [m.isoformat() for m in months],
        'income':      [row(n) for n in PNL_INCOME],
        'incomeTotal': income,
        'cogs':        [row(n) for n in PNL_COGS],
        'cogsTotal':   cogs,
        'grossProfit': {'values': gross, 'total': round(sum(gross), 2)},
        'opex':        [row(n) for n in PNL_OPEX],
        'opexTotal':   opex,
        'ebt':         {'values': ebt, 'total': round(sum(ebt), 2)},
        'tax':         {'values': tax, 'total': round(sum(tax), 2)},
        'netProfit':   {'values': net, 'total': round(sum(net), 2)},
        'grossMargin': pct(gross, income['values']),
        'netMargin':   pct(net,   income['values']),
    }


# ── ОДДС ──────────────────────────────────────────────────────

def cash_flow(shop, year):
    """
    Отчёт о движении денег по месяцам: поступления, выбытия,
    чистый поток и остаток нарастающим итогом.
    """
    months = months_of(year)
    inflow  = defaultdict(lambda: _blank(months))
    outflow = defaultdict(lambda: _blank(months))

    # Деньги от продаж — по накладным. Оплата считается в дату документа:
    # отсрочку платежа отдельным полем пока не ведём (см. заметку в README).
    for inv in Invoice.objects.filter(shop=shop, date__year=year).prefetch_related('lines'):
        inflow['Поступления от продаж'][month_key(inv.date)] += inv.revenue_total

    for op in Operation.objects.filter(shop=shop, date__year=year).select_related('op_type'):
        t = op.op_type
        if not t.affects_cash or not op.cash:
            continue
        bucket = inflow if t.flow == OperationType.FLOW_IN else outflow
        bucket[t.cf_article][month_key(op.date)] += abs(op.cash)

    def rows(bucket):
        return [{'article': a,
                 'values': [round(v[m], 2) for m in months],
                 'total': round(sum(v.values()), 2)}
                for a, v in sorted(bucket.items())]

    in_tot  = [round(sum(v[m] for v in inflow.values()), 2)  for m in months]
    out_tot = [round(sum(v[m] for v in outflow.values()), 2) for m in months]
    net     = [round(i - o, 2) for i, o in zip(in_tot, out_tot)]

    settings = getattr(shop, 'finance_settings', None)
    opening = settings.opening_cash if settings else 0.0
    opens, closes = [], []
    for n in net:
        opens.append(round(opening, 2))
        opening += n
        closes.append(round(opening, 2))

    return {
        'year': year,
        'months': [m.isoformat() for m in months],
        'opening':  opens,
        'inflow':   rows(inflow),
        'inflowTotal':  {'values': in_tot,  'total': round(sum(in_tot), 2)},
        'outflow':  rows(outflow),
        'outflowTotal': {'values': out_tot, 'total': round(sum(out_tot), 2)},
        'netFlow':  {'values': net, 'total': round(sum(net), 2)},
        'closing':  closes,
    }


# ── Дашборд ───────────────────────────────────────────────────

def dashboard(shop, year, month=None):
    """Сводка за месяц + динамика по месяцам + топ продуктов."""
    p = pnl(shop, year)
    c = cash_flow(shop, year)
    idx = (month - 1) if month else 0

    top = defaultdict(lambda: {'qty': 0.0, 'revenue': 0.0, 'cost': 0.0})
    invoices = Invoice.objects.filter(shop=shop, date__year=year)
    if month:
        invoices = invoices.filter(date__month=month)
    for inv in invoices.prefetch_related('lines__product'):
        for l in inv.lines.all():
            row = top[l.product.name]
            row['qty']     += l.quantity
            row['revenue'] += l.line_total
            row['cost']    += l.cost_total

    top_rows = sorted(
        ({'name': k,
          'qty': round(v['qty'], 2),
          'revenue': round(v['revenue'], 2),
          'margin': round(v['revenue'] - v['cost'], 2),
          'marginPct': round((v['revenue'] - v['cost']) / v['revenue'] * 100, 2)
                       if v['revenue'] else 0.0}
         for k, v in top.items()),
        key=lambda r: -r['revenue'])

    settings = getattr(shop, 'finance_settings', None)
    fixed = sum(f.amount for f in shop.fixed_costs.filter(active=True))

    return {
        'year': year,
        'month': month,
        'summary': {
            'revenue':     p['incomeTotal']['values'][idx],
            'cogs':        p['cogsTotal']['values'][idx],
            'grossProfit': p['grossProfit']['values'][idx],
            'opex':        p['opexTotal']['values'][idx],
            'netProfit':   p['netProfit']['values'][idx],
            'cashIn':      c['inflowTotal']['values'][idx],
            'cashOut':     c['outflowTotal']['values'][idx],
            'netFlow':     c['netFlow']['values'][idx],
            'closingCash': c['closing'][idx],
        },
        'dynamics': [
            {'month': p['months'][i],
             'revenue':     p['incomeTotal']['values'][i],
             'grossProfit': p['grossProfit']['values'][i],
             'netProfit':   p['netProfit']['values'][i],
             'netFlow':     c['netFlow']['values'][i]}
            for i in range(12)
        ],
        'topProducts': top_rows[:20],
        'fixedCostsMonthly': round(fixed, 2),
        'targetProfit': settings.target_profit if settings else 0.0,
    }


# ── Расшифровка ячейки ────────────────────────────────────────

def drilldown(shop, year, month, article, report='pnl'):
    """
    Из чего сложилась сумма в конкретной ячейке отчёта.

    Возвращает документы, попавшие в статью `article` за месяц `month`.
    Источник зависит от статьи: выручка и себестоимость лежат в накладных,
    брак — в списаниях, остальное — в журнале операций. Ровно та же
    логика, что и в pnl()/cash_flow(), иначе расшифровка не сошлась бы
    с самой цифрой.
    """
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    items = []

    def invoice_rows(amount_of):
        for inv in (Invoice.objects
                    .filter(shop=shop, date__gte=start, date__lt=end)
                    .prefetch_related('lines__product')):
            amount = amount_of(inv)
            if not amount:
                continue
            items.append({
                'kind': 'invoice',
                'id': inv.id,
                'date': inv.date.isoformat(),
                'title': f'Накладная {inv.number}',
                'subtitle': f'{inv.get_from_department_display()} → {inv.to_client}',
                'amount': round(amount, 2),
                'imported': inv.is_imported,
                'lines': [{'name': l.product.name,
                           'qty': round(l.quantity, 2),
                           'price': round(l.sell_price, 2),
                           'cost': round(l.unit_cost, 2),
                           'total': round(l.line_total, 2)}
                          for l in inv.lines.all()],
            })

    def operation_rows(match):
        for op in (Operation.objects
                   .filter(shop=shop, date__gte=start, date__lt=end)
                   .select_related('op_type')):
            amount = match(op)
            if not amount:
                continue
            items.append({
                'kind': 'operation',
                'id': op.id,
                'date': op.date.isoformat(),
                'title': op.op_type.name,
                'subtitle': ' · '.join(x for x in [op.counterparty, op.description] if x),
                'amount': round(amount, 2),
                'imported': op.op_type.is_legacy,
                'lines': [],
            })

    if report == 'pnl':
        if article == 'Выручка':
            invoice_rows(lambda i: i.revenue_total)
        elif article == 'Себестоимость':
            invoice_rows(lambda i: i.cost_total)
        elif article == 'Брак/списание':
            for d in Disposal.objects.filter(
                    shop=shop, created_at__date__gte=start, created_at__date__lt=end):
                items.append({
                    'kind': 'disposal',
                    'id': d.id,
                    'date': d.created_at.date().isoformat(),
                    'title': f'Списание: {(d.raw or d.product).name}',
                    'subtitle': f'{d.get_reason_display()} · {d.quantity:.2f}',
                    'amount': round(d.loss_amount, 2),
                    'imported': False,
                    'lines': [],
                })
        operation_rows(
            lambda op: op.accrual
            if op.op_type.affects_pnl and op.op_type.pnl_article == article else 0)
    else:
        if article == 'Поступления от продаж':
            invoice_rows(lambda i: i.revenue_total)
        operation_rows(
            lambda op: abs(op.cash)
            if op.op_type.affects_cash and op.op_type.cf_article == article else 0)

    items.sort(key=lambda x: x['date'])
    return {
        'year': year, 'month': month, 'article': article, 'report': report,
        'items': items,
        'total': round(sum(i['amount'] for i in items), 2),
    }


# ── Продажи по дням ───────────────────────────────────────────

def daily_sales(shop, year, month):
    """
    Реализация по суткам за месяц: сколько документов, штук и денег
    прошло каждый день (лист «ДДС по дням» из исходной модели).

    Дни без продаж возвращаются нулевыми строками — иначе в таблице
    не видно провалов, а именно они и интересны при разборе выручки.
    """
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    days = defaultdict(lambda: {'docs': 0, 'units': 0.0, 'revenue': 0.0, 'cost': 0.0})
    for inv in (Invoice.objects
                .filter(shop=shop, date__gte=start, date__lt=end)
                .prefetch_related('lines')):
        row = days[inv.date]
        row['docs']    += 1
        row['revenue'] += inv.revenue_total
        row['cost']    += inv.cost_total
        row['units']   += sum(l.quantity for l in inv.lines.all())

    # Движение денег по дням — из журнала операций.
    # Поступления считаем отдельно от реализации: часть продаж уходит
    # в дебиторку (отгрузили, деньги не пришли), и в посуточном разрезе
    # это видно нагляднее всего.
    inflow, outflow = defaultdict(float), defaultdict(float)
    for op in (Operation.objects
               .filter(shop=shop, date__gte=start, date__lt=end)
               .select_related('op_type')):
        if not op.op_type.affects_cash or not op.cash:
            continue
        bucket = inflow if op.op_type.flow == OperationType.FLOW_IN else outflow
        bucket[op.date] += abs(op.cash)

    rows, d = [], start
    while d < end:
        r = days.get(d, {'docs': 0, 'units': 0.0, 'revenue': 0.0, 'cost': 0.0})
        rows.append({
            'date':    d.isoformat(),
            'weekday': d.weekday(),               # 0 = понедельник
            'docs':    r['docs'],
            'units':   round(r['units'], 2),
            'revenue': round(r['revenue'], 2),
            'cost':    round(r['cost'], 2),
            'margin':  round(r['revenue'] - r['cost'], 2),
            # Деньги = выручка по накладным + поступления из журнала операций
            # (так же, как в cash_flow: накладная считается оплаченной датой документа).
            'cashIn':  round(r['revenue'] + inflow.get(d, 0.0), 2),
            'cashOut': round(outflow.get(d, 0.0), 2),
        })
        d = date(d.year, d.month, d.day + 1) if d.day < _days_in(d) else end

    sold = [r for r in rows if r['revenue']]
    revenue_total = sum(r['revenue'] for r in rows)
    best = max(sold, key=lambda r: r['revenue']) if sold else None

    settings = getattr(shop, 'finance_settings', None)
    fixed = sum(f.amount for f in shop.fixed_costs.filter(active=True))
    target = settings.target_profit if settings else 0.0
    days_in_month = len(rows)

    return {
        'year': year, 'month': month,
        'days': rows,
        'totals': {
            'docs':    sum(r['docs'] for r in rows),
            'units':   round(sum(r['units'] for r in rows), 2),
            'revenue': round(revenue_total, 2),
            'cost':    round(sum(r['cost'] for r in rows), 2),
            'margin':  round(sum(r['margin'] for r in rows), 2),
            'cashIn':  round(sum(r['cashIn'] for r in rows), 2),
            'cashOut': round(sum(r['cashOut'] for r in rows), 2),
        },
        'activeDays':  len(sold),
        # Средний чек считаем по дням С продажами: делить на весь месяц
        # бессмысленно, если цех работал половину дней.
        'avgPerDay':   round(revenue_total / len(sold), 2) if sold else 0.0,
        'bestDay':     best,
        # Сколько нужно продавать в сутки, чтобы закрыть постоянные расходы
        # и выйти на целевую прибыль (лист «План продаж»).
        'planPerDay':  round((fixed + target) / days_in_month, 2) if days_in_month else 0.0,
        'breakevenPerDay': round(fixed / days_in_month, 2) if days_in_month else 0.0,
    }


def _days_in(d):
    import calendar
    return calendar.monthrange(d.year, d.month)[1]


def today_sales(shop, today):
    """Короткая сводка за конкретные сутки — для шапки раздела."""
    invoices = list(Invoice.objects.filter(shop=shop, date=today)
                    .prefetch_related('lines__product'))
    revenue = sum(i.revenue_total for i in invoices)
    cost    = sum(i.cost_total for i in invoices)
    units   = sum(l.quantity for i in invoices for l in i.lines.all())

    items = defaultdict(float)
    for i in invoices:
        for l in i.lines.all():
            items[l.product.name] += l.quantity

    return {
        'date':    today.isoformat(),
        'docs':    len(invoices),
        'units':   round(units, 2),
        'revenue': round(revenue, 2),
        'cost':    round(cost, 2),
        'margin':  round(revenue - cost, 2),
        'topItems': sorted(
            ({'name': k, 'qty': round(v, 2)} for k, v in items.items()),
            key=lambda x: -x['qty'])[:5],
    }
