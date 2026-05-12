"""
Intellect LMS — Email Service  v6

Why data URIs fail in Gmail (and the real fix)
─────────────────────────────────────────────────────────────────────────────
Gmail, Outlook (web), and several other clients actively STRIP the `src`
attribute from <img> tags when the value is a `data:` URI. This is a
deliberate anti-phishing measure applied server-side before delivery.
The attribute disappears entirely — you see <img alt="..." width="...">
with no src. There is no workaround within a data URI approach.

Solution — CID inline attachment (RFC 2387 / multipart/related)
─────────────────────────────────────────────────────────────────────────────
The logo is sent as a MIME attachment embedded inside the email itself.
The HTML references it as:  <img src="cid:intellect-logo">

The mail client matches the CID to the attachment and renders the image
with no network request at all. Works in Gmail, Outlook (all versions),
Apple Mail, and all major webmail clients.

For SMTP   → multipart/related wrapping multipart/alternative + MIMEImage
For Resend → attachments array with content_id field (supported since 2023)
─────────────────────────────────────────────────────────────────────────────
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Optional, List
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_app_config

logger = logging.getLogger(__name__)

_templates_dir = Path(__file__).parent.parent / "templates" / "email"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=select_autoescape(["html"]),
)

# ─────────────────────────────────────────────────────────────────────────────
#  CID constant — must match src="cid:..." in every email template
# ─────────────────────────────────────────────────────────────────────────────

LOGO_CID      = "intellect-logo"      # <img src="cid:intellect-logo"> in templates
LOGO_FILENAME = "logo.png"

_LOGO_CANDIDATES: list[Path] = [
    Path(__file__).parent.parent / "static" / "images" / "logos" / "favicon.png",
    Path(__file__).parent.parent / "static" / "images" / "logos" / "favicon.ico",
    Path("static") / "images" / "logos" / "favicon.png",
    Path("static") / "images" / "logos" / "favicon.ico",
]

_cached_logo: Optional[tuple[bytes, str]] = None   # (raw_bytes, mime_type)


def _load_logo() -> Optional[tuple[bytes, str]]:
    """Return (bytes, mime_type) for the logo, cached after first read."""
    global _cached_logo
    if _cached_logo is not None:
        return _cached_logo
    for path in _LOGO_CANDIDATES:
        if path.exists():
            try:
                data = path.read_bytes()
                mime = "image/png" if path.suffix == ".png" else "image/x-icon"
                _cached_logo = (data, mime)
                logger.debug("Email logo loaded: %s (%d bytes)", path, len(data))
                return _cached_logo
            except Exception as exc:
                logger.warning("Could not read logo at %s: %s", path, exc)
    logger.warning("No logo file found. Searched: %s", [str(p) for p in _LOGO_CANDIDATES])
    return None


def _logo_inline() -> Optional[dict]:
    """Return inline-image dict for send_email(), or None if logo unavailable."""
    result = _load_logo()
    if not result:
        return None
    data, mime = result
    return {"cid": LOGO_CID, "data": data, "mime_type": mime, "filename": LOGO_FILENAME}


def _images() -> list:
    """Convenience used by every high-level sender."""
    img = _logo_inline()
    return [img] if img else []


# ─────────────────────────────────────────────────────────────────────────────
#  Template context
# ─────────────────────────────────────────────────────────────────────────────

def _base_ctx() -> dict:
    cfg      = get_app_config()
    frontend = cfg.hosting_config.frontend_url.rstrip("/")
    return {
        "site_name":       cfg.general_config.site_name,
        "logo_url":        f"cid:{LOGO_CID}" if _load_logo() else "",
        "unsubscribe_url": f"{frontend}/unsubscribe",
    }


def _render(template_name: str, context: dict) -> str:
    try:
        tpl = _jinja_env.get_template(template_name)
        return tpl.render(**context)
    except Exception as e:
        logger.error("Template render error [%s]: %s", template_name, e)
        return context.get("fallback_body", "")


# ─────────────────────────────────────────────────────────────────────────────
#  Transport
# ─────────────────────────────────────────────────────────────────────────────

def send_email(
    to:            str | List[str],
    subject:       str,
    html:          str,
    text:          Optional[str] = None,
    inline_images: Optional[List[dict]] = None,
) -> bool:
    """
    Dispatch via configured provider. Always returns bool, never raises.

    inline_images — list of dicts: {cid, data (bytes), mime_type, filename}
    """
    try:
        cfg        = get_app_config().mail_config
        recipients = [to] if isinstance(to, str) else to
        images     = inline_images or []

        if cfg.provider == "console":
            logger.info("[CONSOLE EMAIL] To: %s | Subject: %s | Images: %d",
                        recipients, subject, len(images))
            logger.info(html[:500])
            return True

        if cfg.provider == "resend":
            return _send_resend(recipients, subject, html, cfg, images)

        if cfg.provider in ("smtp", "sendgrid", "mailgun"):
            return _send_smtp(recipients, subject, html, text, cfg, images)

        logger.warning("Unknown email provider: %s", cfg.provider)
        return False

    except Exception as exc:
        logger.error("send_email unexpected error: %s", exc, exc_info=True)
        return False


def _send_resend(recipients, subject, html, cfg, inline_images: list) -> bool:
    """
    Resend API.  Inline images use the `content_id` attachment field so that
    src="cid:..." references in the HTML resolve.  Resend has supported
    content_id since mid-2023.
    """
    try:
        import resend
        resend.api_key = cfg.resend_api_key

        params: dict = {
            "from":    f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>",
            "to":      recipients,
            "subject": subject,
            "html":    html,
        }

        if inline_images:
            params["attachments"] = [
                {
                    "filename":     img["filename"],
                    "content":      list(img["data"]),  # Resend SDK: list[int]
                    "content_type": img["mime_type"],
                    "content_id":   img["cid"],          # enables cid: resolution
                }
                for img in inline_images
            ]

        resend.Emails.send(params)
        return True

    except ImportError:
        logger.error("'resend' package not installed — pip install resend")
        return False
    except Exception as e:
        logger.error("Resend error: %s | from: %s <%s>",
                     e, cfg.mail_sender_name, cfg.mail_sender_email)
        return False


def _send_smtp(recipients, subject, html, text, cfg, inline_images: list) -> bool:
    """
    SMTP.

    With inline images:    multipart/related
                             └─ multipart/alternative
                             │    ├─ text/plain
                             │    └─ text/html        ← src="cid:..." here
                             └─ image/png (Content-ID: <intellect-logo>)

    Without inline images: standard multipart/alternative.
    """
    try:
        if inline_images:
            msg = MIMEMultipart("related")
            msg["Subject"] = subject
            msg["From"]    = f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>"
            msg["To"]      = ", ".join(recipients)

            alt = MIMEMultipart("alternative")
            if text:
                alt.attach(MIMEText(text, "plain"))
            alt.attach(MIMEText(html, "html"))
            msg.attach(alt)

            for img in inline_images:
                subtype  = img["mime_type"].split("/")[-1]
                mime_img = MIMEImage(img["data"], _subtype=subtype)
                mime_img.add_header("Content-ID",          f"<{img['cid']}>")
                mime_img.add_header("Content-Disposition", "inline",
                                    filename=img["filename"])
                msg.attach(mime_img)
        else:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>"
            msg["To"]      = ", ".join(recipients)
            if text:
                msg.attach(MIMEText(text, "plain"))
            msg.attach(MIMEText(html, "html"))

        if cfg.smtp_use_ssl:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=cfg.smtp_timeout)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.smtp_timeout)
            if cfg.smtp_use_tls:
                server.starttls()

        if cfg.smtp_username and cfg.smtp_password:
            server.login(cfg.smtp_username, cfg.smtp_password)

        server.sendmail(cfg.mail_sender_email, recipients, msg.as_string())
        server.quit()
        return True

    except Exception as e:
        logger.error("SMTP error: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  High-level senders  —  return bool, never raise
# ─────────────────────────────────────────────────────────────────────────────

def send_verification_email(user_email: str, user_name: str, email_code: str) -> bool:
    try:
        cfg  = get_app_config()
        ctx  = _base_ctx()
        html = _render("verify.html", {
            **ctx,
            "user_name":     user_name,
            "email_code":    email_code,
            "whatsapp_link": cfg.general_config.whatsapp_community_link,
            "fallback_body": f"Your verification code is: {email_code}",
        })
        if not html:
            html = (
                f'<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem">'
                f'<h2 style="color:#5826ee">Verify your email</h2>'
                f'<p>Hi {user_name}, your verification code is:</p>'
                f'<div style="font-size:2.5rem;font-weight:800;letter-spacing:.3em;'
                f'color:#5826ee;padding:1rem 1.5rem;background:#f0effe;'
                f'border-radius:8px;text-align:center;font-family:monospace">'
                f'{email_code}</div>'
                f'<p style="color:#6b7280;font-size:.875rem">Expires in 10 minutes.</p></div>'
            )
        return send_email(
            user_email,
            f"Verify your email — {cfg.general_config.site_name}",
            html,
            inline_images=_images(),
        )
    except Exception as exc:
        logger.error("send_verification_email error: %s", exc, exc_info=True)
        return False


def send_welcome_email(user_email: str, user_name: str, whatsapp_link: str = "") -> bool:
    try:
        cfg  = get_app_config()
        html = _render("welcome.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "whatsapp_link": whatsapp_link or cfg.general_config.whatsapp_community_link,
            "login_url":     f"{cfg.hosting_config.frontend_url}/auth/signin",
            "fallback_body": f"Welcome to {cfg.general_config.site_name}!",
        })
        return send_email(user_email, f"Welcome to {cfg.general_config.site_name}!",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_welcome_email error: %s", exc, exc_info=True)
        return False


def send_password_reset_email(user_email: str, user_name: str, reset_code: str) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("reset_password.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "reset_code":    reset_code,
            "fallback_body": f"Your password reset code is: {reset_code}",
        })
        return send_email(user_email,
                          f"Reset your password — {cfg.general_config.site_name}",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_password_reset_email error: %s", exc, exc_info=True)
        return False


def send_course_approved_email(creator_email: str, creator_name: str,
                               course_title: str, course_url: str) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("course_approved.html", {
            **_base_ctx(),
            "creator_name":  creator_name,
            "course_title":  course_title,
            "course_url":    course_url,
            "fallback_body": f'Your course "{course_title}" has been approved!',
        })
        return send_email(creator_email, f'Course Approved: "{course_title}"',
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_course_approved_email error: %s", exc, exc_info=True)
        return False


def send_course_rejected_email(creator_email: str, creator_name: str,
                               course_title: str, reason: str) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("course_rejected.html", {
            **_base_ctx(),
            "creator_name":  creator_name,
            "course_title":  course_title,
            "reason":        reason,
            "dashboard_url": f"{cfg.hosting_config.frontend_url}/creator/courses",
            "fallback_body": f'Your course "{course_title}" requires changes.',
        })
        return send_email(creator_email, f'Course Review: "{course_title}"',
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_course_rejected_email error: %s", exc, exc_info=True)
        return False


def send_team_request_approved(user_email: str, user_name: str, role: str) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("team_approved.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "role":          role,
            "login_url":     f"{cfg.hosting_config.frontend_url}/auth/signin",
            "whatsapp_link": cfg.general_config.whatsapp_community_link,
            "fallback_body": f"Your request to join as {role} has been approved!",
        })
        return send_email(user_email,
                          f"You're now a {role.title()} on {cfg.general_config.site_name}!",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_team_request_approved error: %s", exc, exc_info=True)
        return False


def send_team_request_rejected(user_email: str, user_name: str,
                               role: str, reason: str = "") -> bool:
    try:
        cfg  = get_app_config()
        html = _render("team_rejected.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "role":          role,
            "reason":        reason,
            "courses_url":   f"{cfg.hosting_config.frontend_url}/explore",
            "fallback_body": f"Your {role} request was not approved at this time.",
        })
        return send_email(user_email,
                          f"Your {role.title()} request — {cfg.general_config.site_name}",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_team_request_rejected error: %s", exc, exc_info=True)
        return False


def send_enrollment_confirmation(user_email: str, user_name: str,
                                 course_title: str, course_url: str) -> bool:
    """EXPLICITLY NON-RAISING — called from payment verification endpoints."""
    try:
        cfg  = get_app_config()
        html = _render("enrollment.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "course_title":  course_title,
            "course_url":    course_url,
            "fallback_body": f'You are now enrolled in "{course_title}"',
        })
        return send_email(user_email, f'Enrolled: "{course_title}"',
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_enrollment_confirmation error (non-fatal) for %s: %s",
                     user_email, exc, exc_info=True)
        return False


def send_certificate_email(user_email: str, user_name: str,
                           course_title: str, cert_url: str) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("certificate.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "course_title":  course_title,
            "cert_url":      cert_url,
            "fallback_body": f"Certificate for {course_title}: {cert_url}",
        })
        return send_email(user_email, f"Your Certificate — {course_title}",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_certificate_email error: %s", exc, exc_info=True)
        return False


def send_broadcast_email(recipients: List[str], subject: str, body: str) -> bool:
    try:
        return send_email(recipients, subject, body)
    except Exception as exc:
        logger.error("send_broadcast_email error: %s", exc, exc_info=True)
        return False


def send_invite_email(email: str, invited_by: str,
                      invite_url: str, role: str = "student") -> bool:
    try:
        cfg  = get_app_config()
        html = _render("invite.html", {
            **_base_ctx(),
            "invited_by":    invited_by,
            "role":          role,
            "invite_url":    invite_url,
            "fallback_body": f"You've been invited to join {cfg.general_config.site_name}: {invite_url}",
        })
        return send_email(email, f"You're invited to {cfg.general_config.site_name}",
                          html, inline_images=_images())
    except Exception as exc:
        logger.error("send_invite_email error: %s", exc, exc_info=True)
        return False

