# clerkcontact: managing who can use the Clerk Assistant

`clerkcontact` manages the list of people who can sign in at
clerk.ginkgointernational.com. Each person is one record in the `AllowedPhones`
DynamoDB table (us-west-2), keyed by the phone number they sign in with.

## One-time setup

You need the AWS CLI signed in to the account that owns the site, and
[uv](https://docs.astral.sh/uv/).

Add this line to `~/.zshrc` so `clerkcontact` works from any folder:

```bash
alias clerkcontact='uv run --no-project --with boto3 python ~/Documents/GitHub/StkClerkAIbot/scripts/clerkcontact.py'
```

Open a new terminal (or run `source ~/.zshrc`), then check it works:

```bash
clerkcontact help
clerkcontact list
```

## What's in a record

| Field | Example | What it does |
|---|---|---|
| phone | `801-555-1234` | The number they sign in with. Type it any way; it's stored as `+18015551234`. Must be a valid 10-digit US number. |
| title (`byTitle`) | `President Hokanson` | How the assistant addresses them. |
| first name (`firstName`) | `Robert` | Used instead of the title when rapport is `friend`. |
| rapport | `friend`, `leadership`, or blank | Sets how the assistant talks to them (below). |
| enabled | yes / no | Disabled people can't sign in. |

Titles and first names are capitalized automatically (`gary` becomes `Gary`;
`McKay` is left alone). A title that doesn't start with Brother, Sister,
Bishop, President or Elder is still saved, with a note in case it was a typo.

### Rapport levels

- **friend**: the assistant uses their first name. If they mention Gary, it
  opens with a line of good-natured ribbing (at Gary's expense, never theirs).
- **leadership**: the assistant uses their title. If they mention Gary, it
  replies with a kind "I'm not Gary, but I learned from his notes" line.
- **blank**: same as leadership.

On sensitive topics (membership councils, health, deaths and similar) there's
no humor for anyone, whatever their rapport.

## Everyday tasks

**See everyone**
```bash
clerkcontact list
```

**Add a new clerk**
```bash
clerkcontact add 801-555-1234 --title "Brother Sterzer" --first Jon --rapport friend
clerkcontact add 801-555-9876 --title "President Hokanson" --first Robert --rapport leadership
clerkcontact add 801-555-2222 --title "Sister Ortiz" --first Ana
```
Add `--disabled` to create the record without letting them sign in yet.

**Fix a typo or change a title** (only the fields you give are changed)
```bash
clerkcontact update 801-555-1234 --title "Brother Sterzer"
clerkcontact update 801-555-1234 --first Jon
```

**Change or clear rapport**
```bash
clerkcontact update 801-555-1234 --rapport leadership
clerkcontact update 801-555-1234 --rapport none
```

**Someone is released or should lose access**

Disabling is usually best: they're locked out right away (even mid-session),
and the record is kept so you can re-enable them later.
```bash
clerkcontact update 801-555-1234 --disable
clerkcontact update 801-555-1234 --enable
```

**Remove someone permanently**
```bash
clerkcontact delete 801-555-1234
```
It shows the record and asks "Are you sure?". Only typing `yes` deletes it.

## Troubleshooting

- **"isn't a 10-digit US phone number"** / **"area code can't start with 0 or 1"**:
  check the number; extensions and short numbers aren't accepted.
- **"already on the list"** when adding: the number exists (possibly saved in
  another format). Use `update` instead.
- **"isn't on the list"** when updating: run `clerkcontact list` to see how it's stored.
- **AWS errors** (expired credentials, access denied): run `aws sts get-caller-identity`
  to check which account you're signed in to.
- Different region, profile or table: put `--region`, `--profile` or `--table`
  before the command, e.g. `clerkcontact --profile other list`.
