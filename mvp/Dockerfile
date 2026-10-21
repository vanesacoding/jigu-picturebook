FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 --create-home jigu && mkdir /data && chown jigu:jigu /data
COPY --chown=jigu:jigu app.py ./
COPY --chown=jigu:jigu static ./static
USER jigu
ENV JIGU_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 4173
CMD ["python", "app.py", "serve", "--host", "0.0.0.0", "--port", "4173"]
