# API 镜像（12 部署）：python:3.11-slim + uvicorn
FROM python:3.11-slim

WORKDIR /app

# 先拷 pyproject + app 再装依赖（setuptools find packages 需要 app 存在）
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY init ./init
RUN pip install --no-cache-dir .

EXPOSE 8000
# 迁移 + 启动：api 容器作为迁移执行者（compose command 亦可覆盖）
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
