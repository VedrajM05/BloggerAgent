from openai import OpenAI
from dotenv import load_dotenv
import os


load_dotenv()

# api_key = os.getenv("OPENAI_API_KEY") 
client = OpenAI()

def call_gpt(prompt : str) -> str:
    response = client.chat.completions.create(
        model="gpt-5.5",
        messages=[
            {
                "role" : "user",
                "content" : prompt
            }
        ]
    )

    return response.choices[0].message.content