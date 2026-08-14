"""db 模型统一入口：import 即注册 Base.metadata（create_all/迁移用）。"""

from app.db.models.audit import AuditLog, ToolCallLog
from app.db.models.conversations import Conversation, Message
from app.db.models.documents import Document, DocumentChunk
from app.db.models.images import Image
from app.db.models.integrations import UserIntegration
from app.db.models.memory import UserPreference, UserProfile
from app.db.models.notifications import Notification, Reminder
from app.db.models.prompts import SystemPromptProfile
from app.db.models.rules import AutomationRule
from app.db.models.schedules import Schedule, Todo
from app.db.models.skills import Skill
from app.db.models.users import RefreshToken, User

__all__ = [
    "AuditLog",
    "AutomationRule",
    "Conversation",
    "Document",
    "DocumentChunk",
    "Image",
    "Message",
    "Notification",
    "RefreshToken",
    "Reminder",
    "Schedule",
    "Skill",
    "SystemPromptProfile",
    "Todo",
    "ToolCallLog",
    "User",
    "UserIntegration",
    "UserPreference",
    "UserProfile",
]
