import base64
from io import BytesIO
import json
import unittest
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from documents import build_pdf, validate_asset
from quote_engine import prepare_quote


class DocumentTests(unittest.TestCase):
    def row(self, count=1, profile=None):
        org=dict(id=1,name='ООО Стройтест',details='ИНН 1234567890',vat=22,deduct=True,profile=profile or {})
        data=dict(buyer='Клиент <Тест>',manager='Анна +7999',lead_time='3 рабочих дня',valid_days=5,
                  terms='Оплата: 100% предоплата',items=[dict(name=f'Цемент М500 / позиция {i}',quantity=2,
                  purchase=122,purchase_vat=22,markup=20,unit='меш') for i in range(count)])
        return dict(id=42,created='2026-11-03',payload=json.dumps(prepare_quote(data,org)))

    def test_real_pdf_cyrillic_and_internal_privacy(self):
        pdf=build_pdf(self.row())
        self.assertTrue(pdf.startswith(b'%PDF-'))
        text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        for term in ['ООО Стройтест','Цемент М500','Анна','3 рабочих дня','292,80','08.11.2026']:
            self.assertIn(term,text)
        for term in ['Закупка','Наценка','Себестоимость','Прибыль','122,00']:
            self.assertNotIn(term,text)

    def test_multipage_letterhead_on_every_page(self):
        buf=BytesIO();c=canvas.Canvas(buf,pagesize=(595.28,841.89));c.drawString(50,810,'COMPANY LETTERHEAD');c.save()
        blank=validate_asset(base64.b64encode(buf.getvalue()).decode(),pdf=True)
        pdf=build_pdf(self.row(100,dict(letterhead=blank,top_mm=50,bottom_mm=25)))
        pages=PdfReader(BytesIO(pdf)).pages
        self.assertGreater(len(pages),2)
        for page in pages:
            self.assertIn('COMPANY LETTERHEAD',page.extract_text())
            if 'Цемент М500' in page.extract_text():
                self.assertIn('Наименование',page.extract_text())
        self.assertIn('Наименование',pages[1].extract_text())

    def test_invalid_asset_and_encrypted_pdf_rejected(self):
        with self.assertRaises(ValueError):
            validate_asset('not an image')
        with self.assertRaises(ValueError):
            validate_asset(base64.b64encode(b'broken PDF').decode(),pdf=True)

    def test_logo_normalized_to_safe_png(self):
        from PIL import Image
        buf=BytesIO();Image.new('RGB',(100,40),'green').save(buf,'JPEG')
        result=validate_asset(base64.b64encode(buf.getvalue()).decode())
        self.assertTrue(result.startswith('data:image/png;base64,'))
        pdf=build_pdf(self.row(profile={'logo':result}))
        self.assertTrue(pdf.startswith(b'%PDF-'))
