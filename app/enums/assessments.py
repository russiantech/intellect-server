"""
app/enums/assessments.py
========================
Enums specific to the assessment layer:
  - Quiz / LessonAssessment question types
  - Quiz attempt lifecycle
  - Project & assessment submission lifecycle
  - Legacy Assessment / Question types (kept for backwards compat)
  - Attendance status
"""
import enum


# ──────────────────────────────────────────────────────────────────
#  Question types (shared by Quiz, LessonAssessment, & legacy Assessment)
# ──────────────────────────────────────────────────────────────────

class QuizQuestionType(str, enum.Enum):
    """
    Supported question formats for topic-level quizzes and
    lesson-level assessments (classwork / homework).

    mcq          – single correct option from a list
    multi_select – one or more correct options (checkboxes)
    true_false   – student picks True or False
    short_answer – free-text; AI or tutor grades against a model answer
    essay        – long-form free-text; always requires AI / tutor review
    fill_blank   – complete a sentence (exact / keyword match)
    file_upload  – student uploads a file as their answer
    """
    mcq          = "mcq"
    multi_select = "multi_select"
    true_false   = "true_false"
    short_answer = "short_answer"
    essay        = "essay"
    fill_blank   = "fill_blank"
    file_upload  = "file_upload"


class AssessmentType(str, enum.Enum):
    """
    Discriminator for LessonAssessment rows.

    classwork   – completed during live session (short time limit)
    homework    – completed at home (wider due-date window)
    exam        – formal examination
    quiz        – lightweight knowledge check (prefer Topic-level Quiz model)
    quick_check – on-the-fly teacher check
    """
    classwork   = "classwork"
    homework    = "homework"
    exam        = "exam"
    quiz        = "quiz"
    quick_check = "quick_check"


class QuestionType(str, enum.Enum):
    """
    Legacy question type enum used by the original Assessment / Question models.
    Kept for backward compatibility with existing data.
    New code should use QuizQuestionType.
    """
    mcq          = "mcq"
    true_false   = "true_false"
    short_answer = "short_answer"
    essay        = "essay"
    file_upload  = "file_upload"


# ──────────────────────────────────────────────────────────────────
#  Quiz attempt lifecycle
# ──────────────────────────────────────────────────────────────────

class QuizAttemptStatus(str, enum.Enum):
    """
    Pipeline stages for a single quiz attempt.

    submitted   – answers received, awaiting grading
    auto_graded – fully scored by the auto-grader (MCQ / T-F / fill_blank)
    ai_graded   – short_answer / essay graded by AI; tutor may still review
    reviewed    – tutor has reviewed and optionally adjusted the AI grade
    returned    – student can see results and all feedback
    """
    submitted   = "submitted"
    auto_graded = "auto_graded"
    ai_graded   = "ai_graded"
    reviewed    = "reviewed"
    returned    = "returned"


# ──────────────────────────────────────────────────────────────────
#  Submission lifecycle (Projects & LessonAssessment submissions)
# ──────────────────────────────────────────────────────────────────

class SubmissionStatus(str, enum.Enum):
    """
    Shared lifecycle for ProjectSubmission and AssessmentSubmission.

    pending   – submitted by student, not yet opened by grader
    reviewing – AI or tutor has opened it
    ai_graded – AI feedback written; tutor review optional
    returned  – final grade delivered to student
    resubmit  – grader has requested a revision from the student
    """
    pending   = "pending"
    reviewing = "reviewing"
    ai_graded = "ai_graded"
    returned  = "returned"
    resubmit  = "resubmit"


# ──────────────────────────────────────────────────────────────────
#  Attendance
# ──────────────────────────────────────────────────────────────────

class AttendanceStatus(str, enum.Enum):
    present = "present"
    absent  = "absent"
    late    = "late"
    excused = "excused"
