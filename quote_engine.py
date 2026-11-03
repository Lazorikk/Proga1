"""Normalize old quotes and new supplier blocks into a reproducible snapshot."""
from copy import deepcopy
from decimal import Decimal
from calculations import calculate, allocate_delivery, money, number


def prepare_quote(data, organization):
    groups = deepcopy(data.get('groups') or [])
    items = deepcopy(data.get('items') or [])
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('Добавьте от 1 до 100 товаров')
    if not groups:
        # Legacy quotes keep row-level delivery and VAT values.
        groups = [dict(id='legacy', name='Закупка 1', purchase_vat=0,
                       delivery_mode='manual', delivery=str(sum(number(x.get('delivery', 0)) for x in items)),
                       delivery_vat=0, markup=20)]
        for item in items:
            item['group'] = 'legacy'
    if not isinstance(groups, list) or len(groups) > 30:
        raise ValueError('Допускается до 30 закупок')
    ids = [str(g.get('id', '')) for g in groups]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError('Некорректные идентификаторы закупок')
    for item in items:
        if not str(item.get('name', '')).strip():
            raise ValueError('Укажите наименование товара')
        if len(str(item['name'])) > 500:
            raise ValueError('Наименование товара слишком длинное (максимум 500 символов)')
        item['name'] = str(item['name']).strip()
        item['unit'] = str(item.get('unit') or 'шт')[:30]
        item['lead_time'] = str(item.get('lead_time', ''))[:300]
        item['group'] = str(item.get('group', ids[0]))
        if item['group'] not in ids:
            raise ValueError('Для товара не найдена закупка')
    warnings = []
    for group in groups:
        group['id'] = str(group['id'])
        selected = [item for item in items if item['group'] == group['id']]
        if not selected:
            continue
        # A carrier invoice has one VAT amount. Allocate that amount too, rather
        # than independently rounding its VAT on every selected product.
        entered = number(group.get('delivery', 0), 'Доставка закупки')
        delivery_rate = number(group.get('delivery_vat', 0), 'НДС доставки', maximum=100)
        gross = money(entered * (1 if group.get('delivery_includes_vat', True) else 1 + delivery_rate / 100))
        allocation_group = dict(group, delivery=str(gross))
        if group.get('delivery_mode') == 'manual':
            manual = allocate_delivery(selected, group)
            allocation_items = [dict(quantity=1, purchase=str(value)) for value in manual]
            allocation_group.update(delivery_mode='shared', allocation='cost', purchase_includes_vat=True)
        else:
            allocation_items = selected
        shares = allocate_delivery(allocation_items, allocation_group)
        vat_group = dict(allocation_group, delivery=str(money(gross * delivery_rate / (100 + delivery_rate))))
        vat_shares = allocate_delivery(allocation_items, vat_group)
        group['allocated_delivery'] = str(sum(shares))
        group['unallocated_delivery'] = str(money(gross - sum(shares))) if group.get('delivery_mode') != 'included' else '0.00'
        for item, share, vat_share in zip(selected, shares, vat_shares):
            vat = item.get('purchase_vat')
            if vat in (None, ''):
                vat = group.get('purchase_vat', 0)
            markup = item.get('markup')
            if markup in (None, ''):
                markup = group.get('markup', organization.get('markup', 20))
            item['result'] = calculate(item['quantity'], item['purchase'], markup, vat,
                organization['vat'], organization['deduct'], delivery=share,
                mode=item.get('mode') or group.get('mode', 'markup'), sale_price=item.get('sale_price'),
                delivery_vat=group.get('delivery_vat', 0),
                purchase_includes_vat=group.get('purchase_includes_vat', True),
                delivery_includes_vat=True, delivery_vat_amount=vat_share,
                discount=data.get('discount', 0))
            if Decimal(item['result']['profit']) < 0:
                warnings.append(f'«{item["name"]}»: продажа ниже себестоимости')
    def total(key):
        return str(sum(Decimal(x['result'][key]) for x in items))
    totals = {k: total(k) for k in ('total', 'profit', 'vat', 'cost', 'revenue',
              'input_vat', 'recoverable', 'vat_balance', 'gross_purchase', 'delivery')}
    revenue = Decimal(totals['revenue'])
    totals['margin'] = str(money(Decimal(totals['profit']) / revenue * 100)) if revenue else '0.00'
    profile = organization.get('profile', {})
    if not profile.get('tax_confirmed'):
        warnings.append('Налоговые правила фирмы не подтверждены: результат рассчитан по указанной ставке и флажку вычета. Проверьте настройки с бухгалтером.')
    if organization['deduct'] and not number(organization['vat']):
        warnings.append('Продажа без НДС при включённом вычете: подтвердите право на вычет для этой операции.')
    valid_days = number(data.get('valid_days', 5), 'Срок действия', minimum=1, maximum=365)
    if valid_days != valid_days.to_integral_value():
        raise ValueError('Срок действия должен быть целым числом дней')
    payload = dict(organization=deepcopy(organization), items=items, groups=groups,
        buyer=str(data.get('buyer', ''))[:2000], terms=str(data.get('terms', ''))[:6000],
        manager=str(data.get('manager', ''))[:2000], lead_time=str(data.get('lead_time', ''))[:300],
        discount=str(number(data.get('discount', 0), 'Скидка', maximum=100)),
        valid_days=int(valid_days),
        warnings=warnings, **totals)
    return payload
