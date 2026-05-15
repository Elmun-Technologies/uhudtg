FROM python:3.11-slim

WORKDIR /app

RUN apt-get update -qq && apt-get install -y -qq \
    libffi-dev libssl-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /app/assets

CMD ["python", "bot.py"]
