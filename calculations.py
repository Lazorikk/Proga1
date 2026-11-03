from decimal import Decimal, ROUND_HALF_UP


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate(quantity, purchase, markup, purchase_vat, sale_vat, deduct):
    """Prices include VAT. Markup applies to cost excluding recoverable VAT."""
    q, p, m, iv, ov = map(lambda x: Decimal(str(x)),
                         (quantity, purchase, markup, purchase_vat, sale_vat))
    if not all(x.is_finite() for x in (q, p, m, iv, ov)):
        raise ValueError('Введите конечные числа')
    if q <= 0 or min(p, m, iv, ov) < 0 or max(iv, ov) > 100:
        raise ValueError('Количество должно быть положительным, цены и проценты — неотрицательными; НДС — до 100%')
    cost = p / (1 + iv / 100) if deduct else p
    price = money(cost * (1 + m / 100) * (1 + ov / 100))
    total = money(price * q)
    revenue = total / (1 + ov / 100)
    profit = money(revenue - cost * q)
    return dict(price=str(price), total=str(total), cost=str(money(cost * q)),
                profit=str(profit), vat=str(money(total - revenue)),
                margin=str(money(profit / revenue * 100)) if revenue else '0.00')
