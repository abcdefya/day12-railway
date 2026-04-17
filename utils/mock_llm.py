"""Mock LLM used for deployment labs."""

import random
import time


MOCK_RESPONSES = {
    "default": [
        "Day 12 lab agent is running with mock LLM.",
        "This is a mock response from the deployed agent.",
        "The service is healthy and can answer your question.",
    ],
    "docker": ["Docker packages app and dependencies into a portable container."],
    "deploy": ["Deployment publishes your app so others can access it online."],
    "health": ["Service status is healthy."],
}


def ask(question: str, delay: float = 0.1) -> str:
    time.sleep(delay + random.uniform(0.0, 0.05))
    lowered = question.lower()
    for keyword, answers in MOCK_RESPONSES.items():
        if keyword in lowered:
            return random.choice(answers)
    return random.choice(MOCK_RESPONSES["default"])


def ask_stream(question: str):
    response = ask(question)
    for word in response.split():
        time.sleep(0.05)
        yield word + " "
