import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


class OpenAIService:

    def __init__(self):

        print("Creating client...")

        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=30
        )

        print("Client ready.")

    def ask(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:

        print("Sending request...")

        response = self.client.responses.create(

            model="gpt-4.1-mini",

            input=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        print("Response received.")

        return response.output_text