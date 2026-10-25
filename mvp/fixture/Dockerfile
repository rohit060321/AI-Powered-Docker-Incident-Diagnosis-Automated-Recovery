FROM python:3.12-slim
WORKDIR /app
COPY worker.py /app/worker.py
ENV PYTHONUNBUFFERED=1 TARGET_MIB=192
USER 65532:65532
CMD ["python", "/app/worker.py"]

