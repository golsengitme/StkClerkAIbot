"""Manage who can sign in to the Clerk Assistant (the AllowedPhones table).

    uv run --no-project --with boto3 python scripts/clerkcontact.py list
    uv run --no-project --with boto3 python scripts/clerkcontact.py add 801-555-1234 \
        --title "Brother Jensen" --first Jon --rapport friend
    uv run --no-project --with boto3 python scripts/clerkcontact.py update 801-555-1234 --rapport leadership
    uv run --no-project --with boto3 python scripts/clerkcontact.py update 801-555-1234 --disable
    uv run --no-project --with boto3 python scripts/clerkcontact.py delete 801-555-1234
    uv run --no-project --with boto3 python scripts/clerkcontact.py help

Phone numbers can be typed any way (801-555-1234, (801) 555-1234, +18015551234).
New records are stored as +1XXXXXXXXXX. Existing records are found whatever
format they were saved in, the same way the sign-in page finds them.

Fields:
    phone      the PIN people sign in with (table key)
    byTitle    how the assistant addresses them, e.g. "President Hokanson"
    firstName  used instead of byTitle when rapport is "friend"
    rapport    friend | leadership | (blank)
    enabled    true/false; disabled numbers can't sign in
"""

from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

RAPPORT_CHOICES = ("friend", "leadership", "none")


def digits_of(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


MAX_TEXT = 60


def us_digits(raw: str) -> str:
    """Validate a US phone number and return its 10 digits, or exit with a message."""
    if any(ch.isalpha() for ch in raw):
        raise SystemExit(f"'{raw}' has letters in it. Enter a phone number like 801-555-1234.")
    d = digits_of(raw)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10:
        raise SystemExit(f"'{raw}' isn't a 10-digit US phone number. Enter it like 801-555-1234.")
    if d[0] in "01":
        raise SystemExit(f"'{raw}': the area code ({d[:3]}) can't start with 0 or 1.")
    if d[3] in "01":
        raise SystemExit(f"'{raw}': the exchange ({d[3:6]}) can't start with 0 or 1.")
    return d


def canonical(raw: str) -> str:
    """Store US numbers as +1XXXXXXXXXX."""
    return "+1" + us_digits(raw)


def capitalize_words(value: str) -> str:
    """Uppercase the first letter of each word, leaving the rest alone (McKay stays McKay)."""
    return " ".join(w[:1].upper() + w[1:] for w in value.split())


def clean_text(value: str, label: str) -> str:
    value = capitalize_words(value)
    if not value:
        raise SystemExit(f"{label} can't be blank.")
    if len(value) > MAX_TEXT:
        raise SystemExit(f"{label} is too long ({len(value)} characters; the limit is {MAX_TEXT}).")
    return value


KNOWN_TITLES = ("Brother", "Sister", "Bishop", "President", "Elder")


def checked_title(raw: str) -> str:
    """Clean the title, and warn (but allow) when it doesn't start with a usual title."""
    value = clean_text(raw, "Title")
    first_word = value.split()[0].rstrip(".,").lower()
    if first_word not in (t.lower() for t in KNOWN_TITLES):
        print(f"Note: '{value}' doesn't start with {', '.join(KNOWN_TITLES[:-1])} or {KNOWN_TITLES[-1]}. "
              "Saving it as typed; use 'update --title' if that wasn't intended.")
    return value


def rapport_value(raw: str) -> str:
    value = raw.strip().lower()
    if value not in RAPPORT_CHOICES:
        raise argparse.ArgumentTypeError(
            f"'{raw}' isn't a rapport level. Use one of: {', '.join(RAPPORT_CHOICES)}."
        )
    return value


def candidates(raw: str) -> list[str]:
    """Same formats the sign-in page tries, so existing records are found."""
    trimmed = "".join(raw.split())
    d = digits_of(raw)
    found = [trimmed, d, "+" + d]
    if len(d) == 10:
        found += ["+1" + d, "1" + d]
    if len(d) == 11 and d.startswith("1"):
        found += ["+1" + d[1:], d[1:]]
    out: list[str] = []
    for c in found:
        if c and c != "+" and c not in out:
            out.append(c)
    return out


def find(table, raw: str):
    us_digits(raw)
    for key in candidates(raw):
        item = table.get_item(Key={"phone": key}).get("Item")
        if item:
            return item
    return None


def pretty_phone(phone: str) -> str:
    d = digits_of(phone)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) == 10:
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return phone


def cmd_list(table, _args) -> int:
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    if not items:
        print("No records.")
        return 0
    items.sort(key=lambda i: (str(i.get("byTitle") or "~"), i["phone"]))
    rows = [("Phone", "Title", "First", "Rapport", "Enabled", "Stored as")]
    for i in items:
        rows.append(
            (
                pretty_phone(i["phone"]),
                str(i.get("byTitle") or ""),
                str(i.get("firstName") or ""),
                str(i.get("rapport") or ""),
                "yes" if i.get("enabled") is True else "NO",
                i["phone"],
            )
        )
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    for n, r in enumerate(rows):
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip())
        if n == 0:
            print("  ".join("-" * w for w in widths))
    enabled = sum(1 for i in items if i.get("enabled") is True)
    print(f"\n{len(items)} records, {enabled} enabled.")
    return 0


def cmd_add(table, args) -> int:
    existing = find(table, args.phone)
    if existing:
        print(f"{pretty_phone(args.phone)} is already on the list (stored as {existing['phone']}). "
              "Use 'update' to change it.")
        return 1
    item = {
        "phone": canonical(args.phone),
        "byTitle": checked_title(args.title),
        "firstName": clean_text(args.first, "First name"),
        "enabled": not args.disabled,
    }
    if args.rapport and args.rapport != "none":
        item["rapport"] = args.rapport
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(phone)")
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print("That number was just added by someone else. Run 'list' to check.")
            return 1
        raise
    print(f"Added {pretty_phone(item['phone'])}: {item['byTitle']} ({item['firstName']}), "
          f"rapport {item.get('rapport', '-')}, {'enabled' if item['enabled'] else 'disabled'}.")
    return 0


def cmd_update(table, args) -> int:
    existing = find(table, args.phone)
    if not existing:
        print(f"{pretty_phone(args.phone)} isn't on the list. Use 'add' to add it.")
        return 1
    sets, removes, names, values = [], [], {}, {}

    def set_field(field: str, value) -> None:
        names[f"#{field}"] = field
        values[f":{field}"] = value
        sets.append(f"#{field} = :{field}")

    if args.title is not None:
        set_field("byTitle", checked_title(args.title))
    if args.first is not None:
        set_field("firstName", clean_text(args.first, "First name"))
    if args.rapport is not None:
        if args.rapport == "none":
            names["#rapport"] = "rapport"
            removes.append("#rapport")
        else:
            set_field("rapport", args.rapport)
    if args.enable:
        set_field("enabled", True)
    if args.disable:
        set_field("enabled", False)
    if not sets and not removes:
        print("Nothing to change. Give --title, --first, --rapport, --enable or --disable.")
        return 1

    expression = ""
    if sets:
        expression += "SET " + ", ".join(sets)
    if removes:
        expression += (" " if expression else "") + "REMOVE " + ", ".join(removes)
    kwargs = {
        "Key": {"phone": existing["phone"]},
        "UpdateExpression": expression,
        "ExpressionAttributeNames": {**names, "#phone": "phone"},
        "ConditionExpression": "attribute_exists(#phone)",
        "ReturnValues": "ALL_NEW",
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    item = table.update_item(**kwargs)["Attributes"]
    print(f"Updated {pretty_phone(item['phone'])}: {item.get('byTitle', '')} ({item.get('firstName', '')}), "
          f"rapport {item.get('rapport', '-')}, {'enabled' if item.get('enabled') is True else 'disabled'}.")
    return 0


def cmd_delete(table, args) -> int:
    existing = find(table, args.phone)
    if not existing:
        print(f"{pretty_phone(args.phone)} isn't on the list.")
        return 1
    print("About to permanently delete:")
    print(f"  {pretty_phone(existing['phone'])}  {existing.get('byTitle', '')} ({existing.get('firstName', '')}), "
          f"rapport {existing.get('rapport', '-')}, {'enabled' if existing.get('enabled') is True else 'disabled'}")
    print("To keep the record but block sign-in, use 'update --disable' instead.")
    try:
        reply = input("Are you sure? Type 'yes' to delete: ")
    except EOFError:
        reply = ""
    if reply.strip().lower() != "yes":
        print("Not deleted.")
        return 1
    try:
        table.delete_item(
            Key={"phone": existing["phone"]},
            ConditionExpression="attribute_exists(#phone)",
            ExpressionAttributeNames={"#phone": "phone"},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print("That record was already gone.")
            return 1
        raise
    print(f"Deleted {pretty_phone(existing['phone'])}.")
    return 0


HELP = """clerkcontact: manage who can sign in to the Clerk Assistant

Commands
  list                       show everyone on the list
  add PHONE --title T --first F [--rapport R] [--disabled]
                             add a new person
  update PHONE [--title T] [--first F] [--rapport R] [--enable | --disable]
                             change only the fields you give
  delete PHONE               permanently remove someone (asks "Are you sure?")
  help                       show this message

Fields
  PHONE      the number they sign in with: a 10-digit US number, typed any way
             (801-555-1234, (801) 555-1234, +18015551234)
  --title    how the assistant addresses them, e.g. "President Hokanson";
             a title not starting with Brother, Sister, Bishop, President or
             Elder is saved, with a note in case it was a typo
  --first    first name; used instead of the title when rapport is friend
  --rapport  friend      first name, and good-natured ribbing if they mention Gary
             leadership  title, and a kind reply if they mention Gary
             none        same as leadership; on update, clears rapport
  --disable  block sign-in but keep the record (safer than delete)

Examples
  clerkcontact add 801-555-1234 --title "Brother Sterzer" --first Jon --rapport friend
  clerkcontact update 801-555-1234 --rapport leadership
  clerkcontact update 801-555-1234 --disable
  clerkcontact delete 801-555-1234

Options (before the command)
  --region us-west-2   --profile NAME   --table AllowedPhones
  Each command also takes -h for its own details, e.g. clerkcontact add -h
"""


def cmd_help(_table, _args) -> int:
    print(HELP)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage Clerk Assistant sign-ins (AllowedPhones).")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--profile", default=None, help="AWS profile (default: your default profile)")
    p.add_argument("--table", default="AllowedPhones")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("help", help="show commands, fields and examples")
    sub.add_parser("list", help="show everyone on the list")

    add = sub.add_parser("add", help="add a new person")
    add.add_argument("phone")
    add.add_argument("--title", required=True, help='how to address them, e.g. "Brother Jensen"')
    add.add_argument("--first", required=True, help="first name")
    add.add_argument("--rapport", type=rapport_value, default="none", help="friend, leadership or none")
    add.add_argument("--disabled", action="store_true", help="add without allowing sign-in yet")

    up = sub.add_parser("update", help="change an existing person")
    up.add_argument("phone")
    up.add_argument("--title")
    up.add_argument("--first")
    up.add_argument("--rapport", type=rapport_value, help="friend, leadership, or none to clear it")
    state = up.add_mutually_exclusive_group()
    state.add_argument("--enable", action="store_true")
    state.add_argument("--disable", action="store_true")

    rm = sub.add_parser("delete", help="permanently remove a person (asks first)")
    rm.add_argument("phone")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command in (None, "help"):
        return cmd_help(None, args)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    table = session.resource("dynamodb").Table(args.table)
    commands = {"list": cmd_list, "add": cmd_add, "update": cmd_update, "delete": cmd_delete}
    try:
        return commands[args.command](table, args)
    except ClientError as error:
        print(f"AWS error: {error.response['Error'].get('Message', error)}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
