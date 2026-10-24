FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY poll_agentforce.py json_to_otlp.py ./
ENV PYTHONUNBUFFERED=1
ENV EXPORTED_FILE=/tmp/agentforce-exported.json
ENV MAX_PASSES=1
CMD ["python", "poll_agentforce.py"]
