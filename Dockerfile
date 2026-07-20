FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

WORKDIR /app/src
EXPOSE 8000
CMD ["/bin/sh", "/app/entrypoint.sh"]
