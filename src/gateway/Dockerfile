# Base image: a small official Python (Debian "slim" + Python 3.12).
FROM python:3.12-slim

# Every command below runs inside /app (created automatically). Also the
# directory the app starts from, so relative paths in CMD resolve here.
WORKDIR /app

# Copy ONLY the dependency list first — this is deliberate (layer caching, below).
# Paths are relative to the BUILD CONTEXT (the project root), so this grabs
# ./requirements.txt and drops it at /app/requirements.txt.
COPY requirements.txt .

# Install the Python dependencies. --no-cache-dir skips pip's download cache,
# which just bloats the image.
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the gateway's code. "src/gateway/." means "the CONTENTS of that
# folder" -> so gateway.py + the two .lua files land directly in /app/.
COPY src/gateway/. .

# Start the server. fastapi run = production mode (comes from fastapi[standard]).
# --host 0.0.0.0 makes it listen on all interfaces so it's reachable from
# OUTSIDE the container (explained below).
CMD ["fastapi", "run", "gateway.py", "--host", "0.0.0.0", "--port", "8000"]
