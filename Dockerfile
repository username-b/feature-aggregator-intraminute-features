FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aggregate_features.py config_loader.py ./

ENV PYTHONUNBUFFERED=1

CMD ["python", "aggregate_features.py"]
