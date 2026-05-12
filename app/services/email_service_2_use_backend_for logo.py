"""
Intellect LMS — Email Service  v5

Changes vs v4:
─────────────────────────────────────────────────────────────────────────────
1.  logo_url now uses api_url (backend) instead of frontend_url.
    Gmail/Outlook image proxies fetch from the backend domain, which is
    always publicly reachable. The frontend URL (localhost/ngrok) is only
    used for unsubscribe links and CTAs that users click.

2.  Added logo_width / logo_height to _base_ctx() so every template
    receives explicit dimensions — required by Outlook and Gmail.

3.  Added logo_mimetype for templates that may need it (e.g. base64 fallback).

4.  _base_ctx() falls back to frontend_url if api_url is missing,
    preserving backwards compatibility.
─────────────────────────────────────────────────────────────────────────────
"""

import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_ctx() -> dict:
    """
    Context variables that every template requires.

    CRITICAL: logo_url uses api_url (backend), NOT frontend_url.
    Email clients (Gmail, Outlook) run image proxies that fetch images
    from their own servers. Those proxies must reach a public URL.
    localhost:5173 and temporary ngrok URLs are invisible to Google.
    """
    cfg = get_app_config()
    frontend = cfg.hosting_config.frontend_url.rstrip("/")
    
    # Use backend API URL for images — this is the public server
    api_base = getattr(cfg.hosting_config, "api_url", None) or frontend
    api_base = api_base.rstrip("/")

    return {
        "site_name":        cfg.general_config.site_name,
        # Backend-served logo — must be a PNG/JPG, not .ico
        "logo_url":         f"{api_base}/static/images/logos/favicon.png",
        "logo_width":       120,
        "logo_height":      40,
        "logo_mimetype":    "image/png",
        "unsubscribe_url":  f"{frontend}/unsubscribe",
    }


def _render(template_name: str, context: dict) -> str:
    try:
        tpl = _jinja_env.get_template(template_name)
        return tpl.render(**context)
    except Exception as e:
        logger.error("Template render error [%s]: %s", template_name, e)
        return context.get("fallback_body", "")


def send_email(
    to:      str | List[str],
    subject: str,
    html:    str,
    text:    Optional[str] = None,
) -> bool:
    """
    Dispatch an email via the configured provider.
    Always returns bool. Never raises.
    """
    try:
        cfg        = get_app_config().mail_config
        recipients = [to] if isinstance(to, str) else to

        if cfg.provider == "console":
            logger.info("[CONSOLE EMAIL] To: %s | Subject: %s", recipients, subject)
            logger.info(html[:800])
            return True

        if cfg.provider == "resend":
            return _send_resend(recipients, subject, html, cfg)

        if cfg.provider in ("smtp", "sendgrid", "mailgun"):
            return _send_smtp(recipients, subject, html, text, cfg)

        logger.warning("Unknown email provider: %s", cfg.provider)
        return False

    except Exception as exc:
        logger.error("send_email unexpected error: %s", exc, exc_info=True)
        return False


def _send_resend(recipients, subject, html, cfg) -> bool:
    try:
        import resend
        resend.api_key = cfg.resend_api_key
        resend.Emails.send({
            "from":    f"{cfg.mail_sender_name} <{cfg.mail_sender_email}>",
            "to":      recipients,
            "subject": subject,
            "html":    html,
        })
        return True
    except ImportError:
        logger.error("'resend' package not installed — pip install resend")
        return False
    except Exception as e:
        logger.error("Resend error: %s, %s, %s", e, cfg.mail_sender_name, cfg.mail_sender_email)
        return False


def _send_smtp(recipients, subject, html, text, cfg) -> bool:
    try:
        msg            = MIMEMultipart("alternative")
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
#  High-level senders
#  Contract: return bool, never raise.
# ─────────────────────────────────────────────────────────────────────────────

def send_verification_email(
    user_email: str,
    user_name:  str,
    email_code: str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("verify.html", {
            **_base_ctx(),
            "user_name":      user_name,
            "email_code":     email_code,
            "whatsapp_link":  cfg.general_config.whatsapp_community_link,
            "fallback_body":  f"Your verification code is: {email_code}",
        })

        if not html:
            ctx = _base_ctx()
            html = f"""
            <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:2rem">
              <img src="{ctx['logo_url']}" alt="{ctx['site_name']}"
                   width="{ctx['logo_width']}" height="{ctx['logo_height']}"
                   style="display:block;margin-bottom:1rem">
              <h2 style="color:#5826ee">Verify your email</h2>
              <p>Hi {user_name}, your verification code is:</p>
              <div style="font-size:2.5rem;font-weight:800;letter-spacing:0.3em;
                          color:#5826ee;padding:1rem 1.5rem;background:#f0effe;
                          border-radius:8px;text-align:center;
                          font-family:'Courier New',monospace">{email_code}</div>
              <p style="color:#6b7280;font-size:0.875rem">
                Expires in 10 minutes. Never share this code.
              </p>
            </div>"""

        return send_email(
            user_email,
            f"Verify your email — {cfg.general_config.site_name}",
            html,
        )
    except Exception as exc:
        logger.error("send_verification_email error: %s", exc, exc_info=True)
        return False


def send_welcome_email(
    user_email:    str,
    user_name:     str,
    whatsapp_link: str = "",
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("welcome.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "whatsapp_link": whatsapp_link or cfg.general_config.whatsapp_community_link,
            "login_url":     f"{cfg.hosting_config.frontend_url}/auth/signin",
            "fallback_body": f"Welcome to {cfg.general_config.site_name}!",
        })
        return send_email(user_email, f"Welcome to {cfg.general_config.site_name}!", html)
    except Exception as exc:
        logger.error("send_welcome_email error: %s", exc, exc_info=True)
        return False


def send_password_reset_email(
    user_email: str,
    user_name:  str,
    reset_code: str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("reset_password.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "reset_code":    reset_code,
            "fallback_body": f"Your password reset code is: {reset_code}",
        })
        return send_email(
            user_email,
            f"Reset your password — {cfg.general_config.site_name}",
            html,
        )
    except Exception as exc:
        logger.error("send_password_reset_email error: %s", exc, exc_info=True)
        return False


def send_course_approved_email(
    creator_email: str,
    creator_name:  str,
    course_title:  str,
    course_url:    str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("course_approved.html", {
            **_base_ctx(),
            "creator_name":  creator_name,
            "course_title":  course_title,
            "course_url":    course_url,
            "fallback_body": f'Your course "{course_title}" has been approved!',
        })
        return send_email(creator_email, f'Course Approved: "{course_title}"', html)
    except Exception as exc:
        logger.error("send_course_approved_email error: %s", exc, exc_info=True)
        return False


def send_course_rejected_email(
    creator_email: str,
    creator_name:  str,
    course_title:  str,
    reason:        str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("course_rejected.html", {
            **_base_ctx(),
            "creator_name":  creator_name,
            "course_title":  course_title,
            "reason":        reason,
            "dashboard_url": f"{cfg.hosting_config.frontend_url}/creator/courses",
            "fallback_body": f'Your course "{course_title}" requires changes. Reason: {reason}',
        })
        return send_email(creator_email, f'Course Review: "{course_title}"', html)
    except Exception as exc:
        logger.error("send_course_rejected_email error: %s", exc, exc_info=True)
        return False


def send_team_request_approved(
    user_email: str,
    user_name:  str,
    role:       str,
) -> bool:
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
        return send_email(
            user_email,
            f"You're now a {role.title()} on {cfg.general_config.site_name}!",
            html,
        )
    except Exception as exc:
        logger.error("send_team_request_approved error: %s", exc, exc_info=True)
        return False


def send_team_request_rejected(
    user_email: str,
    user_name:  str,
    role:       str,
    reason:     str = "",
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("team_rejected.html", {
            **_base_ctx(),
            "user_name":   user_name,
            "role":        role,
            "reason":      reason,
            "courses_url": f"{cfg.hosting_config.frontend_url}/explore",
            "fallback_body": f"Your {role} request was not approved at this time.",
        })
        return send_email(
            user_email,
            f"Your {role.title()} request — {cfg.general_config.site_name}",
            html,
        )
    except Exception as exc:
        logger.error("send_team_request_rejected error: %s", exc, exc_info=True)
        return False


def send_enrollment_confirmation(
    user_email:   str,
    user_name:    str,
    course_title: str,
    course_url:   str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("enrollment.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "course_title":  course_title,
            "course_url":    course_url,
            "fallback_body": f'You are now enrolled in "{course_title}"',
        })
        return send_email(user_email, f'Enrolled: "{course_title}"', html)
    except Exception as exc:
        logger.error(
            "send_enrollment_confirmation error (non-fatal) for %s: %s",
            user_email, exc, exc_info=True,
        )
        return False


def send_certificate_email(
    user_email:   str,
    user_name:    str,
    course_title: str,
    cert_url:     str,
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("certificate.html", {
            **_base_ctx(),
            "user_name":     user_name,
            "course_title":  course_title,
            "cert_url":      cert_url,
            "fallback_body": f"Certificate for {course_title}: {cert_url}",
        })
        return send_email(user_email, f"Your Certificate — {course_title}", html)
    except Exception as exc:
        logger.error("send_certificate_email error: %s", exc, exc_info=True)
        return False


def send_broadcast_email(
    recipients: List[str],
    subject:    str,
    body:       str,
) -> bool:
    try:
        return send_email(recipients, subject, body)
    except Exception as exc:
        logger.error("send_broadcast_email error: %s", exc, exc_info=True)
        return False


def send_invite_email(
    email:      str,
    invited_by: str,
    invite_url: str,
    role:       str = "student",
) -> bool:
    try:
        cfg  = get_app_config()
        html = _render("invite.html", {
            **_base_ctx(),
            "invited_by":    invited_by,
            "role":          role,
            "invite_url":    invite_url,
            "fallback_body": f"You've been invited to join {cfg.general_config.site_name}: {invite_url}",
        })
        return send_email(
            email,
            f"You're invited to {cfg.general_config.site_name}",
            html,
        )
    except Exception as exc:
        logger.error("send_invite_email error: %s", exc, exc_info=True)
        return False
