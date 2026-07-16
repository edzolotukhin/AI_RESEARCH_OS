class KnowledgeManager:

    def __init__(self):

        self.documents = []

    def add_document(self, title, content):

        self.documents.append({
            "title": title,
            "content": content
        })

    def search(self, keyword):

        result = []

        for doc in self.documents:

            if keyword.lower() in doc["content"].lower():

                result.append(doc)

        return result