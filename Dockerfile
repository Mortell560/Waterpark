FROM python:3.14-alpine

LABEL maintainer="Mortell560"
LABEL description="Watermarking tool for images and PDFs"

ENV PORT=8080
ENV RELOAD=false
ENV HOST="0.0.0.0"
ENV CERT_PATH="/app/certs/cert.pem"
ENV KEY_PATH="/app/certs/key.pem"
ENV SIGN_PASS=""

RUN apk add --no-cache gcc musl-dev poppler poppler-utils zbar zbar-dev libzbar && \
    addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

USER appuser

COPY src/ .

EXPOSE ${PORT}

CMD ["python", "main.py"]