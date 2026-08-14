"""06 图片库：CLIP 多模态向量（蓝图 06 image_embedding 段）。

sentence-transformers 本地模型，图查图（embed_image）与文字搜图（embed_text）同一向量空间；
懒加载单例，无外部 API 依赖；首次加载需下载模型（几百 MB，需网络/梯子）。
"""

import io

from app.core.config import get_settings


class ImageEmbeddingService:
    """CLIP（clip-ViT-B-32，01 settings；中文场景可换 Chinese-CLIP）。"""

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or get_settings().image_embedding_model
        self._model = None  # 懒加载单例

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed_image(self, image_bytes: bytes) -> list[float]:
        """图片 → CLIP 向量。"""
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return self._get_model().encode(img).tolist()

    def embed_text(self, text: str) -> list[float]:
        """文本 → CLIP 向量（与图片同空间）。"""
        return self._get_model().encode([text]).tolist()


_inst: ImageEmbeddingService | None = None


def get_image_embedding() -> ImageEmbeddingService:
    """全局单例（懒加载）。"""
    global _inst
    if _inst is None:
        _inst = ImageEmbeddingService()
    return _inst
