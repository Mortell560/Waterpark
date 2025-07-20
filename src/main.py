import io
from nicegui import events, ui
from lib.watermark import add_watermark_to_pdf, add_watermark
from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF
with ui.header():
    ui.label('Waterpark').classes('text-2xl')

def preview_watermark(img: Image):
    with ui.dialog().props('full-width') as dialog:
        dialog.classes('max-w-3xl')
        dialog.open()
        with ui.card():
            ui.label('Preview Watermark').classes('text-lg')
            ui.image(img).classes('max-w-full')
            ui.button('Close', on_click=lambda: dialog.close()).props('color=primary')

def preview_pdf(imgs: list[Image]): # type: ignore
    with ui.dialog().props('full-width') as dialog:
        dialog.classes('max-w-3xl')
        dialog.open()
        with ui.card():
            ui.label('Preview PDF').classes('text-lg')
            with ui.scroll_area().classes('max-h-80'):
                # Display each image in the dialog
                for img in imgs:
                    ui.image(img).classes('max-w-full')
            ui.button('Close', on_click=lambda: dialog.close()).props('color=primary')
            
def handle_upload(e: events.UploadEventArguments):
    global watermark_text, font_size
    file = e.content
    print(f"Uploaded file type: {e.type}")
    if e.type.startswith('image/'):
        image = Image.open(file)
        watermarked = add_watermark(image, watermark_text=watermark_text.value, font_size=float(font_size.value) if font_size.value else None, color=color.value if color.value else "#CCCCCC")
        preview_watermark(watermarked) if preview.value else None
        bytes_img = io.BytesIO()
        watermarked.save(bytes_img, format='JPEG')
        watermarked = bytes_img.getvalue()

    elif e.type == 'application/pdf':
        watermarked, images = add_watermark_to_pdf(file.read(), watermark_text=watermark_text.value, font_size=float(font_size.value) if font_size.value else None, color=color.value if color.value else "#CCCCCC")
        print(len(images), "pages processed")
        preview_pdf(images) if preview.value else None
        watermarked = bytes(watermarked.output())

    else:
        ui.notify('Unsupported file type', color='negative')
        return
    
    ui.download.content(watermarked, filename=f'watermarked_{e.name}')
    



ui.upload(on_upload=handle_upload, multiple=True, max_total_size=1 << 30).props('accept=.png,.jpg,.jpeg,.gif,.pdf').classes('max-w-full')

watermark_text = ui.input('Watermark Text', placeholder='Enter watermark text here', value='Sample Watermark').props('clearable').classes('w-full')
font_size = ui.input('Font Size', value=None).props('clearable').classes('w-full')
color = ui.color_input('Watermark Color', value='#CCCCCC').props('clearable').classes('w-full')
preview = ui.checkbox('Preview Watermark', value=True).props('checked').classes('w-full')


import os
ui.run(title='Waterpark', host='127.0.0.1' if not os.environ.get('HOST') else os.environ.get('HOST'), port=int(os.environ.get('PORT', 8080)), reload=os.environ.get('RELOAD', 'true').lower() == 'true')