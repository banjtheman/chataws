FROM python:3.9-slim

WORKDIR /app
RUN apt-get update && apt-get install graphviz -y

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY ai-plugin.json ai-plugin.json
COPY app.py app.py
COPY openapi.yaml openapi.yaml
COPY ai_utils.py ai_utils.py

EXPOSE 5000

CMD ["python", "app.py"]
