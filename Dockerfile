FROM python:3.11-slim

# Ajustes básicos
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# Dependencias del sistema (curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl libpq-dev \
  && rm -rf /var/lib/apt/lists/*

# Copiar e instalar deps de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Puerto por defecto (Railway usará $PORT dinámicamente)
ENV PORT=8000
ENV HOST=0.0.0.0

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# Ejecutar
CMD ["python", "-u", "main.py"]
