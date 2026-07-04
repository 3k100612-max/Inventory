FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Change EXPOSE to your new port
EXPOSE 8506

# Force Gunicorn to bind to 8506
CMD ["gunicorn", "--bind", "0.0.0.0:8506", "app:app"]
