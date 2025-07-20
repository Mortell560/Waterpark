FROM python:3.13-alpine

LABEL maintainer="Mortell560"
LABEL description="Watermarking tool for images and PDFs"

ENV PORT=8080
ENV RELOAD=false
ENV HOST="0.0.0.0"

RUN addgroup -S appgroup && adduser -S appuser -G appgroup && apk add --no-cache poppler

USER appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

EXPOSE ${PORT}

CMD ["python", "main.py"]