FROM python:3.13-slim

# psycopg2-binary bundles libpq, so no build tools or extra apt packages needed.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (dev/test artefacts excluded via .dockerignore).
COPY . .

# Run as a non-root user.
RUN useradd --system --no-create-home orc
USER orc

CMD ["python", "main.py"]
