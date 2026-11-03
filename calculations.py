from decimal import Decimal, ROUND_HALF_UP


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate(quantity, purchase, markup, purchase_vat, sale_vat, deduct,
              delivery=0, mode='markup', sale_price=None):
    """Purchase, sale and delivery prices include VAT; delivery is non-deductible."""
    q, p, m, iv, ov, d = (Decimal(str(x)) for x in
                         (quantity, purchase, markup, purchase_vat, sale_vat, delivery))
    if not all(x.is_finite() for x in (q, p, m, iv, ov, d)):
        raise ValueError('Введите конечные числа')
    if q <= 0 or min(p, m, iv, ov, d) < 0 or max(iv, ov) > 100:
        raise ValueError('Количество должно быть больше нуля; цены и проценты неотрицательны; НДС — до 100%')
    if mode not in ('markup', 'margin', 'price'):
        raise ValueError('Неизвестный способ расчёта')
    input_vat = money(p * q * iv / (100 + iv))
    recoverable = input_vat if deduct else Decimal(0)
    cost_total = money(p * q - recoverable + d)
    cost = cost_total / q
    if mode == 'margin':
        if m >= 100:
            raise ValueError('Целевая маржинальность должна быть меньше 100%')
        net_price = cost / (1 - m / 100)
    else:
        net_price = cost * (1 + m / 100)
    price = money(sale_price) if mode == 'price' else money(net_price * (1 + ov / 100))
    if not price.is_finite() or price < 0:
        raise ValueError('Цена продажи должна быть неотрицательной')
    total = money(price * q)
    vat = money(total * ov / (100 + ov))
    revenue = total - vat
    profit = revenue - cost_total
    return {k: str(v) for k, v in dict(price=price, total=total, cost=cost_total,
        profit=profit, vat=vat, input_vat=input_vat, recoverable=recoverable,
        vat_balance=vat-recoverable, revenue=revenue,
        margin=money(profit / revenue * 100) if revenue else Decimal(0),
        profitability=money(profit / cost_total * 100) if cost_total else Decimal(0)).items()}
