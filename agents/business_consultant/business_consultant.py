from openai import OpenAI

from domain.artifact import Artifact


class BusinessConsultant:

    def __init__(self, api_key):

        self.client = OpenAI(api_key=api_key)

    def create_business_brief(self, request):

        response = self.client.chat.completions.create(

            model="gpt-4.1-mini",

            messages=[
                {
                    "role": "system",
                    "content":
                    """
Ты опытный консультант
маркетингового исследовательского агентства.

На основе запроса клиента подготовь
структурированный Business Brief.
"""
                },
                {
                    "role": "user",
                    "content": request
                }
            ]
        )

        return Artifact(

            artifact_type="Business Brief",

            title="Business Brief",

            content=response.choices[0].message.content
        )