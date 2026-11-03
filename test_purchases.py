from decimal import Decimal
import unittest
from calculations import allocate_delivery, calculate
from quote_engine import prepare_quote


class DeliveryTests(unittest.TestCase):
    def item(self, cost, quantity=1, **extra):
        return dict(name='Товар',purchase=cost,quantity=quantity,**extra)

    def test_three_supplier_real_case(self):
        groups = [dict(id='A',delivery_mode='included',delivery=500,purchase_vat=22,markup=20),
            dict(id='B',delivery_mode='shared',delivery=700,allocation='cost',purchase_vat=0,markup=20),
            dict(id='C',delivery_mode='partial',delivery=5000,allocation='cost',full_base=100000,purchase_vat=7,markup=20)]
        items = [dict(self.item(122),group='A') for _ in range(3)]
        items += [dict(self.item(100),group='B') for _ in range(7)]
        items += [dict(self.item(10000),group='C')]
        result=prepare_quote(dict(groups=groups,items=items),dict(id=1,name='Фирма',vat=22,deduct=True))
        self.assertEqual(result['delivery'],'1200.00')
        self.assertEqual([x['result']['delivery'] for x in result['items'][:3]],['0.00']*3)
        self.assertEqual(result['groups'][2]['allocated_delivery'],'500.00')
        self.assertEqual(result['groups'][2]['unallocated_delivery'],'4500.00')

    def test_rounding_preserves_full_delivery(self):
        shares=allocate_delivery([self.item(1) for _ in range(3)],dict(delivery_mode='shared',delivery='0.10',allocation='equal'))
        self.assertEqual(shares,[Decimal('.04'),Decimal('.03'),Decimal('.03')])
        self.assertEqual(sum(shares),Decimal('.10'))

    def test_partial_rounding_never_assigns_whole_invoice(self):
        shares=allocate_delivery([self.item(1),self.item(1)],dict(delivery_mode='partial',delivery=1,allocation='equal',full_base=3))
        self.assertEqual(sum(shares),Decimal('.67'))

    def test_weight_and_quantity(self):
        items=[self.item(100,quantity=2,weight=3),self.item(100,quantity=1,weight=4)]
        self.assertEqual(allocate_delivery(items,dict(delivery_mode='shared',delivery=100,allocation='weight')),[Decimal(60),Decimal(40)])
        self.assertEqual(allocate_delivery(items,dict(delivery_mode='shared',delivery=90,allocation='quantity')),[Decimal(60),Decimal(30)])

    def test_partial_base_too_small(self):
        with self.assertRaises(ValueError):
            allocate_delivery([self.item(100)],dict(delivery_mode='partial',delivery=10,allocation='cost',full_base=90))

    def test_manual_requires_exact_sum(self):
        with self.assertRaises(ValueError):
            allocate_delivery([self.item(100,delivery=9)],dict(delivery_mode='manual',delivery=10))

    def test_zero_value_goods_need_another_allocation(self):
        with self.assertRaises(ValueError):
            allocate_delivery([self.item(0)],dict(delivery_mode='shared',delivery=10,allocation='cost'))

    def test_net_purchase_and_delivery_vat(self):
        r=calculate(1,100,20,22,22,True,delivery=12.2,delivery_vat=22,purchase_includes_vat=False)
        self.assertEqual(r['gross_purchase'],'122.00')
        self.assertEqual(r['recoverable'],'24.20')
        self.assertEqual(r['cost'],'110.00')
        self.assertEqual(r['price'],'161.04')

    def test_discount_can_create_loss_warning(self):
        p=prepare_quote(dict(discount=50,items=[dict(self.item(100),markup=20,purchase_vat=0)]),dict(id=1,name='Фирма',vat=0,deduct=False))
        self.assertEqual(p['profit'],'-40.00')
        self.assertTrue(any('ниже себестоимости' in w for w in p['warnings']))

    def test_comma_decimal_input(self):
        self.assertEqual(calculate('1,5','100,00',20,0,0,False)['total'],'180.00')

    def test_real_tax_example(self):
        r=calculate(1,107000,0,7,22,True,mode='price',sale_price=122000)
        self.assertEqual(r['profit'],'0.00')
        self.assertEqual(r['input_vat'],'7000.00')
        self.assertEqual(r['vat_balance'],'15000.00')

    def test_carrier_vat_is_allocated_without_extra_cents(self):
        groups=[dict(id='A',delivery_mode='shared',allocation='equal',delivery='.10',delivery_vat=22,markup=0)]
        items=[dict(self.item(1),group='A') for _ in range(3)]
        p=prepare_quote(dict(groups=groups,items=items),dict(id=1,name='Фирма',vat=22,deduct=True))
        self.assertEqual(p['delivery'],'0.10')
        self.assertEqual(sum(Decimal(x['result']['input_delivery']) for x in p['items']),Decimal('.02'))

    def test_delivery_vat_on_top_preserves_invoice_total(self):
        groups=[dict(id='A',delivery_mode='shared',allocation='equal',delivery='.10',delivery_vat=22,
                     delivery_includes_vat=False,markup=0)]
        items=[dict(self.item(1),group='A') for _ in range(3)]
        p=prepare_quote(dict(groups=groups,items=items),dict(id=1,name='Фирма',vat=22,deduct=True))
        self.assertEqual(p['delivery'],'0.12')
        self.assertEqual(sum(Decimal(x['result']['input_delivery']) for x in p['items']),Decimal('.02'))

    def test_switching_to_manual_price_keeps_one_discount(self):
        calculated=calculate(1,100,20,0,22,False,discount=10)
        manual=calculate(1,100,20,0,22,False,discount=10,mode='price',sale_price=calculated['base_price'])
        self.assertEqual(calculated['price'],'131.76')
        self.assertEqual(manual['price'],calculated['price'])
