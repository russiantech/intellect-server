"""
Certificate API routes — download, generate PDF
"""
from pathlib import Path
import tempfile, os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Certificate, User, Course
from app.enums import CertStatus
from app.api.deps.auth import get_current_user, require_admin
from app.services.certificate_service import generate_certificate_pdf
from app.services.storage import upload_file
from app.core.config import get_app_config

router = APIRouter(prefix="/certificates", tags=["Certificates"])


# @router.get("/{cert_id}/download")
# async def download_certificate(
#     cert_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """Download a certificate as PDF. Generates if not already on disk."""
#     cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
#     if not cert:
#         raise HTTPException(status_code=404, detail="Certificate not found")

#     # Only owner or admin can download
#     if cert.user_id != user.id and not user.is_admin():
#         raise HTTPException(status_code=403, detail="Access denied")

#     if cert.status != CertStatus.issued:
#         raise HTTPException(status_code=400, detail="Certificate is not active")

#     cfg = get_app_config()
#     cert_dir = os.path.join(cfg.hosting_config.content_delivery.filesystem_base_path, "certificates")
#     os.makedirs(cert_dir, exist_ok=True)

#     # Check if PDF already exists
#     existing_filename = cert.cert_url.split("/")[-1] if cert.cert_url else None
#     existing_path = os.path.join(cert_dir, existing_filename) if existing_filename else None

#     if existing_path and os.path.exists(existing_path):
#         return FileResponse(
#             path=existing_path,
#             media_type="application/pdf",
#             filename=f"Certificate_{cert.cert_number}.pdf",
#         )

#     # Generate PDF
#     owner = db.query(User).filter(User.id == cert.user_id).first()
#     course = db.query(Course).filter(Course.id == cert.course_id).first() if cert.course_id else None

#     # Get instructor name
#     instructor_name = None
#     if course and course.creator:
#         instructor_name = course.creator.name

#     filename = generate_certificate_pdf(
#         student_name=owner.name or owner.username,
#         course_title=course.title if course else "Course Completion",
#         cert_number=cert.cert_number,
#         issued_date=cert.issued_at,
#         instructor_name=instructor_name,
#         platform_name=cfg.general_config.site_name,
#         output_dir=cert_dir,
#     )

#     if not filename:
#         # Fallback: return certificate info as JSON if PDF generation fails
#         raise HTTPException(
#             status_code=500,
#             detail="PDF generation failed. Install reportlab: pip install reportlab",
#         )

#     # Update cert URL in DB
#     cert_url = f"/uploads/certificates/{filename}"
#     cert.cert_url = cert_url
#     db.commit()

#     pdf_path = os.path.join(cert_dir, filename)
#     return FileResponse(
#         path=pdf_path,
#         media_type="application/pdf",
#         filename=f"Certificate_{cert.cert_number}.pdf",
#     )

# v2
@router.get("/{cert_id}/download")
async def download_certificate(cert_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cert = db.query(Certificate).filter(Certificate.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.user_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    if cert.status != CertStatus.issued:
        raise HTTPException(status_code=400, detail="Certificate is not active")

    if cert.cert_url and cert.cert_url.startswith("http"):
        return RedirectResponse(url=cert.cert_url, status_code=302)

    cfg = get_app_config()
    owner = db.query(User).filter(User.id == cert.user_id).first()
    course = db.query(Course).filter(Course.id == cert.course_id).first() if cert.course_id else None
    instructor_name = course.creator.name if course and course.creator else None

    with tempfile.TemporaryDirectory() as tmp_dir:
        filename = generate_certificate_pdf(
            student_name=owner.name or owner.username,
            course_title=course.title if course else "Course Completion",
            cert_number=cert.cert_number,
            issued_date=cert.issued_at,
            instructor_name=instructor_name,
            platform_name=cfg.general_config.site_name,
            output_dir=tmp_dir,
        )
        if not filename:
            raise HTTPException(status_code=500, detail="PDF generation failed. Install reportlab: pip install reportlab")

        pdf_bytes = (Path(tmp_dir) / filename).read_bytes()

    url = upload_file(pdf_bytes, f"Certificate_{cert.cert_number}.pdf", folder="certificates")
    cert.cert_url = url
    db.commit()

    return RedirectResponse(url=url, status_code=302)

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
