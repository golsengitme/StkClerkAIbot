"""Clerk Assistant website: sign-in, questions, and the hand-off to the AgentCore agent.

Flow:
    POST /api/sign-in      phone number (the PIN) checked against AllowedPhones -> session cookie
    GET  /api/me           who is signed in (for the greeting)
    POST /api/ask          saves the question as RUNNING, starts a background run, returns its id
    GET  /api/ask/<id>     the page polls this until the status is FINISHED or ERROR
    background run         this same Lambda, invoked asynchronously with {"clerkWorker": id};
                           calls the AgentCore runtime and writes the answer back

The background run exists because API Gateway cuts requests off at ~30 seconds and an
answer can take longer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import traceback
import uuid
from pathlib import Path

import boto3

PHONES_TABLE = os.environ.get("PHONES_TABLE", "AllowedPhones")
QUESTIONS_TABLE = os.environ.get("QUESTIONS_TABLE", "ClerkQuestions")
SECRET_ID = os.environ.get("SECRET_ID", "stk-clerk/cursor")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
SESSION_SECONDS = 12 * 60 * 60
COOKIE_NAME = "stk_session"
MAX_QUESTION_CHARS = 2000
STALE_SECONDS = 5 * 60  # a RUNNING question older than this is reported as failed
ASKER_FIELDS = ("byTitle", "firstName", "rapport")
DONE = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}

_secrets = None
_dynamodb = boto3.resource("dynamodb")
_index = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")


# ---------------------------------------------------------------- routing

def lambda_handler(event, context):
    if isinstance(event, dict) and event.get("clerkWorker"):
        return run_worker(str(event["clerkWorker"]))

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath") or "/"
    if method == "GET" and path == "/":
        return _html(_index)
    if method == "POST" and path == "/api/sign-in":
        return sign_in(event)
    if method == "POST" and path == "/api/sign-out":
        return sign_out()
    if method == "GET" and path == "/api/me":
        return me(event)
    if method == "POST" and path == "/api/ask":
        return ask(event, context)
    if method == "GET" and path.startswith("/api/ask/"):
        return answer(event, path.removeprefix("/api/ask/"))
    return _json(404, {"error": "Not found"})


# ---------------------------------------------------------------- endpoints

def sign_in(event):
    record = _listed_record(str(_body(event).get("pin") or ""))
    if record is None:
        return _json(401, {"error": "That PIN is not recognized."})
    token = _sign_session({"phone": record["phone"], "exp": _now() + SESSION_SECONDS})
    return _json(200, {"ok": True, **_greeting(record)}, cookies=[_cookie(token, SESSION_SECONDS)])


def sign_out():
    return _json(200, {"ok": True}, cookies=[_cookie("", 0)])


def me(event):
    phone = _session_phone(event)
    record = _enabled_record(phone) if phone else None
    if record is None:
        return _json(200, {"signedIn": False})
    return _json(200, {"signedIn": True, **_greeting(record)})


def ask(event, context):
    phone = _session_phone(event)
    if phone is None:
        return _json(401, {"error": "Sign in again."})
    if _enabled_record(phone) is None:
        return _json(401, {"error": "Sign in again."}, cookies=[_cookie("", 0)])

    body = _body(event)
    question = str(body.get("question") or "").strip()
    if not question:
        return _json(400, {"error": "Enter a question."})
    if len(question) > MAX_QUESTION_CHARS:
        return _json(400, {"error": f"Keep the question under {MAX_QUESTION_CHARS} characters."})

    question_id = str(uuid.uuid4())
    item = {
        "id": question_id,
        "phone": phone,
        "question": question,
        "status": "RUNNING",
        "createdAt": _now(),
    }
    if body.get("vague") is True:
        item["vague"] = True
        previous = str(body.get("previousAnswer") or "").strip()[:4000]
        if previous:
            item["previousAnswer"] = previous
    table = _dynamodb.Table(QUESTIONS_TABLE)
    table.put_item(Item=item)

    try:
        boto3.client("lambda").invoke(
            FunctionName=context.invoked_function_arn,
            InvocationType="Event",
            Payload=json.dumps({"clerkWorker": question_id}).encode(),
        )
    except Exception:
        print(f"[{question_id}] could not start background run\n{traceback.format_exc()}")
        _finish(question_id, "ERROR", "", "could not start background run")
        return _json(502, {"error": "Something went wrong on our end. Try again in a moment."})

    return _json(200, {"id": question_id, "status": "RUNNING"})


def answer(event, question_id):
    phone = _session_phone(event)
    if phone is None:
        return _json(401, {"error": "Sign in again."})
    item = _dynamodb.Table(QUESTIONS_TABLE).get_item(Key={"id": question_id}).get("Item")
    if not item or item.get("phone") != phone:
        return _json(404, {"error": "Question not found."})

    status = str(item.get("status") or "RUNNING")
    if status not in DONE and _now() - int(item.get("createdAt") or 0) > STALE_SECONDS:
        print(f"[{question_id}] still RUNNING after {STALE_SECONDS}s; marking EXPIRED")
        _finish(question_id, "EXPIRED", "", "timed out waiting for the agent")
        status = "EXPIRED"
    if status == "FINISHED":
        return _json(200, {"status": status, "answer": item.get("answer") or ""})
    return _json(200, {"status": status, "answer": ""})


# ---------------------------------------------------------------- background run

def run_worker(question_id: str):
    table = _dynamodb.Table(QUESTIONS_TABLE)
    item = table.get_item(Key={"id": question_id}).get("Item")
    if not item:
        print(f"[{question_id}] worker: question not found")
        return {"ok": False}
    if item.get("status") in DONE:
        return {"ok": True}  # duplicate delivery; already handled

    started = time.time()
    try:
        record = _record(item["phone"]) or {}
        payload = {
            "question": item["question"],
            "mode": "ask",
            "asker": {f: str(record[f]) for f in ASKER_FIELDS if record.get(f)},
        }
        if item.get("vague"):
            payload["vague"] = True
            if item.get("previousAnswer"):
                payload["previousAnswer"] = item["previousAnswer"]

        text = _call_agent(question_id, payload)
        if not text:
            raise RuntimeError("agent returned an empty answer")
        _finish(question_id, "FINISHED", text)
        print(f"[{question_id}] finished in {time.time() - started:.1f}s")
        return {"ok": True}
    except Exception as error:
        print(f"[{question_id}] agent call failed after {time.time() - started:.1f}s\n{traceback.format_exc()}")
        _finish(question_id, "ERROR", "", f"{type(error).__name__}: {error}"[:500])
        return {"ok": False}


def _call_agent(question_id: str, payload: dict) -> str:
    if not AGENT_RUNTIME_ARN:
        raise RuntimeError("AGENT_RUNTIME_ARN is not set")
    response = boto3.client("bedrock-agentcore").invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        runtimeSessionId=f"q-{question_id}",  # one session per question; must be 33+ chars
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode(),
    )
    raw = response["response"].read().decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"agent returned non-JSON: {raw[:200]!r}")
    if not isinstance(parsed, dict):
        raise RuntimeError(f"agent returned unexpected JSON: {raw[:200]!r}")
    return str(parsed.get("answer") or "").strip()


def _finish(question_id: str, status: str, answer_text: str, error: str = ""):
    names = {"#s": "status"}
    values = {":s": status, ":a": answer_text, ":t": _now()}
    expression = "SET #s = :s, answer = :a, finishedAt = :t"
    if error:
        expression += ", errorDetail = :e"
        values[":e"] = error
    _dynamodb.Table(QUESTIONS_TABLE).update_item(
        Key={"id": question_id},
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


# ---------------------------------------------------------------- people

def _record(phone: str):
    return _dynamodb.Table(PHONES_TABLE).get_item(Key={"phone": phone}).get("Item")


def _enabled_record(phone: str):
    record = _record(phone)
    return record if record and record.get("enabled") is True else None


def _listed_record(raw: str):
    for candidate in _pin_candidates(raw):
        record = _enabled_record(candidate)
        if record:
            return record
    return None


def _greeting(record: dict) -> dict:
    name = record.get("firstName") if record.get("rapport") == "friend" else record.get("byTitle")
    return {"name": str(name or record.get("byTitle") or "")}


def _pin_candidates(raw: str) -> list[str]:
    trimmed = "".join(raw.split())
    digits = "".join(ch for ch in raw if ch.isdigit())
    candidates: list[str] = []
    if trimmed:
        candidates.append(trimmed)
    if digits:
        candidates.append(digits)
        candidates.append("+" + digits)
    if len(digits) == 10:
        candidates.append("+1" + digits)
        candidates.append("1" + digits)
    if len(digits) == 11 and digits.startswith("1"):
        candidates.append("+" + digits)
        candidates.append(digits)
        candidates.append("+1" + digits[1:])
        candidates.append(digits[1:])
    seen: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


# ---------------------------------------------------------------- sessions

def _session_phone(event):
    token = _cookies(event).get(COOKIE_NAME)
    if not token:
        return None
    payload = _read_session(token)
    if not payload:
        return None
    phone = payload.get("phone")
    exp = payload.get("exp")
    if not isinstance(phone, str) or not isinstance(exp, int) or exp < _now():
        return None
    return phone


def _sign_session(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(_load_secrets()["cookieSecret"].encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def _read_session(token: str):
    body, dot, sig = token.partition(".")
    if not dot or not body or not sig:
        return None
    expected = hmac.new(
        _load_secrets()["cookieSecret"].encode(), body.encode(), hashlib.sha256
    ).digest()
    try:
        given = _b64decode(sig)
    except Exception:
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_secrets():
    global _secrets
    if _secrets is None:
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ID)["SecretString"]
        value = str(json.loads(raw).get("cookieSecret") or "").strip()
        if not value:
            raise RuntimeError("missing cookieSecret")
        _secrets = {"cookieSecret": value}
    return _secrets


# ---------------------------------------------------------------- http helpers

def _body(event) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cookies(event) -> dict:
    found = {}
    for entry in event.get("cookies") or []:
        name, sep, value = entry.partition("=")
        if sep:
            found[name] = value
    return found


def _cookie(value: str, max_age: int) -> str:
    return f"{COOKIE_NAME}={value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"


def _html(page: str):
    return {
        "statusCode": 200,
        "headers": {"content-type": "text/html; charset=utf-8", "cache-control": "no-store"},
        "body": page,
    }


def _json(status: int, payload: dict, cookies: list[str] | None = None):
    response = {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(payload),
    }
    if cookies is not None:
        response["cookies"] = cookies
    return response


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _now() -> int:
    return int(time.time())
