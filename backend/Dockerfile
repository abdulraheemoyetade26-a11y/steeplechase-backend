FROM python:3.12-slim

# Install Tesseract OCR and LibreOffice for PPTX conversion
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libreoffice-impress \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose the port and run the app
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT