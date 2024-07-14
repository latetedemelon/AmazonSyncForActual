# Set Base Image
FROM python:3.12-slim-bookworm

#Set working Directory
WORKDIR /code
COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY secrets/ secrets/
COPY src/ .
CMD ["python3", "./main.py"]
