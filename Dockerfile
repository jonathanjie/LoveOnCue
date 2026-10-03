# Source-layout image: compiled browser assets are committed and checked in CI.
# Pin this base image by digest after the first verified deployment build.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-runtime.lock ./
RUN pip install -r requirements-runtime.lock "psycopg[binary]==3.3.4"
COPY . .
RUN pip install --no-deps -e . && useradd --system --uid 10001 --create-home weddingops \
    && mkdir -p /app/.data && chown -R weddingops:weddingops /app
USER weddingops
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request,urllib.parse; h=urllib.parse.urlparse(os.environ['WEDDINGOPS_PUBLIC_URL']).netloc; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/ready',headers={'Host':h}),timeout=3)" || exit 1
CMD ["weddingops", "serve", "--host", "0.0.0.0", "--port", "8000"]
