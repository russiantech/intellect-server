"""
Certificate API routes — download, generate PDF
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Certificate, User, Course
from app.enums import CertStatus
from app.api.deps.auth import get_current_user, require_admin
from app.services.certificate_service import generate_certificate_pdf
from app.core.config import get_app_config

router = APIRouter(prefix="/certificates", tags=["Certificates"])


@router.get("/{cert_id}/download")
async def download_certificate(
    cert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download a certificate as PDF. Generates if not already on disk."""
    cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    # Only owner or admin can download
    if cert.user_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    if cert.status != CertStatus.issued:
        raise HTTPException(status_code=400, detail="Certificate is not active")

    cfg = get_app_config()
    cert_dir = os.path.join(cfg.hosting_config.content_delivery.filesystem_base_path, "certificates")
    os.makedirs(cert_dir, exist_ok=True)

    # Check if PDF already exists
    existing_filename = cert.cert_url.split("/")[-1] if cert.cert_url else None
    existing_path = os.path.join(cert_dir, existing_filename) if existing_filename else None

    if existing_path and os.path.exists(existing_path):
        return FileResponse(
            path=existing_path,
            media_type="application/pdf",
            filename=f"Certificate_{cert.cert_number}.pdf",
        )

    # Generate PDF
    owner = db.query(User).filter(User.id == cert.user_id).first()
    course = db.query(Course).filter(Course.id == cert.course_id).first() if cert.course_id else None

    # Get instructor name
    instructor_name = None
    if course and course.creator:
        instructor_name = course.creator.name

    filename = generate_certificate_pdf(
        student_name=owner.name or owner.username,
        course_title=course.title if course else "Course Completion",
        cert_number=cert.cert_number,
        issued_date=cert.issued_at,
        instructor_name=instructor_name,
        platform_name=cfg.general_config.site_name,
        output_dir=cert_dir,
    )

    if not filename:
        # Fallback: return certificate info as JSON if PDF generation fails
        raise HTTPException(
            status_code=500,
            detail="PDF generation failed. Install reportlab: pip install reportlab",
        )

    # Update cert URL in DB
    cert_url = f"/uploads/certificates/{filename}"
    cert.cert_url = cert_url
    db.commit()

    pdf_path = os.path.join(cert_dir, filename)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"Certificate_{cert.cert_number}.pdf",
    )


@router.post("/{cert_id}/revoke", dependencies=[Depends(require_admin)])
async def revoke_certificate(cert_id: int, db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    cert.status = CertStatus.revoked
    db.commit()
    return {"message": "Certificate revoked"}


@router.post("/{cert_id}/reinstate", dependencies=[Depends(require_admin)])
async def reinstate_certificate(cert_id: int, db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    cert.status = CertStatus.issued
    db.commit()
    return {"message": "Certificate reinstated"}
