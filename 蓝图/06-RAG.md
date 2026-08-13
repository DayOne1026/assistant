# 06 RAG（知识库检索）

用户私有文档检索。**完整管线**：加载 → 分块 → 向量化 → 异步索引 → 查询预处理 → 多路召回（向量+图+BM25 RRF 融合）→ 粗排（CrossEncoder）→ 精排（LLM）→ 拼 prompt。
管线算法从 `zhao/rag/` 移植，存储适配 pgvector。

## 数据模型（PG）

### documents
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK users.id CASCADE, index | |
| title | VARCHAR(255) | NOT NULL | |
| filename | VARCHAR(255) | NOT NULL | 原文件名 |
| content_type | VARCHAR(50) | | text/markdown/pdf... |
| storage_path | VARCHAR(500) | | 原始文件/URL |
| status | VARCHAR(20) | default 'processing' | processing/ready/failed |
| chunk_count | INT | default 0 | |
| created_at / updated_at | TIMESTAMPTZ | TimestampMixin | |

### document_chunks
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| document_id | UUID | FK documents.id CASCADE, index | |
| user_id | UUID | FK users.id CASCADE, index | 隔离过滤必需 |
| chunk_index | INT | NOT NULL | |
| group_id | VARCHAR(20) | NULL | 组号（文档内原子单元编号，0 起） |
| seq_in_group | INT | NULL | 组内顺序号（0 起） |
| parent_id | UUID | NULL | 父子切分：child 检索→parent 喂 LLM |
| content | TEXT | NOT NULL | |
| embedding | vector(1536) | NOT NULL | |
| created_at | TIMESTAMPTZ | | |

索引：`hnsw (embedding vector_cosine_ops)`、`(user_id)`、`(document_id)`。

## Pydantic Schema

```python
class DocumentUpload(BaseModel):
    title: str | None = None

class DocumentResponse(BaseModel):
    id: UUID
    title: str
    filename: str
    status: str
    chunk_count: int
    created_at: datetime

class ChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    score: float | None = None

class RetrievalQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)

class RetrievalResponse(BaseModel):
    chunks: list[ChunkResponse]
```

## 文档加载（rag/loader.py）— 复用 `zhao/rag/loader.py`

```python
def load_txt(path: str) -> str: ...            # 纯文本直接读
def load_document(path: str) -> str: ...       # pdf/docx/pptx/图片 → Docling → Markdown
def load_url(url: str) -> str: ...             # 网页 → Jina Reader (r.jina.ai) → Markdown
def load(path_or_url: str) -> str: ...
    """统一入口：http 开头走 Jina；.txt/.md/.py/.json 等纯文本直接读；其余走 Docling。"""
```

适配：异步服务里用 `await asyncio.to_thread(load, ...)` 包同步 I/O。

## 数据清洗（rag/cleaner.py）— 蓝图新增（zhao 无对应）

加载与分块之间必须过清洗，否则噪音进 embedding 拉低检索精度：

```python
def clean(markdown: str) -> str:
    """清洗 loader 输出（txt 直读 / Docling / Jina 都可能带噪音）：
    去 BOM 与非法字符 → 统一换行 → 去纯链接/导航/版权行 →
    折叠连续空行 → 压缩段内连续空白。"""

def dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """分块后内容级去重：文本相同/互为子串的块合并，保留首个（避免 RRF 前重复命中）。"""
```

清洗要点：
- **格式容错**：load 失败（Docling 解析不了、URL 超时）→ 记 `status=failed` + 错误原因，不阻塞其他文档；单块 embed 失败 → 跳过该块，不整体失败
- **空文档**：clean 后为空 → `status=failed`（"无有效内容"）
- **不做过度停用词清洗**：检索是向量 + BM25，粗暴去中文停用词/标点反而伤召回（ponytail: 有意为之，不跟风）

## 文本分块（rag/chunker.py）— 复用 `zhao/rag/chunker.py`

三种切法，统一输出 `[{text, tokens, group_id, seq_in_group}]`（parent-child：children 同结构，parent 为组）：

| 函数 | 适用 | 说明 |
|---|---|---|
| `chunk_by_token(text, size=200, overlap=30)` | 默认 | 段落聚合为原子单元 → 超限分组 |
| `chunk_by_semantic(text, size=200)` | 有标题层级 | 每个章节为原子单元 |
| `chunk_parent_child(text, child_size=200, parent_size=800)` | 长文档 | parent=组，children 组内有序 |

**分组兜底（三法共用，超上限时的统一规则）：**
- `group_id`：**文档内**组号（0 起，每个原子单元一组）
- `seq_in_group`：组内顺序号（0 起，组内第几块）
- 原子单元超 token 窗口 → 硬切为多块，同一 `group_id`，`seq_in_group` 递增
- 检索命中某块 → 按 `group_id` 取整组补上下文，不只见碎片
- 对 zhao 的扩展：zhao 的 group_id 是全局自增 g1/g2 且无组内序号；搬时改 `_split_unit` 返回值补 `seq_in_group`，组号改文档内自增

默认策略：`chunk_by_token`；文档有标题结构时 `chunk_by_semantic`；长文档/精度要求高时 `parent_child`。分块策略写入 documents 记录，索引时按策略选函数。

**保护规则（`_protect`，三法共用）——代码块和表格必须完整切，不碎：**

| 内容 | 原子单元 | 规则 |
|---|---|---|
| 代码块（```` ``` ```` 包裹） | 函数/类（按 `def / class / async def / fn` 切） | 单个函数整体作一个块，**不跨块切开** |
| 表格（markdown `\|` 行） | 连续表格行 | 整表连续行保留为一个单元，**不从中间断开** |
| 段落/章节（常规） | 段落/句子 | token 窗口切 + overlap |

兜底：单个原子超长超 token 窗口（如超长函数）→ 唯一例外允许 token 硬切，但**共享 group_id**（同源块，检索命中可带同组其余块）。

> 为什么必须完整：代码/表格被切开 → 块内语义断裂 → embedding 向量失真 → 检索命中碎片。zhao 的 `_protect` 已实现此规则，蓝图照搬。

## 向量化（rag/embedding.py）

```python
class EmbeddingService:
    """千问 text-embedding（DashScope compatible-mode），实现 embed/embed_many。
    参考 zhao/rag/embedding.py 的 QwenEmbedding（直接调 DashScope HTTP）。"""
    def __init__(self, model: str, dim: int): ...
    async def embed(self, text: str) -> list[float]: ...
    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...
```

## 文档服务（rag/document_service.py）

| 函数 | 职责 |
|---|---|
| `upload(db, storage, user_id, file, data) -> DocumentResponse` | 存原始文件 → 建 documents(status=processing) → `index_document.delay` |
| `list_documents(db, user_id, page_params) -> Page` | |
| `get_document(db, user_id, doc_id) -> Document` | 归属校验 |
| `soft_delete(db, user_id, doc_id) -> None` | 二次确认走 07 通用模式 |

## Celery 异步索引（tasks/rag_tasks.py）

```python
@app.task(bind=True, max_retries=3, default_retry_delay=30)
def index_document(self, document_id: str):
    """load → chunk → embed → 批量写 chunks → status=ready。失败置 failed。"""
```

`index_document` 伪代码：
```
doc = get_document(...)
markdown = clean(asyncio.run(to_thread(load, doc.storage_path)))   # 数据清洗（cleaner.py）
chunks = dedupe_chunks(pick_strategy(doc).apply(markdown))         # 去重后再向量化
vecs = asyncio.run(embedding.embed_many([c.text for c in chunks]))
delete 该 doc 已有 chunks（幂等重试）
bulk insert chunks(user_id, document_id, chunk_index, group_id, parent_id, content, embedding)
doc.status = "ready"; doc.chunk_count = len(chunks); commit
# 可选：markdown 抽取三元组写图谱（05 复用 extract_triples）
```

## 查询预处理（rag/query.py）— 复用 `zhao/rag/query.py`

| 函数 | 说明 |
|---|---|
| `rewrite(query, llm) -> str` | 改写扩写：补同义词/关键词，书面语 |
| `hyde(query, llm) -> str` | 生成 100-200 字假设答案，用其向量检索（HyDE） |
| `step_back(query, llm) -> str` | 后退到基础背景问题 |
| `preprocess(query, llm, strategies=['rewrite']) -> list[str]` | 批量执行多种策略，返回变体查询 |

## 多路召回（rag/retrieval.py）— 移植 `zhao/rag/retrieval.py`

三通道 + RRF 融合：

```python
def search(query, user_id, top_k=5,
           vector_fn=None,      # pgvector 余弦检索（必传）
           graph=None,          # 05 GraphMemory 多跳（可选）
           bm25=None) -> list[dict]:
    """向量 + 图 + BM25 → RRF 融合。
    RRF(doc) = Σ 1/(k + rank_in_channel(doc))，k=60。"""
```

| 通道 | 蓝图实现 | 说明 |
|---|---|---|
| 向量 | pgvector `cosine_distance` WHERE user_id | 必传，每通道取 top_k×2 |
| 图 | 05 `get_related_entities` | 可选，命中实体相关路径 |
| BM25 | `BM25Retriever`（纯 Python，zhao 移植） | 可选；内存索引适合单文档集，多用户规模化换 PG tsvector |

`BM25Retriever`：中文按"字 + 二元组"分词，英文按空白；`index(docs)` + `search(q, top_k)`。无外部依赖。

## 排序（rag/reranker.py）— 移植 `zhao/rag/reranker.py`

```python
class CrossEncoderReranker:
    """BGE-reranker-v2-m3，query+doc 深度打分。score(q, docs) -> [(idx, score)] 降序。"""

def coarse_rank(query, candidates, reranker, top_k=20) -> list[str]:
    """粗排：CrossEncoder 50→top_k。"""

def rerank(query, candidates, llm, top_k=5) -> list[dict]:
    """精排：LLM 逐条打分(1-5)+理由 → [{"text", "relevance", "reason"}]。
    用结构化输出（05 三层兜底模式），失败降级保留原序。"""
```

## 检索管线（rag/pipeline.py）

```python
async def build_context(user_id, query, top_k=5, rewrite_query=True) -> str:
    """① 改写 → ② 多路召回(RRF, top_k×2 候选) → ③ CrossEncoder 粗排 → ④ LLM 精排
    → ⑤ 拼成 "[参考文档] ..." 注入 prompt。无相关文档返回空串。"""
```

## Agent 集成（04 节点）

```python
async def rag_retrieve(state: AgentState) -> dict:
    """按用户问题 build_context，注入 rag_context 供 finalize。"""
    ctx = await build_context(state["user_id"], state["messages"][-1]["content"])
    return {"rag_context": ctx}
```

## 联网搜索（web_search）

助理查实时信息（天气/新闻/百科）。复用 `zhao/toollist.py` 的 web_search（Tavily）。

| 工具名 | 参数 schema | 等级 | 职责 |
|---|---|---|---|
| `web_search` | {query, max_results?=5} | read_only | Tavily 搜索 → 标题/摘要/URL |

- 01 settings：`tavily_api_key`
- 04 INTENTS：`web_search`（触发"查一下/搜一下实时…"）→ tool: web_search
- 结果注入回复（带来源链接），走 04 工具链（read_only 直接执行 + 审计）
- 复用 zhao `web_search` 原样搬，API key 走 Settings 配置

## API 层（api/documents.py）

| 方法 | 路径 | 入参 | 出参 | 说明 |
|---|---|---|---|---|
| POST | /documents | multipart file + DocumentUpload | DocumentResponse | 上传即异步索引 |
| GET | /documents | 分页 | Page | 列表 |
| GET | /documents/{id} | Bearer | DocumentResponse | 详情 |
| DELETE | /documents/{id} | Bearer | ok | 二次确认（07 通用模式） |
| POST | /search | RetrievalQuery | RetrievalResponse | 站内检索（走 build_context 但返回 chunks） |

## 复用来源（zhao）

| 蓝图位置 | 复用 |
|---|---|
| rag/loader.py | `zhao/rag/loader.py` 原样搬 |
| rag/chunker.py | `zhao/rag/chunker.py` 原样搬 |
| rag/query.py | `zhao/rag/query.py` 原样搬（LLM 调用换 get_chat_model） |
| rag/retrieval.py | `zhao/rag/retrieval.py` 的 BM25Retriever + RRF search（向量通道改 pgvector，图通道改 05） |
| rag/reranker.py | `zhao/rag/reranker.py`（精排输出改结构化输出三层兜底） |
| rag/pipeline.py | `zhao/rag/pipeline.py` build_context 骨架 |
| rag/cleaner.py | **蓝图新增**（zhao 无对应）——loader 输出到分块之间的清洗 + 去重 |

## 测试要点

- 索引：上传→按策略分块→embedding 维度正确→status=ready；重跑幂等不重复
- 加载：txt 直读 / pdf 走 Docling / URL 走 Jina（mock）
- 检索：RRF 融合后相关文档靠前；隔离（A 搜不到 B 文档）
- 排序：粗排后候选缩减；精排失败降级不崩
- 空库/无相关文档返回空串，agent 正常闲聊

## 模块边界

- 文档抽取三元组→图谱：05（复用 extract_triples）
- 文档删除审计：11；软删物理清除：12 cleanup
- BM25 内存索引上限：单文档集规模；多用户规模化换 PG tsvector（ponytail: 内存 BM25 先用，规模上来再换）

## 图片库（images）

图片完整落盘（Storage，01）+ 元数据表 + 多模态向量（CLIP）图查图 / 文字搜图 + 前端展示端点。

### images 表（PG）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK users.id CASCADE, index | |
| storage_path | VARCHAR(500) | NOT NULL | 原图（`media/{user_id}/{uuid}.{ext}`） |
| thumbnail_path | VARCHAR(500) | NULL | 缩略图 |
| filename | VARCHAR(255) | NOT NULL | 原始文件名 |
| content_type | VARCHAR(50) | NOT NULL | image/jpeg/png... |
| size | INT | NOT NULL | 字节 |
| phash | BIGINT | NULL | 感知哈希（可选去重） |
| ocr_text | TEXT | NULL | 可选，图内文字（增强文字搜图） |
| description | TEXT | NULL | 可选，VLM 视觉描述 |
| image_embedding | vector(512) | NOT NULL | CLIP 向量（图文同空间） |
| source_document_id | UUID | NULL | 来自哪篇文档的插图 |
| created_at | TIMESTAMPTZ | TimestampMixin | |

索引：`hnsw (image_embedding vector_cosine_ops)`、`(user_id)`。RLS 纳入（03）。

### Pydantic Schema

```python
class ImageResponse(BaseModel):
    id: UUID
    url: str                     # 展示端点（短期 token，前端直接 <img>）
    thumbnail_url: str | None
    filename: str
    content_type: str
    size: int
    created_at: datetime
```

### Agent 工具（注册进 ToolRegistry，11）

| 工具名 | 参数 | 等级 | 职责 |
|---|---|---|---|
| `search_images` | {query_text?} | read_only | 文字搜图 / 相似搜图，返回 ImageResponse[] |
| `get_image` | {image_id} | read_only | 取单图展示信息 |

> 工具结果转 `ChatResponse.attachments`（04）：对话中搜图 → 回复带图片，前端直接渲染。

### 多模态向量（app/rag/image_embedding.py）

```python
class ImageEmbeddingService:
    """CLIP（sentence-transformers，本地免费，图文同一向量空间）。
    图查图（embed_image）与文字搜图（embed_text）共用同一空间。"""
```

- 模型：`clip-ViT-B-32`（01 settings）；中文场景可换 Chinese-CLIP
- 本地加载单例，图片/文本各一次编码返回向量；无外部 API 依赖

### 图片服务（app/rag/image_service.py）

| 函数 | 职责 |
|---|---|
| `upload_image(db, storage, user_id, file) -> Image` | 存原图 + 缩略图 + CLIP 向量 + 写表 |
| `list_images(db, user_id, page_params) -> Page` | 分页（含展示/缩略图 URL） |
| `get_image(db, user_id, id) -> Image` | 归属校验（user_id 过滤 + RLS） |
| `get_image_bytes(db, user_id, id) -> tuple[bytes, str]` | 读取原图字节 + content_type（展示端点） |
| `search_images(db, user_id, query_image=None, query_text=None, top_k=10)` | 图查图 / 文字搜图 |
| `soft_delete` | 二次确认（07 通用），删文件 + 记录 |

`search_images` 伪代码：
```
if query_image_bytes: vec = image_emb.embed_image(query_image)   # 图查图
else:                 vec = image_emb.embed_text(query_text)     # 文字搜图
select Image where user_id == user_id
       order by image_embedding cosine_distance(vec) limit top_k
```

### 入库流程

```
POST /images（multipart 图片）
→ storage.write(media/{user_id}/{uuid}.{ext})     # 完整落盘
→ 生成缩略图（PIL）→ storage.write
→ image_emb.embed_image(bytes) → image_embedding
→ 写 images 表
→ （可选）VLM 生成 ocr_text/description 增强文字搜图
```

### API 层（app/api/images.py）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /images | multipart 上传 → 存 + 向量化 |
| GET | /images | 分页列表 |
| GET | /images/{id} | 原图字节流（展示） |
| GET | /images/{id}/thumbnail | 缩略图 |
| POST | /images/search | multipart 图片 或 `{query_text}` → 相似图片 |
| DELETE | /images/{id} | 二次确认（07） |

展示端点鉴权（`<img>` 带不了 header，二选一）：
```
GET /images/{id}?token=<short_lived>   # query token，秒级/一次用
或 cookie 会话
```

### 前端展示

```html
<img src="/api/v1/images/{id}?token=xxx">
```

### 测试要点

- 上传：文件落盘（路径含 user_id 目录、UUID 名）、CLIP 向量写入、缩略图生成
- 检索：同图搜出最相似；文字搜图命中相关图片；隔离（A 搜不到 B 的图）
- 展示：GET /images/{id} 返回正确字节 + content_type；无/错 token 拒
- 删除：二次确认后文件与记录同删（不残留孤儿文件）

### 模块边界（图片库）

- 文档插图：Docling 丢的视觉信息用 images 表补，`source_document_id` 关联原文档
- 图片描述进 RAG 文本检索：可选，走本文件检索管线（description 作文本块）
- phash 去重 / 多模态增强：`ponytail:` 已留（phash 列 + CLIP 通道即基础，规模化再增强）
