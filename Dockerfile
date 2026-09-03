# Base image: official lightweight Python 3.12 image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /code

# Copy only requirements.txt first (not the whole project yet)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the project code into the container
COPY . .

# Default command (overridden by docker-compose for the worker service)
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]