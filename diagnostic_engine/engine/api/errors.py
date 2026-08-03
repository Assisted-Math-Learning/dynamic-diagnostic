"""
API error codes and exception classes.

Each error code from spec sections 5.3-5.6 and 12 maps to:
  - an exception subclass of EngineApiError
  - a fixed HTTP status code
  - a fixed code string for the envelope's `error.code` field

Route handlers raise the exception; the registered FastAPI exception handler
(see api/main.py) translates to the envelope-wrapped response.
"""

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """All engine error codes from spec sections 5.3-5.6, 7.8, and 12."""

    INVALID_TENANT_TOKEN = "INVALID_TENANT_TOKEN"
    INVALID_GRADE = "INVALID_GRADE"
    INVALID_SKILL_ID = "INVALID_SKILL_ID"
    LEARNER_MISMATCH = "LEARNER_MISMATCH"
    PII_FIELD_PRESENT = "PII_FIELD_PRESENT"
    SESSION_ALREADY_EXISTS = "SESSION_ALREADY_EXISTS"
    SESSION_ALREADY_ENDED = "SESSION_ALREADY_ENDED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_NOT_COMPLETE = "SESSION_NOT_COMPLETE"
    RESPONSE_CONFLICT = "RESPONSE_CONFLICT"
    NO_TREE_FOR_GRADE = "NO_TREE_FOR_GRADE"
    NO_QUESTION_FOR_SKILL = "NO_QUESTION_FOR_SKILL"
    VERDICTS_NOT_WRITTEN = "VERDICTS_NOT_WRITTEN"
    SESSION_LOCKED = "SESSION_LOCKED"


# HTTP status code per error code (spec sections 7.8 and 12).
HTTP_STATUS: dict = {
    ErrorCode.INVALID_TENANT_TOKEN: 401,
    ErrorCode.INVALID_GRADE: 400,
    ErrorCode.INVALID_SKILL_ID: 400,
    ErrorCode.LEARNER_MISMATCH: 400,
    ErrorCode.PII_FIELD_PRESENT: 400,
    ErrorCode.SESSION_ALREADY_EXISTS: 409,
    ErrorCode.SESSION_ALREADY_ENDED: 409,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_COMPLETE: 409,
    ErrorCode.RESPONSE_CONFLICT: 409,
    ErrorCode.NO_TREE_FOR_GRADE: 404,
    ErrorCode.NO_QUESTION_FOR_SKILL: 500,
    ErrorCode.VERDICTS_NOT_WRITTEN: 500,
    ErrorCode.SESSION_LOCKED: 503,
}


class EngineApiError(Exception):
    """Base class for all engine API errors. Carries an ErrorCode and a message.

    The FastAPI exception handler reads .code and .message to build the
    error envelope; .http_status to set the response code.
    """

    code: ErrorCode  # override in subclasses

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]


# Concrete error subclasses, one per code -------------------------------------


class InvalidTenantTokenError(EngineApiError):
    code = ErrorCode.INVALID_TENANT_TOKEN


class InvalidGradeError(EngineApiError):
    code = ErrorCode.INVALID_GRADE


class InvalidSkillIdError(EngineApiError):
    code = ErrorCode.INVALID_SKILL_ID


class LearnerMismatchError(EngineApiError):
    code = ErrorCode.LEARNER_MISMATCH


class PiiFieldPresentError(EngineApiError):
    code = ErrorCode.PII_FIELD_PRESENT


class SessionAlreadyExistsError(EngineApiError):
    code = ErrorCode.SESSION_ALREADY_EXISTS


class SessionAlreadyEndedError(EngineApiError):
    code = ErrorCode.SESSION_ALREADY_ENDED


class SessionNotFoundError(EngineApiError):
    code = ErrorCode.SESSION_NOT_FOUND


class SessionNotCompleteError(EngineApiError):
    code = ErrorCode.SESSION_NOT_COMPLETE


class ResponseConflictError(EngineApiError):
    code = ErrorCode.RESPONSE_CONFLICT


class NoTreeForGradeError(EngineApiError):
    code = ErrorCode.NO_TREE_FOR_GRADE


class NoQuestionForSkillError(EngineApiError):
    """Spec section 7.8 failure mode: the question pool returned no question
    for a skill the engine needs to ask. Indicates a content-pool gap that
    engineering and the content team must address. Fires when the pool's
    filtered candidate set is empty for a valid in-scope skill.
    """

    code = ErrorCode.NO_QUESTION_FOR_SKILL


class VerdictsNotWrittenError(EngineApiError):
    code = ErrorCode.VERDICTS_NOT_WRITTEN


class SessionLockedError(EngineApiError):
    code = ErrorCode.SESSION_LOCKED
