import asyncio
import io
import os
from nicegui import events, ui
from pyhanko.sign import signers
from starlette.formparsers import MultiPartParser

from lib.watermark import BOPdfDocumentTemplate, FileInputStream, WatermarkParameters

MultiPartParser.spool_max_size = 1 << 26

with ui.header():
    ui.label('Waterpark').classes('text-2xl')

last_pdf_bytes: bytes | None = None
last_pdf_name: str | None = None


def _build_template() -> BOPdfDocumentTemplate:
    font_size_value = None
    if font_size.value:
        try:
            font_size_value = int(font_size.value)
        except ValueError:
            font_size_value = None

    params = WatermarkParameters(
        text=watermark_text.value or BOPdfDocumentTemplate.DEFAULT_WATERMARK,
        font_size_base=font_size_value if font_size_value else WatermarkParameters(text="tmp").font_size_base,
    )
    return BOPdfDocumentTemplate(
        watermark_params=params,
        use_colors=use_colors.value,
        use_distortion=use_distortion.value,
        use_blur=use_blur.value,
    )


async def handle_upload(e: events.UploadEventArguments):
    global last_pdf_bytes, last_pdf_name
    file_bytes = await e.file.read()
    if not file_bytes:
        ui.notify('Empty file upload', color='negative')
        return

    content_type = e.file.content_type or ''
    if not (content_type.startswith('image/') or content_type == 'application/pdf'):
        ui.notify('Unsupported file type', color='negative')
        return

    template = _build_template()
    file_stream = FileInputStream(io.BytesIO(file_bytes), content_type)

    try:
        pdf_buffer = await template.render(
            [file_stream],
            watermark_text=watermark_text.value,
        )
    except Exception as exc:
        ui.notify(f'Watermarking failed: {exc}', color='negative')
        return

    last_pdf_bytes = pdf_buffer.getvalue()
    base_name = e.file.name.rsplit('.', 1)[0] if e.file.name else 'document'
    last_pdf_name = f'watermarked_{base_name}.pdf'
    if sign_on_upload.value:
        if not cert_path or not key_path:
            ui.notify('Certificate and key paths are required', color='negative')
            return
        if sign_pass and (not user_sign_pass.value or user_sign_pass.value != sign_pass):
            ui.notify('Invalid signing password', color='negative')
            return

        metadata = signers.PdfSignatureMetadata(
            field_name=signature_field.value or 'Signature1',
            certify=certify.value,
            location=signature_location.value or None,
            reason=signature_reason.value or None,
            name=signature_name.value or None,
        )

        try:
            signed_pdf = await template.sign_pdf(
                io.BytesIO(last_pdf_bytes),
                cert_path,
                key_path,
                metadata,
            )
        except Exception as exc:
            ui.notify(f'Signing failed: {exc}', color='negative')
            return

        signed_name = (last_pdf_name or 'watermarked.pdf').replace('.pdf', '.signed.pdf')
        ui.download.content(signed_pdf.getvalue(), filename=signed_name)
        ui.notify('Signed PDF ready', color='positive')
        return

    ui.download.content(last_pdf_bytes, filename=last_pdf_name)
    ui.notify('Watermarked PDF ready', color='positive')


ui.upload(on_upload=handle_upload, multiple=True, max_total_size=1 << 30).props(
    'accept=.png,.jpg,.jpeg,.gif,.pdf'
).classes('w-full')

watermark_text = ui.input(
    'Watermark Text',
    placeholder='Enter watermark text here',
    value='Sample Watermark',
).props('clearable').classes('w-full')
font_size = ui.input('Font Size (base)', value=None).props('clearable').classes('w-full')

use_colors = ui.checkbox('Use colors in watermark', value=False).props('checked').classes('w-full')
use_distortion = ui.checkbox('Use distortion filter', value=False).props('checked').classes('w-full')
use_blur = ui.checkbox('Use blur glow', value=True).props('checked').classes('w-full')

ui.separator()
ui.label('PDF Signing').classes('text-lg')
cert_path = os.environ.get('CERT_PATH', '')
key_path = os.environ.get('KEY_PATH', '')
sign_pass = os.environ.get('SIGN_PASS', '')
user_sign_pass = ui.input('Sign password', password=True).props('clearable').classes('w-full')
signature_field = ui.input('Signature field name', value='Signature1').props('clearable').classes('w-full')
signature_name = ui.input('Signer name', placeholder='Your name').props('clearable').classes('w-full')
signature_reason = ui.input('Signing reason', placeholder='Reason for signing').props('clearable').classes('w-full')
signature_location = ui.input('Signing location', placeholder='Location').props('clearable').classes('w-full')
certify = ui.checkbox('Certify PDF', value=True).props('checked').classes('w-full')
sign_on_upload = ui.checkbox('Sign on upload', value=False).props('checked').classes('w-full')


ui.run(
    title='Waterpark',
    host='0.0.0.0' if not os.environ.get('HOST') else os.environ.get('HOST'),
    port=int(os.environ.get('PORT', 8080)),
    reload=os.environ.get('RELOAD', 'true').lower() == 'true',
)