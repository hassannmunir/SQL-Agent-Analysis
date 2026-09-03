"""
Quick diagnostic script: asks the Google Gemini API directly which
models are currently available for this API key, instead of guessing
model names (which change frequently).
"""

from google import genai
from app.settings import GOOGLE_API_KEY

client = genai.Client(api_key=GOOGLE_API_KEY)

print("Models available for your API key:\n")
for m in client.models.list():
    print(m.name)