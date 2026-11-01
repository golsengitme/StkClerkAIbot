"""Clerk Assistant agent for the Copper Hills Stake.

Runs on Amazon Bedrock AgentCore Runtime. The whole training manual goes into
the system prompt (it is small enough), with a cache point so repeat questions
reuse it cheaply.

Request payload:
    {"question": "...", "mode": "ask", "vague": false, "previousAnswer": "...",
     "asker": {"byTitle": "Brother Jensen", "firstName": "Jon", "rapport": "friend"}}
Response:
    {"answer": "..."}

Settings (environment variables):
    MODEL_ID        Bedrock model or inference profile ID (default below)
    AWS_REGION      Region for Bedrock (default us-west-2)
    MANUAL_S3_URI   s3://bucket/key of the manual; if unset, a local copy is used
    MANUAL_PATH     Local manual path override
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
REGION = os.environ.get("AWS_REGION", "us-west-2")
MAX_QUESTION_CHARS = 2000

VAGUE_FOLLOW_UP = (
    "My previous answer was too vague. Answer the question again from the stake knowledge base. "
    "Give the specific procedure in order, who owns each step, the timing, and the "
    "handbook references."
)

app = BedrockAgentCoreApp()


def _read_manual() -> str:
    s3_uri = os.environ.get("MANUAL_S3_URI", "").strip()
    if s3_uri:
        import boto3

        bucket, _, key = s3_uri.removeprefix("s3://").partition("/")
        body = boto3.client("s3", region_name=REGION).get_object(Bucket=bucket, Key=key)["Body"]
        return body.read().decode("utf-8")

    candidates = [
        os.environ.get("MANUAL_PATH", ""),
        str(HERE / "stake-clerk-training-manual.md"),
        str(HERE.parent / "docs" / "stake-clerk-training-manual.md"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).read_text(encoding="utf-8")
    raise FileNotFoundError("Training manual not found. Set MANUAL_S3_URI or MANUAL_PATH.")


@lru_cache(maxsize=1)
def _system_prompt() -> list[dict]:
    instructions = (HERE / "instructions.md").read_text(encoding="utf-8")
    manual = _read_manual()
    text = f"{instructions}\n\n<knowledge_base>\n{manual}\n</knowledge_base>"
    # Cache point after the large, unchanging block.
    return [{"text": text}, {"cachePoint": {"type": "default"}}]


@lru_cache(maxsize=1)
def _model() -> BedrockModel:
    return BedrockModel(
        model_id=os.environ.get("MODEL_ID", DEFAULT_MODEL_ID),
        region_name=REGION,
        max_tokens=2000,
        temperature=0.2,
    )


ASKER_FIELDS = ("byTitle", "firstName", "rapport")


GARY = re.compile(r"\bgary\b", re.IGNORECASE)

# Topics where the Gary humor is switched off. The agent also uses its own judgment;
# this list makes the common cases certain. Add terms here as needed.
SENSITIVE = re.compile(
    r"membership council|disciplin|withdraw|excommunicat|confidential|abuse|"
    r"tithing (?:record|amount|statement)|donation (?:record|amount)|"
    r"health|medical|illness|hospital|divorce|suicid|death|died|passed away|funeral|"
    r"addiction|arrest|police|court",
    re.IGNORECASE,
)


def _asker_block(asker: dict | None, question: str = "") -> str:
    """Per-request context: who is asking (from AllowedPhones) and whether they mentioned Gary."""
    lines = []
    if isinstance(asker, dict):
        fields = {f: " ".join(str(asker.get(f) or "").split())[:60] for f in ASKER_FIELDS}
        for field, value in fields.items():
            if value:
                lines.append(f"{field}: {value}")
        if fields["rapport"].lower() == "friend":
            address = fields["firstName"] or fields["byTitle"]
        else:
            address = fields["byTitle"] or fields["firstName"]
        if address:
            lines.append(f"addressAs: {address}")
    lines.append(f"mentionsGary: {'yes' if GARY.search(question) else 'no'}")
    lines.append(f"sensitiveTopic: {'yes' if SENSITIVE.search(question) else 'no'}")
    return "<asker>\n" + "\n".join(lines) + "\n</asker>\n\n"


def answer(
    question: str,
    vague: bool = False,
    previous_answer: str = "",
    asker: dict | None = None,
) -> str:
    """Answer one clerk question. A fresh agent per question keeps answers independent."""
    question = (question or "").strip()
    if not question:
        return "Enter a question."
    question = question[:MAX_QUESTION_CHARS]
    question = _asker_block(asker, question) + question

    messages = []
    if vague and previous_answer.strip():
        messages = [
            {"role": "user", "content": [{"text": question}]},
            {"role": "assistant", "content": [{"text": previous_answer.strip()[:4000]}]},
        ]
        prompt = VAGUE_FOLLOW_UP
    elif vague:
        prompt = f"{question}\n\n{VAGUE_FOLLOW_UP}"
    else:
        prompt = question

    agent = Agent(
        model=_model(),
        system_prompt=_system_prompt(),
        messages=messages,
        callback_handler=None,
    )
    result = agent(prompt)
    return str(result).strip()


@app.entrypoint
def invoke(payload: dict) -> dict:
    mode = str(payload.get("mode") or "ask")
    if mode != "ask":
        return {"answer": "Training mode isn't available yet."}
    text = answer(
        str(payload.get("question") or ""),
        vague=payload.get("vague") is True,
        previous_answer=str(payload.get("previousAnswer") or ""),
        asker=payload.get("asker"),
    )
    return {"answer": text}


if __name__ == "__main__":
    app.run()
