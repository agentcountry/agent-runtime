FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PERMISSION_LEVEL=0

CMD ["python", "-c", "\
from agent_runtime import Runtime; \
import asyncio, os; \
rt = Runtime( \
    did=os.environ['ARMP_DID'], \
    homeserver=os.environ['ARMP_HOMESERVER'], \
    username=os.environ['ARMP_USERNAME'], \
    password=os.environ.get('ARMP_PASSWORD', ''), \
    permission_level=int(os.environ.get('PERMISSION_LEVEL', 0)), \
); \
asyncio.run(rt.start())"]
