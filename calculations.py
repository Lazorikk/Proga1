"""Money calculations. Decimal throughout; all returned sums are currency amounts."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, InvalidOperation


def number(value, label='Значение', minimum=0, maximum=None):
    try:
        result = Decimal(str(value).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label}: введите число') from None
    if not result.is_finite() or result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f'{label}: недопустимое значение')
    if result > Decimal('1000000000000'):
        raise ValueError(f'{label}: слишком большое значение')
    return result


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate(quantity, purchase, markup, purchase_vat, sale_vat, deduct,
              delivery=0, mode='markup', sale_price=None, delivery_vat=0,
              purchase_includes_vat=True, delivery_includes_vat=True, discount=0,
              delivery_vat_amount=None):
    q = number(quantity, 'Количество')
    if q == 0:
        raise ValueError('Количество должно быть больше нуля')
    p, m = number(purchase, 'Закупка'), number(markup, 'Наценка / маржа')
    iv, ov = number(purchase_vat, 'НДС закупки', maximum=100), number(sale_vat, 'НДС продажи', maximum=100)
    d, dv = number(delivery, 'Доставка'), number(delivery_vat, 'НДС доставки', maximum=100)
    discount = number(discount, 'Скидка', maximum=100)
    if mode not in ('markup', 'margin', 'price'):
        raise ValueError('Неизвестный способ расчёта')
    gross_purchase = money(p * q * (1 if purchase_includes_vat else 1 + iv / 100))
    gross_delivery = money(d * (1 if delivery_includes_vat else 1 + dv / 100))
    input_goods = money(gross_purchase * iv / (100 + iv))
    input_delivery = (money(gross_delivery * dv / (100 + dv)) if delivery_vat_amount is None
                      else money(number(delivery_vat_amount, 'Распределённый НДС доставки')))
    input_vat = input_goods + input_delivery
    recoverable = input_vat if deduct else Decimal(0)
    cost_total = gross_purchase + gross_delivery - recoverable
    cost = cost_total / q
    if mode == 'margin':
        if m >= 100:
            raise ValueError('Целевая маржинальность должна быть меньше 100%')
        net_price = cost / (1 - m / 100)
    else:
        net_price = cost * (1 + m / 100)
    price_before = money(number(sale_price, 'Цена продажи') if mode == 'price'
                         else net_price * (1 + ov / 100))
    price = money(price_before * (1 - discount / 100))
    total = money(price * q)
    vat = money(total * ov / (100 + ov))
    revenue = total - vat
    profit = revenue - cost_total
    values = dict(price=price, base_price=price_before, total=total, cost=cost_total, gross_purchase=gross_purchase,
        delivery=gross_delivery, profit=profit, vat=vat, input_vat=input_vat,
        input_goods=input_goods, input_delivery=input_delivery, recoverable=recoverable,
        vat_balance=vat-recoverable, revenue=revenue,
        break_even=(cost * (1 + ov / 100)).quantize(Decimal('0.01'), rounding=ROUND_CEILING),
        margin=money(profit / revenue * 100) if revenue else Decimal(0),
        profitability=money(profit / cost_total * 100) if cost_total else Decimal(0))
    return {key: str(value) for key, value in values.items()}


def allocate_delivery(items, group):
    """Allocate cents by largest remainder; partial invoices never absorb absent goods."""
    mode = group.get('delivery_mode', 'included')
    amount = money(number(group.get('delivery', 0), 'Доставка закупки'))
    if mode == 'included':
        return [Decimal(0)] * len(items)
    if mode == 'manual':
        shares = [money(number(x.get('delivery', 0), 'Ручная доставка')) for x in items]
        if sum(shares) != amount:
            raise ValueError('Ручная доставка: сумма по строкам должна совпадать с доставкой закупки')
        return shares
    if mode not in ('shared', 'partial'):
        raise ValueError('Неизвестный способ учёта доставки')
    method = group.get('allocation', 'cost')
    weights = []
    for item in items:
        q = number(item['quantity'], 'Количество')
        if method == 'cost':
            vat = number(item.get('purchase_vat') if item.get('purchase_vat') not in (None, '')
                         else group.get('purchase_vat', 0), 'НДС закупки', maximum=100)
            weight = number(item['purchase'], 'Закупка') * q
            if not group.get('purchase_includes_vat', True):
                weight *= 1 + vat / 100
        elif method == 'quantity':
            weight = q
        elif method == 'equal':
            weight = Decimal(1)
        elif method in ('weight', 'volume'):
            weight = number(item.get(method, 0), 'Вес / объём единицы') * q
        else:
            raise ValueError('Неизвестный способ распределения доставки')
        weights.append(weight)
    selected = sum(weights)
    if selected == 0:
        if amount:
            raise ValueError('Нет базы для распределения доставки: укажите стоимость, количество, вес или объём')
        return [Decimal(0)] * len(items)
    denominator = number(group.get('full_base', 0), 'База полного счёта') if mode == 'partial' else selected
    if denominator < selected or not denominator:
        raise ValueError('База полного счёта не может быть меньше выбранных товаров')
    raw = [amount * w / denominator for w in weights]
    target = money(amount * selected / denominator)
    # Floor, then give remaining cents to largest fractional remainders.
    from decimal import ROUND_DOWN
    shares = [x.quantize(Decimal('0.01'), rounding=ROUND_DOWN) for x in raw]
    remainder = int((target - sum(shares)) * 100)
    order = sorted(range(len(raw)), key=lambda i: raw[i]-shares[i], reverse=True)
    for i in order[:remainder]:
        shares[i] += Decimal('0.01')
    return shares
