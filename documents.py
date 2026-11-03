"""Real downloadable PDFs, embedded Cyrillic font, optional company letterhead."""
import base64
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent


def validate_asset(value, pdf=False):
    if not value:
        return ''
    try:
        raw = base64.b64decode(value.split(',', 1)[-1], validate=True)
        if len(raw) > 5_000_000:
            raise ValueError('Файл должен быть не больше 5 МБ')
        if pdf:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) != 1:
                raise ValueError('Нужен одностраничный PDF без пароля')
            page = reader.pages[0]
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                raise ValueError('Некорректный размер PDF')
            return 'data:application/pdf;base64,' + base64.b64encode(raw).decode()
        from PIL import Image
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 16_000_000 or image.format not in ('PNG', 'JPEG'):
                raise ValueError('Нужна картинка PNG/JPEG до 16 мегапикселей')
            image.load()
            image.thumbnail((1400, 700))
            normalized = BytesIO()
            image.convert('RGBA').save(normalized, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(normalized.getvalue()).decode()
    except ValueError:
        raise
    except Exception:
        raise ValueError('Не удалось прочитать файл. Загрузите корректный PNG/JPEG или одностраничный PDF.') from None


def build_pdf(row):
    import json
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, KeepTogether
    if 'KPMaster' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('KPMaster', str(ROOT / 'assets/DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('KPMasterBold', str(ROOT / 'assets/DejaVuSans-Bold.ttf')))
    p = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
    org, profile = p['organization'], p['organization'].get('profile', {})
    color = colors.HexColor(profile.get('color', '#255b68'))
    style = ParagraphStyle('body', fontName='KPMaster', fontSize=9, leading=14, textColor=colors.HexColor('#233347'))
    small = ParagraphStyle('small', parent=style, fontSize=8, leading=11)
    heading = ParagraphStyle('heading', parent=style, fontName='KPMasterBold', fontSize=18, leading=24, spaceAfter=8)
    right = ParagraphStyle('right', parent=style, alignment=TA_RIGHT, fontName='KPMasterBold', fontSize=13, leading=19)
    def para(text, st=style):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), st)
    def rub(value):
        return f'{Decimal(str(value)):,.2f}'.replace(',', ' ').replace('.', ',') + ' ₽'
    output = BytesIO()
    blank = profile.get('letterhead', '')
    top = float(profile.get('top_mm', 65)) if blank else 16
    bottom = float(profile.get('bottom_mm', 20)) if blank else 20
    doc = SimpleDocTemplate(output, pagesize=(210*mm, 297*mm), leftMargin=16*mm, rightMargin=16*mm,
        topMargin=top*mm, bottomMargin=bottom*mm, title=f'КП-{row["id"]:04d}', author=org['name'])
    story = []
    if not blank:
        logo = profile.get('logo', '')
        if logo:
            raw = BytesIO(base64.b64decode(logo.split(',', 1)[-1]))
            image = Image(raw)
            factor = min(42*mm/image.imageWidth, 24*mm/image.imageHeight)
            image.drawWidth, image.drawHeight = image.imageWidth*factor, image.imageHeight*factor
            company = Table([[image, para(org['name'], heading)]], colWidths=[48*mm, 130*mm])
            company.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0)]))
            story.append(company)
        else:
            story.append(para(org['name'], heading))
        story.extend([para(org.get('details',''), small), Spacer(1, 8*mm)])
    story.append(para('Коммерческое предложение', heading))
    created = date.fromisoformat(row['created'])
    story.append(para(f'№ {row["id"]:04d} от {created:%d.%m.%Y}'))
    if p.get('buyer'):
        story.append(para('Для: ' + p['buyer']))
    story.append(Spacer(1, 6*mm))
    headers = ['№', 'Наименование', 'Ед.', 'Кол-во', 'Цена, ₽', 'Сумма, ₽']
    data = [[para(x, small) for x in headers]]
    for i, item in enumerate(p['items'], 1):
        name = item['name']
        lead = item.get('lead_time') or p.get('lead_time')
        if lead:
            name += '\nСрок: ' + lead
        data.append([para(i, small), para(name), para(item.get('unit','шт'), small),
                     para(item['quantity'], small), para(rub(item['result']['price']), small),
                     para(rub(item['result']['total']), small)])
    table = Table(data, colWidths=[9*mm, 73*mm, 13*mm, 19*mm, 30*mm, 34*mm], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf3f6')),
        ('LINEBELOW',(0,0),(-1,0),1,color),('LINEBELOW',(0,1),(-1,-1),.35,colors.HexColor('#dce4eb')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),8),
        ('BOTTOMPADDING',(0,0),(-1,-1),8),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)]))
    story.append(table)
    vat = p.get('vat', str(sum(Decimal(x['result']['vat']) for x in p['items'])))
    tax_text = f'В том числе НДС {org["vat"]}%: {rub(vat)}' if org['vat'] else 'Без НДС'
    ending = [Spacer(1,6*mm),para('Итого: '+rub(p['total']),right),para(tax_text),Spacer(1,6*mm)]
    if p.get('terms'):
        ending.append(para(p['terms']))
    if p.get('valid_days'):
        expiry = created + timedelta(days=int(p['valid_days']))
        ending.append(para(f'Предложение действительно до {expiry:%d.%m.%Y}.'))
    if p.get('manager'):
        ending.extend([Spacer(1,5*mm),para('Ваш менеджер: '+p['manager'])])
    story.append(KeepTogether(ending))
    def footer(canvas, document):
        if blank:
            return  # Do not overwrite the company's existing letterhead footer.
        canvas.setFont('KPMaster', 8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawRightString(194*mm, 10*mm, f'КП-{row["id"]:04d} · {document.page}')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    result = output.getvalue()
    if blank:
        from pypdf import PdfReader, PdfWriter, Transformation
        background = base64.b64decode(blank.split(',', 1)[-1])
        content = PdfReader(BytesIO(result))
        writer = PdfWriter()
        for page in content.pages:
            target = writer.add_page(page)
            background_writer = PdfWriter(clone_from=BytesIO(background))
            source = background_writer.pages[0]
            source.transfer_rotation_to_content()
            for key in ('/Annots','/AA'):
                if key in source:
                    del source[key]
            source.add_transformation(Transformation().translate(-float(source.mediabox.left),-float(source.mediabox.bottom)))
            source.add_transformation(Transformation().scale(float(page.mediabox.width)/float(source.mediabox.width),
                                                            float(page.mediabox.height)/float(source.mediabox.height)))
            from pypdf.generic import RectangleObject
            source.mediabox = RectangleObject(page.mediabox)
            source.cropbox = RectangleObject(page.mediabox)
            target.merge_page(source, over=False)
        merged = BytesIO()
        writer.write(merged)
        result = merged.getvalue()
    return result
