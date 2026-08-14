"""db 模型统一入口：import 即注册 Base.metadata（create_all/迁移用）。"""

from app.db.models.conversations import Conversation, Message
from app.db.models.documents import Document, DocumentChunk
from app.db.models.memory import UserPreference, UserProfile
from app.db.models.users import RefreshToken, User

__all__ = [
    "Conversation",
    "Document",
    "DocumentChunk",
    "Message",
    "RefreshToken",
    "User",
    "UserPreference",
    "UserProfile",
]
