import unittest
from calculations import calculate

class CalculationTests(unittest.TestCase):
    def test_deductible_vat(self):
        r = calculate(2, 122, 20, 22, 22, True)
        self.assertEqual(r['price'], '146.40')
        self.assertEqual(r['profit'], '40.00')
        self.assertEqual(r['vat'], '52.80')

    def test_non_deductible_vat(self):
        r = calculate(1, 107, 20, 7, 5, False)
        self.assertEqual(r['price'], '134.82')
        self.assertEqual(r['profit'], '21.40')

    def test_no_vat(self):
        self.assertEqual(calculate(3, 100, 20, 0, 0, False)['total'], '360.00')

    def test_invalid_quantity(self):
        with self.assertRaises(ValueError):
            calculate(0, 100, 20, 0, 22, True)

    def test_nonfinite(self):
        with self.assertRaises(ValueError):
            calculate(1, 'NaN', 20, 0, 22, True)

if __name__ == '__main__':
    unittest.main()
