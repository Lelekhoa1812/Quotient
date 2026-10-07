# Motivation vs Logic
# Motivation: A replayed activity with the same idempotency key returns the stored result.
# Logic: The memory store is the worker-side checkpoint port. DynamoDB stays outside this package.

class MemoryStore:
    def __init__(self):
        self.items: dict = {}

    def get(self, key: str):
        return self.items.get(key)

    def put(self, key: str, value) -> None:
        self.items[key] = value
