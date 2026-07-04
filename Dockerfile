# Use a lightweight Python base image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Inform Docker that the container listens on port 8506
EXPOSE 8506

# Set environment variables for Flask
ENV FLASK_APP=app.py
ENV FLASK_RUN_PORT=8506
ENV FLASK_RUN_HOST=0.0.0.0

# Run using 'flask run' to respect the environment variables
CMD ["flask", "run"]
