import asyncio
import io
import math
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pdf2image import convert_from_bytes
import piexif
from pyzbar.pyzbar import decode
import numpy as np
import random
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)


class FileInputStream:
    """Wrapper for file input stream with media type information."""
    
    def __init__(self, input_stream: io.BytesIO, media_type: str):
        self.input_stream = input_stream
        self.media_type = media_type


class PageDimension:
    """Represents page dimensions."""
    
    def __init__(self, width: int, height: int, padding: int = 0):
        self.width = width
        self.height = height
        self.padding = padding


class PdfTemplateParameters:
    """Configuration parameters for PDF generation."""
    
    def __init__(self):
        # A4 page dimensions at 128 DPI
        self.dpi = 600
        self.compression_quality = 95
        self.max_page = PageDimension(int(210 * 128 / 25.4), int(297 * 128 / 25.4))  # A4 in pixels
        self.media_box = PageDimension(self.max_page.width, self.max_page.height)


class WatermarkParameters:
    """Parameters for watermark generation."""
    
    def __init__(self, *, text: str, rotation_angle: int = -25, opacity_range: Tuple[float, float] = (0.52, 0.60),
                 blur_opacity_range: Tuple[float, float] = (0.75, 0.95), blur_radius_range: Tuple[int, int] = (45, 65),
                 spacing_range: Tuple[float, float] = (8.0, 10.0), text_lines: int = 10,
                 font_name: str = "Arial", font_size_base: int = 36, colors: Optional[List[Tuple[int, int, int, int]]] = None):
        self.text = text
        self.rotation_angle = rotation_angle
        self.opacity_range = opacity_range
        self.blur_opacity_range = blur_opacity_range
        self.blur_radius_range = blur_radius_range
        self.spacing_range = spacing_range
        self.text_lines = text_lines
        self.font_name = font_name
        self.font_size_base = font_size_base
        self.colors = colors if colors is not None else [
            (64, 64, 64, 255),      # Dark gray
            (32, 32, 32, 220),      # Darker gray
            (0, 0, 0, 110),         # Black with transparency
            (0, 0, 91, 170),        # Dark blue with transparency
            (255, 0, 0, 170)        # Red with transparency
        ]

class BOPdfDocumentTemplate:
    """
    Generates watermarked PDF documents from images and PDFs.
    Applies a rotated, blurred watermark with QR code detection.
    """
    
    DEFAULT_WATERMARK = "  DOCUMENTS EXCLUSIVEMENT DESTINÉS À LA LOCATION IMMOBILIÈRE     "
    WATERMARK_ROTATION_ANGLE = -25
    WATERMARK_OPACITY_RANGE = (0.52, 0.60)
    WATERMARK_BLUR_OPACITY_RANGE = (0.75, 0.95)
    WATERMARK_BLUR_RADIUS_RANGE = (45, 65)
    WATERMARK_SPACING_RANGE = (8.0, 10.0)
    WATERMARK_TEXT_LINES = 10
    WATERMARK_FONT_NAME = "Arial"
    WATERMARK_FONT_SIZE_BASE = 36
    QR_CODE_BORDER_SIZE = 20
    
    COLORS = [
        (64, 64, 64, 255),      # Dark gray
        (32, 32, 32, 220),      # Darker gray
        (0, 0, 0, 110),         # Black with transparency
        (0, 0, 91, 170),        # Dark blue with transparency
        (255, 0, 0, 170)        # Red with transparency
    ]
    
    def __init__(self, watermark_params: Optional[WatermarkParameters] = None, use_colors: bool = False, use_distortion: bool = False, use_blur: bool = True):
        """
        Initialize the PDF template.
        
        Args:
            watermark_params: Watermark parameters object (uses default if not provided)
            use_colors: Whether to use multiple colors for watermark
            use_distortion: Whether to apply distortion filter to watermark
            use_blur: Whether to add a blurred glow behind the watermark
        """
        self.params = PdfTemplateParameters()
        if watermark_params is None:
            self.watermark_params = WatermarkParameters(text=self.DEFAULT_WATERMARK)
        else:
            self.watermark_params = watermark_params
        self.use_colors = use_colors
        self.use_distortion = use_distortion
        self.use_blur = use_blur
    
    async def render(self, file_input_streams: List[FileInputStream], 
                     watermark_text: Optional[str] = None) -> io.BytesIO:
        """
        Main render method that converts files to watermarked PDF.
        
        Args:
            file_input_streams: List of file input streams (images/PDFs)
            watermark_text: Custom watermark text (uses default if not provided)
            
        Returns:
            BytesIO object containing the PDF
        """
        if watermark_text is None:
            watermark_text = self.watermark_params.text
        
        watermark_to_apply = watermark_text.strip() + "   " if watermark_text.strip() else self.watermark_params.text
        
        # Convert all files to images
        images = []
        for file_stream in file_input_streams:
            try:
                converted = await self._convert_to_images(file_stream)
                images.extend(converted)
            except Exception:
                logger.exception("Error converting file")
                continue

        if not images:
            raise ValueError("No images could be produced from the provided inputs (conversion failed).")
        
        # Process images: crop -> fit to page -> apply watermark
        processed_images = []
        for image in images:
            try:
                cropped = self._smart_crop(image)
                if cropped is None:
                    continue
                fitted = self._fit_image_to_page(cropped)
                watermarked = await self._apply_watermark(fitted, watermark_to_apply)
                processed_images.append(watermarked)
            except Exception:
                logger.exception("Error processing image")
                continue

        if not processed_images:
            raise ValueError("All images failed during processing/watermarking; see logs for details.")
        
        # Create PDF from processed images
        return await self._create_pdf_from_images(processed_images)
    
    async def _convert_to_images(self, file_input_stream: FileInputStream) -> List[Image.Image]:
        """
        Convert PDF or image file to list of PIL Images.
        
        Args:
            file_input_stream: Input file stream
            
        Returns:
            List of PIL Image objects
        """
        media_type = file_input_stream.media_type.lower()
        
        if "pdf" in media_type:
            # Convert PDF to images in thread pool
            file_input_stream.input_stream.seek(0)
            images = await asyncio.to_thread(
                convert_from_bytes,
                file_input_stream.input_stream.read(),
                self.params.dpi
            )
            return images
        else:
            # Handle image file with orientation
            file_input_stream.input_stream.seek(0)
            image = self._create_image_with_orientation(file_input_stream.input_stream)
            return [image] if image else []
    
    def _create_image_with_orientation(self, input_stream: io.BytesIO) -> Optional[Image.Image]:
        """
        Load image and apply EXIF orientation.
        
        Args:
            input_stream: Input stream containing image data
            
        Returns:
            PIL Image with proper orientation applied
        """
        try:
            input_stream.seek(0)
            image = Image.open(input_stream)
            image = image.convert("RGB")
            
            # Try to read EXIF orientation
            try:
                input_stream.seek(0)
                exif_bytes = input_stream.read()
                exif_data = piexif.load(exif_bytes)
                orientation_tag = piexif.ImageIFD.Orientation
                
                if orientation_tag in exif_data["0th"]:
                    orientation = exif_data["0th"][orientation_tag]
                    image = self._apply_exif_orientation(image, orientation)
            except Exception as e:
                logger.warning(f"Could not read EXIF orientation: {e}")
            
            return image
        except Exception as e:
            logger.error(f"Error creating image with orientation: {e}")
            return None
    
    @staticmethod
    def _apply_exif_orientation(image: Image.Image, orientation: int) -> Image.Image:
        """
        Apply EXIF orientation transformation to image.
        
        Args:
            image: PIL Image object
            orientation: EXIF orientation value (1-8)
            
        Returns:
            Transformed image
        """
        orientation_map = {
            2: (Image.Transpose.FLIP_LEFT_RIGHT,),
            3: (Image.Transpose.ROTATE_180,),
            4: (Image.Transpose.FLIP_TOP_BOTTOM,),
            5: (Image.Transpose.FLIP_TOP_BOTTOM, Image.Transpose.ROTATE_90),
            6: (Image.Transpose.ROTATE_270,),
            7: (Image.Transpose.FLIP_TOP_BOTTOM, Image.Transpose.ROTATE_270),
            8: (Image.Transpose.ROTATE_90,),
        }
        
        if orientation in orientation_map:
            for transform in orientation_map[orientation]:
                image = image.transpose(transform)
        
        return image
    
    def _smart_crop(self, image: Image.Image) -> Optional[Image.Image]:
        """
        Apply smart crop if needed (optional customization point).
        By default, returns image unchanged.
        
        Args:
            image: PIL Image object
            
        Returns:
            Cropped image or original if no cropping needed
        """
        return image
    
    async def _apply_watermark(self, image: Image.Image, watermark_text: str) -> Image.Image:
        """
        Apply watermark to image with blur and rotation effects.
        
        Args:
            image: Input PIL Image
            watermark_text: Text to use for watermark
            
        Returns:
            Watermarked image
        """
        return await asyncio.to_thread(self._apply_watermark_sync, image, watermark_text)
    
    def _apply_watermark_sync(self, image: Image.Image, watermark_text: str) -> Image.Image:
        """
        Synchronous watermark application (runs in thread pool).
        
        Args:
            image: Input PIL Image
            watermark_text: Text to use for watermark
            
        Returns:
            Watermarked image
        """
        try:
            width, height = image.size
            diagonal = int(math.sqrt(width * width + height * height))
            
            # Create watermark layer
            watermark_layer = Image.new("RGBA", (diagonal, diagonal), (0, 0, 0, 0))
            watermark_draw = ImageDraw.Draw(watermark_layer)
            
            # Base watermark text for tiling across the line
            base_text = (watermark_text.strip() + "   ") if watermark_text.strip() else self.watermark_params.text
            
            # Calculate font size based on image width
            font_size = max(12, int(self.watermark_params.font_size_base * width / self.params.max_page.width))
            font = self._load_font(font_size)
            
            # Get random opacity for main watermark layer
            main_opacity = random.uniform(*self.watermark_params.opacity_range)
            
            # Get random spacing between text lines
            space_between = diagonal / random.uniform(*self.watermark_params.spacing_range)
            
            # Draw tiled watermark text across each line
            text_width = watermark_draw.textlength(base_text, font=font)
            if text_width <= 0:
                text_width = max(1, int(font_size * len(base_text) * 0.6))

            y_offset = space_between
            for i in range(self.watermark_params.text_lines):
                if self.use_colors:
                    color = self.watermark_params.colors[random.randint(0, len(self.watermark_params.colors) - 1)]
                else:
                    # Dark gray
                    color = (64, 64, 64, int(255 * main_opacity))

                x_offset = -diagonal
                while x_offset < diagonal * 2:
                    watermark_draw.text(
                        (int(x_offset), int(y_offset)),
                        base_text,
                        fill=color,
                        font=font
                    )
                    x_offset += text_width
                y_offset += space_between
            if self.use_blur:
                # Create blurred layer from the sharp watermark
                blur_radius = random.randint(*self.watermark_params.blur_radius_range)
                blurred_layer = watermark_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))

                # Apply blur opacity by scaling alpha channel
                blur_opacity = random.uniform(*self.watermark_params.blur_opacity_range)
                alpha = blurred_layer.getchannel("A")
                alpha = alpha.point(lambda p: int(p * blur_opacity))
                blurred_layer.putalpha(alpha)
            else:
                blurred_layer = None

            # Apply optional distortion to the sharp watermark only
            if self.use_distortion:
                watermark_layer = self._apply_distortion_filter(watermark_layer)

            # Rotate watermark layers
            rotated_layer = watermark_layer.rotate(
                self.watermark_params.rotation_angle,
                center=(diagonal / 2, diagonal / 2),
                expand=False
            )
            rotated_blur = None
            if blurred_layer is not None:
                rotated_blur = blurred_layer.rotate(
                    self.watermark_params.rotation_angle,
                    center=(diagonal / 2, diagonal / 2),
                    expand=False
                )
            
            # Crop rotated layer to image size
            left = (diagonal - width) // 2
            top = (diagonal - height) // 2
            right = left + width
            bottom = top + height
            cropped_rotated = rotated_layer.crop((left, top, right, bottom))
            if rotated_blur is not None:
                cropped_blur = rotated_blur.crop((left, top, right, bottom))
                cropped_rotated = Image.alpha_composite(cropped_blur, cropped_rotated)
            
            # Detect and clear QR codes
            qr_codes = self._detect_qr_codes(image)
            logger.info(f"[QR_CODE] QR codes detected: {len(qr_codes)}")
            
            if qr_codes:
                wm_alpha = cropped_rotated.getchannel("A")
                alpha_draw = ImageDraw.Draw(wm_alpha)

                for x, y, w, h in qr_codes:
                    qr_x = max(x - self.QR_CODE_BORDER_SIZE, 0)
                    qr_y = max(y - self.QR_CODE_BORDER_SIZE, 0)
                    qr_x2 = min(x + w + self.QR_CODE_BORDER_SIZE, width)
                    qr_y2 = min(y + h + self.QR_CODE_BORDER_SIZE, height)
                    alpha_draw.rectangle([qr_x, qr_y, qr_x2, qr_y2], fill=0)

                cropped_rotated.putalpha(wm_alpha)
            
            # Composite watermark onto original image
            result = image.convert("RGBA")
            result = Image.alpha_composite(result, cropped_rotated)
            result = result.convert("RGB")
            
            return result
        except Exception as e:
            logger.exception("Error applying watermark")
            raise RuntimeError(f"Unable to apply watermark: {e}")

    def _load_font(self, font_size: int) -> ImageFont.ImageFont:
        """
        Load a TrueType font; fall back to a bundled font for clarity.
        """
        try:
            font_path = Path(__file__).resolve().parents[1] / "fonts" / "Arial.ttf"
            if font_path.exists():
                return ImageFont.truetype(str(font_path), font_size)
        except Exception:
            pass
        try:
            return ImageFont.truetype(self.watermark_params.font_name, font_size)
        except Exception:
            try:
                return ImageFont.truetype("DejaVuSans.ttf", font_size)
            except Exception:
                return ImageFont.load_default()
    
    def _apply_watermark_recursive_call(self, image: Image.Image, watermark_text: str) -> Image.Image:
        return self._apply_watermark_sync(image, watermark_text)
    
    def _apply_distortion_filter(self, image: Image.Image) -> Image.Image:
        """
        Apply wave/ripple distortion filter to image.
        
        Args:
            image: PIL Image object
            
        Returns:
            Distorted image
        """
        width, height = image.size
        pixels = np.array(image)

        # Wave parameters tuned for readability
        amplitude_x = max(1, int(min(width, height) * 0.004))
        amplitude_y = max(1, int(min(width, height) * 0.004))
        wavelength_x = max(60, int(min(width, height) * 0.24))
        wavelength_y = max(60, int(min(width, height) * 0.24))

        distorted = np.empty_like(pixels)
        for y in range(height):
            offset = int(amplitude_x * math.sin(2 * math.pi * y / wavelength_x))
            distorted[y] = np.roll(pixels[y], shift=offset, axis=0)

        # Second pass: vertical ripple by shifting columns
        distorted = np.transpose(distorted, (1, 0, 2))
        for x in range(width):
            offset = int(amplitude_y * math.sin(2 * math.pi * x / wavelength_y))
            distorted[x] = np.roll(distorted[x], shift=offset, axis=0)
        distorted = np.transpose(distorted, (1, 0, 2))

        return Image.fromarray(distorted, mode=image.mode)
    
    def _detect_qr_codes(self, image: Image.Image) -> List[Tuple[int, int, int, int]]:
        """
        Detect QR codes in image.
        
        Args:
            image: PIL Image object
            
        Returns:
            List of (x, y, width, height) tuples for detected QR codes
        """
        try:
            # Convert to grayscale for QR detection
            gray_image = image.convert("L")
            decoded_objects = decode(gray_image)
            
            qr_boxes = []
            for obj in decoded_objects:
                x, y = obj.rect.left, obj.rect.top
                w, h = obj.rect.width, obj.rect.height
                qr_boxes.append((x, y, w, h))
            
            return qr_boxes
        except Exception as e:
            logger.error(f"QR code detection failed: {e}")
            return []
    
    def _fit_image_to_page(self, image: Image.Image) -> Image.Image:
        """
        Fit image to A4 page dimensions with white background.
        
        Args:
            image: Input PIL Image
            
        Returns:
            Image fitted to page with white padding
        """
        try:
            img_width, img_height = image.size
            page_width, page_height = self.params.media_box.width, self.params.media_box.height

            # Scale image to fit within the page while preserving aspect ratio
            scale = min(page_width / img_width, page_height / img_height)
            new_img_width = max(1, int(img_width * scale))
            new_img_height = max(1, int(img_height * scale))

            if (new_img_width, new_img_height) != (img_width, img_height):
                image = image.resize((new_img_width, new_img_height), Image.Resampling.LANCZOS)

            # Create white page background
            result = Image.new("RGB", (page_width, page_height), "white")

            # Center the image on the page
            offset_x = (page_width - image.width) // 2
            offset_y = (page_height - image.height) // 2
            result.paste(image, (offset_x, offset_y))

            return result
        except Exception as e:
            logger.error(f"Error fitting image to page: {e}")
            raise RuntimeError(f"Unable to fit image to page: {e}")
    
    async def _create_pdf_from_images(self, images: List[Image.Image]) -> io.BytesIO:
        """
        Create PDF document from list of images.
        
        Args:
            images: List of PIL Image objects
            
        Returns:
            BytesIO containing PDF data
        """
        if not images:
            raise ValueError("No images to convert to PDF")
        
        return await asyncio.to_thread(self._create_pdf_from_images_sync, images)
    
    def _create_pdf_from_images_sync(self, images: List[Image.Image]) -> io.BytesIO:
        """
        Synchronous PDF creation (runs in thread pool).
        
        Args:
            images: List of PIL Image objects
            
        Returns:
            BytesIO containing PDF data
        """
        try:
            pdf_buffer = io.BytesIO()
            
            # Convert images to RGB mode if needed
            rgb_images = []
            for img in images:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                rgb_images.append(img)
            
            # Save as PDF using PIL
            rgb_images[0].save(
                pdf_buffer,
                format="PDF",
                save_all=True,
                append_images=rgb_images[1:] if len(rgb_images) > 1 else [],
                quality=self.params.compression_quality
            )
            
            pdf_buffer.seek(0)
            return pdf_buffer
        except Exception as e:
            logger.error(f"Error creating PDF: {e}")
            raise RuntimeError(f"Unable to create PDF: {e}")
    
    async def sign_pdf(self, pdf_buffer: io.BytesIO, cert_path: str, key_path: str, metadata: signers.PdfSignatureMetadata) -> io.BytesIO:
        """
        Sign a PDF with a certificate and private key.
        
        Args:
            pdf_buffer: BytesIO containing unsigned PDF
            cert_path: Path to PEM certificate file
            key_path: Path to PEM private key file
            metadata: Metadata for the signature
        Returns:
            BytesIO containing signed PDF
        """
        return await asyncio.to_thread(self._sign_pdf_sync, pdf_buffer, cert_path, key_path, metadata)
    
    def _sign_pdf_sync(self, pdf_buffer: io.BytesIO, cert_path: str, key_path: str, metadata: signers.PdfSignatureMetadata) -> io.BytesIO:
        """
        Synchronous PDF signing (runs in thread pool).
        
        Args:
            pdf_buffer: BytesIO containing unsigned PDF
            cert_path: Path to PEM certificate file
            key_path: Path to PEM private key file
            metadata: Metadata for the signature
        Returns:
            BytesIO containing signed PDF
        """
        try:
            pdf_buffer.seek(0)

            # Normalize PDFs to avoid invalid xref/object generations
            # Use pypdf to rebuild the PDF without creating signature artifacts
            reader = PdfReader(pdf_buffer)
            writer = PdfWriter()
            
            # Copy all pages to the writer
            for page in reader.pages:
                writer.add_page(page)
            
            # Write to a clean buffer
            sanitized_pdf = io.BytesIO()
            writer.write(sanitized_pdf)
            sanitized_pdf.seek(0)

            # Now sign the sanitized PDF
            incremental_writer = IncrementalPdfFileWriter(sanitized_pdf)

            # Create signer with cert and key
            signer = signers.SimpleSigner.load(
                key_path,
                cert_path,
                key_passphrase=None,  # Set to password bytes if needed
                ca_chain_files=None
            )

            # If certifying, ensure proper certification permissions are set
            if metadata.certify:
                from pyhanko.sign.fields import MDPPerm
                # Set to allow form filling and annotations (level 2)
                # You can change to MDPPerm.NO_CHANGES (level 1) or MDPPerm.ANNOTATE (level 3)
                if metadata.docmdp_permissions is None:
                    metadata = signers.PdfSignatureMetadata(
                        field_name=metadata.field_name,
                        certify=True,
                        docmdp_permissions=MDPPerm.FILL_FORMS,  # Level 2: allow form filling
                        location=metadata.location,
                        reason=metadata.reason,
                        name=metadata.name,
                    )

            # Sign the PDF
            signed_out = io.BytesIO()
            signers.sign_pdf(
                incremental_writer,
                signature_meta=metadata,
                signer=signer,
                output=signed_out
            )
            signed_out.seek(0)
            
            return signed_out
        except Exception as e:
            logger.error(f"Error signing PDF: {e}")
            raise RuntimeError(f"Unable to sign PDF: {e}")


# Example usage
if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Create watermark parameters
    watermark_params = WatermarkParameters(
        text="  DOCUMENTS EXCLUSIF  ",
        rotation_angle=-25,
        opacity_range=(0.52, 0.60),
        blur_opacity_range=(0.75, 0.95),
        blur_radius_range=(45, 65),
        spacing_range=(8.0, 10.0),
        text_lines=10,
        font_name="Arial",
        font_size_base=36
    )
    
    # Create template
    template = BOPdfDocumentTemplate(watermark_params=watermark_params, use_colors=True, use_distortion=False, use_blur=False)
    
    # Example: Load PDF, create watermarked PDF, and sign it
    with open("image.png", "rb") as f:
        file_stream = FileInputStream(io.BytesIO(f.read()), "image/png")
        
        pdf_result = template.render([file_stream], "Copie CNI - 2022-2023")

        signed_pdf = template.sign_pdf(
            pdf_result,
            cert_path="./certs/vendredicorp.crt",
            key_path="./certs/client1.key",
            metadata=signers.PdfSignatureMetadata(
                field_name="Signature1",
                certify=True,
                location="Location",
                reason="Document signed by BO",
                name="BO"
            )
        )

        # Save signed result
        with open("output.signed.pdf", "wb") as out:
            out.write(signed_pdf.getvalue())

