from PIL import Image, ImageDraw, ImageFont, ImageColor
from fpdf import FPDF

def add_watermark(image: Image, watermark_text: str, font_size: float = None, color: str = "#CCCCCC", transparency: float = 0.5) -> Image:
    # Open the original image
    original = image.copy()

    # Create a new image for the watermark
    width, height = original.size
    watermark = Image.new("RGBA", original.size)

    # Initialize the drawing context
    draw = ImageDraw.Draw(watermark)

    # Load a font with size relative to the image size
    font = ImageFont.load_default(size=font_size if font_size else float(min(width, height) * 0.02))  # 1% of the smaller dimension

    # Calculate text size
    bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Repeat watermark text all over the image
    x_step = text_width + 40  # horizontal spacing
    y_step = text_height + 40  # vertical spacing
    color_rgb = ImageColor.getcolor(color, "RGB")

    for y in range(0, height, y_step):
        for x in range(0, width, x_step):
            draw.text((x, y), watermark_text, fill=color_rgb + (int(255 * transparency),), font=font)

    # Combine the original image with the watermark
    watermarked = Image.alpha_composite(original.convert("RGBA"), watermark)

    # Return the result
    return watermarked.convert("RGB")

def add_watermark_to_pdf(pdf_file: bytes, watermark_text: str, font_size: int = None, color: str = "#CCCCCC", transparency: float = 0.5) -> tuple[FPDF, list[Image]]: # type: ignore
    """Function to add a watermark to each page of a PDF file. It should return the PDF as is"""
    from pdf2image import convert_from_bytes

    # Convert PDF to images
    images = convert_from_bytes(pdf_file)

    # Create a new PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    imgs = []

    for image in images:
        # Add a new page
        pdf.add_page()

        # Add watermark to the image
        watermarked_image = add_watermark(image, watermark_text, font_size, color, transparency)
        imgs.append(watermarked_image)


        # Add the image to the PDF
        pdf.image(watermarked_image, x=0, y=0, w=210, h=297)  # A4 size

    return pdf, imgs

if __name__ == "__main__":
    input_path = "input.jpg"  # Replace with your input image path
    output_path = "output.jpg"  # Replace with your desired output path
    watermark_text = "Copie CNI 23232/232/3232 à l'attention de Synchrotron SOLEIL"  # Replace with your watermark text

    image = Image.open(input_path)
    watermarked_image = add_watermark(image, watermark_text)
    watermarked_image.save(output_path)
    print(f"Watermark added to {output_path}")

    # Example usage for PDF
    pdf_input_path = "test.pdf"  # Replace with your input PDF path
    with open(pdf_input_path, 'rb') as pdf_file:
        pdf_content = pdf_file.read()
    pdf_output, images = add_watermark_to_pdf(pdf_content, watermark_text, transparency=0.5)
    pdf_output_path = "output.pdf"  # Replace with your desired output PDF path
    pdf_output.output(pdf_output_path)
    print(f"Watermark added to {pdf_output_path}")