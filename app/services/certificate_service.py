"""
Certificate PDF Generator
Uses reportlab to create professional PDF certificates
"""
import os
import uuid
from io import BytesIO
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def generate_certificate_pdf(
    student_name: str,
    course_title: str,
    cert_number: str,
    issued_date: Optional[datetime] = None,
    instructor_name: Optional[str] = None,
    platform_name: str = "Intellect",
    output_dir: str = "./uploads/certificates",
) -> Optional[str]:
    """
    Generate a PDF certificate and save to disk.
    Returns the filename (relative to output_dir), or None on failure.
    """
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.units import cm, mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.pdfgen import canvas

        os.makedirs(output_dir, exist_ok=True)
        filename = f"cert_{cert_number.lower().replace('-', '_')}.pdf"
        filepath = os.path.join(output_dir, filename)

        if issued_date is None:
            issued_date = datetime.utcnow()

        # Page setup
        page_width, page_height = landscape(A4)
        c = canvas.Canvas(filepath, pagesize=landscape(A4))

        # Background gradient effect
        c.setFillColor(colors.HexColor("#f8faff"))
        c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

        # Decorative border
        c.setStrokeColor(colors.HexColor("#4A90D9"))
        c.setLineWidth(4)
        c.rect(15*mm, 15*mm, page_width - 30*mm, page_height - 30*mm, fill=0, stroke=1)
        c.setLineWidth(1.5)
        c.setStrokeColor(colors.HexColor("#2c6fad"))
        c.rect(18*mm, 18*mm, page_width - 36*mm, page_height - 36*mm, fill=0, stroke=1)

        # Corner decorations
        corner_size = 10*mm
        for x, y in [(20*mm, 20*mm), (page_width - 20*mm, 20*mm),
                     (20*mm, page_height - 20*mm), (page_width - 20*mm, page_height - 20*mm)]:
            c.setFillColor(colors.HexColor("#4A90D9"))
            c.circle(x, y, 3*mm, fill=1, stroke=0)

        # Platform logo / name
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(colors.HexColor("#4A90D9"))
        c.drawCentredString(page_width / 2, page_height - 45*mm, f"🎓  {platform_name}")

        # Tagline
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#6c757d"))
        c.drawCentredString(page_width / 2, page_height - 52*mm, "Your Digital Learning Companion")

        # Divider
        c.setStrokeColor(colors.HexColor("#dee2e6"))
        c.setLineWidth(1)
        c.line(50*mm, page_height - 57*mm, page_width - 50*mm, page_height - 57*mm)

        # "Certificate of Completion" title
        c.setFont("Helvetica-Bold", 32)
        c.setFillColor(colors.HexColor("#1a3a5c"))
        c.drawCentredString(page_width / 2, page_height - 75*mm, "Certificate of Completion")

        # "This is to certify that"
        c.setFont("Helvetica", 14)
        c.setFillColor(colors.HexColor("#6c757d"))
        c.drawCentredString(page_width / 2, page_height - 88*mm, "This is to certify that")

        # Student name
        c.setFont("Helvetica-Bold", 38)
        c.setFillColor(colors.HexColor("#2c6fad"))
        c.drawCentredString(page_width / 2, page_height - 105*mm, student_name)

        # Underline for name
        name_width = c.stringWidth(student_name, "Helvetica-Bold", 38)
        c.setStrokeColor(colors.HexColor("#4A90D9"))
        c.setLineWidth(1.5)
        c.line(
            page_width / 2 - name_width / 2 - 5*mm,
            page_height - 108*mm,
            page_width / 2 + name_width / 2 + 5*mm,
            page_height - 108*mm,
        )

        # "has successfully completed"
        c.setFont("Helvetica", 14)
        c.setFillColor(colors.HexColor("#6c757d"))
        c.drawCentredString(page_width / 2, page_height - 118*mm, "has successfully completed the course")

        # Course title
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(colors.HexColor("#1a3a5c"))
        c.drawCentredString(page_width / 2, page_height - 133*mm, f'"{course_title}"')

        # Bottom section — date, cert number, instructor
        bottom_y = 35*mm
        col1_x = page_width * 0.22
        col2_x = page_width * 0.50
        col3_x = page_width * 0.78

        # Lines
        c.setStrokeColor(colors.HexColor("#4A90D9"))
        c.setLineWidth(1.5)
        line_width = 55*mm
        for cx in [col1_x, col2_x, col3_x]:
            c.line(cx - line_width / 2, bottom_y + 8*mm, cx + line_width / 2, bottom_y + 8*mm)

        # Labels
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor("#1a3a5c"))
        c.drawCentredString(col1_x, bottom_y + 3*mm, issued_date.strftime("%B %d, %Y"))
        c.drawCentredString(col2_x, bottom_y + 3*mm, cert_number)
        c.drawCentredString(col3_x, bottom_y + 3*mm, instructor_name or platform_name)

        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#6c757d"))
        c.drawCentredString(col1_x, bottom_y - 2*mm, "Issue Date")
        c.drawCentredString(col2_x, bottom_y - 2*mm, "Certificate ID")
        c.drawCentredString(col3_x, bottom_y - 2*mm, "Issued by")

        c.save()
        logger.info(f"Certificate PDF generated: {filepath}")
        return filename

    except ImportError:
        logger.warning("reportlab not installed — skipping PDF generation. Run: pip install reportlab")
        return None
    except Exception as e:
        logger.error(f"Certificate generation failed: {e}")
        return None


def generate_cert_number() -> str:
    """Generate a unique certificate number."""
    import random, string
    prefix = "ILT"
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return f"{prefix}-{random_part}"
