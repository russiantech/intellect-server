import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import User, Course, Topic
from app.api.deps.auth import get_current_user
from app.core.config import get_app_config

router = APIRouter(prefix="/ai", tags=["AI Assistant"])
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str


class AIRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    context: Optional[str] = None  # course_slug, topic info, etc.
    course_id: Optional[int] = None


@router.post("/chat")
async def ai_chat(
    payload: AIRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = get_app_config()
    if not cfg.ai_config.is_ai_enabled:
        raise HTTPException(status_code=503, detail="AI assistant is not enabled")

    context_text = ""
    if payload.course_id:
        course = db.query(Course).filter(Course.id == payload.course_id).first()
        if course:
            context_text = f"\n\nCurrent course context: {course.title}\n"
            if course.description:
                context_text += f"Course description: {course.description[:500]}\n"

    system_prompt = f"""You are Intellect AI, a helpful learning assistant on the Intellect LMS platform.
You help students understand course content, answer questions about what they're learning,
provide explanations, suggest resources, and support their learning journey.
Be encouraging, clear, and educational. Keep responses concise but thorough.
{context_text}
Student name: {user.name or user.username}
"""

    messages = []
    for m in payload.history[-10:]:  # Last 10 messages for context
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": payload.message})

    try:
        if cfg.ai_config.anthropic_api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=cfg.ai_config.anthropic_api_key)
            response = client.messages.create(
                model=cfg.ai_config.default_model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            reply = response.content[0].text

        elif cfg.ai_config.openai_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=cfg.ai_config.openai_api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": system_prompt}] + messages,
                max_tokens=1024,
            )
            reply = response.choices[0].message.content
        else:
            raise HTTPException(status_code=503, detail="No AI provider configured")

        return {"reply": reply, "model": cfg.ai_config.default_model}

    except Exception as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=500, detail="AI assistant encountered an error")


@router.post("/grade-essay")
async def ai_grade_essay(
    answer_text: str,
    question_body: str,
    max_marks: float = 10.0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Use AI to grade an essay/open-ended answer."""
    cfg = get_app_config()
    if not cfg.ai_config.is_ai_enabled:
        raise HTTPException(status_code=503, detail="AI grading is not enabled")

    prompt = f"""Grade the following student answer on a scale of 0 to {max_marks} marks.

Question: {question_body}

Student Answer: {answer_text}

Provide:
1. Score (number between 0 and {max_marks})
2. Brief feedback (2-3 sentences)
3. What was done well
4. What could be improved

Format your response as JSON:
{{"score": <number>, "feedback": "<string>", "strengths": "<string>", "improvements": "<string>"}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.ai_config.anthropic_api_key)
        response = client.messages.create(
            model=cfg.ai_config.default_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        result = json.loads(response.content[0].text)
        return result
    except Exception as e:
        logger.error(f"AI grading error: {e}")
        raise HTTPException(status_code=500, detail="AI grading failed")
