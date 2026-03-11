# Use Python with Playwright pre-installed
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir slack-bolt slack-sdk aiohttp beautifulsoup4 lxml pytz python-dotenv requests python-dateutil

# Copy app code
COPY . .

# Install Firefox (barre3 requires it to bypass headless detection)
# The base image has Chromium but we need Firefox too
RUN playwright install firefox

# Run the app
CMD ["python", "app.py"]