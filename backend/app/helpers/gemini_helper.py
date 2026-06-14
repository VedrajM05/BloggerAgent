import google.generativeai as genai
from dotenv import load_dotenv
import os


load_dotenv()

MODEL_EDITOR = "gemini-2.5-flash"
# genai.configure(api_key= os.get)

def call_gemini_text(prompt :str) -> str:
    model = genai.GenerativeModel(MODEL_EDITOR)

    response = model.generate_content(prompt)

    return response.text.strip()

