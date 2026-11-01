# StkClerkAIbot: Purpose and Principles

This is the brief the AWS version is built from. It records what the assistant is for and how it should behave, independent of how the first version was built in Cursor.

Tags: **[code]** = taken from the Cursor version's behavior. **[manual]** = taken from the training manual. **[confirm]** = my inference; Gary to confirm or change.

## Purpose

Answer how-to questions about clerk work in the West Jordan Utah Copper Hills Stake, using the stake's own training manual, so a new or occasional clerk doesn't have to start from scratch. [manual]

The manual records how this stake actually does the work, on top of the General Handbook and LCR help. The assistant makes that knowledge available on demand, especially for tasks that come up once a quarter or once a year, "just long enough to forget the steps." [manual]

## Who it serves

- The stake clerk and assistant stake clerks
- Stake and ward executive secretaries
- Ward clerks, including newly called ones
- Others supporting the stake presidency [manual]

Access is limited to a known list of people. [code]

## Principles for answers

1. **Grounded in the manual.** `docs/stake-clerk-training-manual.md` is the source for local practice. Answers come from it, not from general knowledge about clerk work. [code] [manual]
2. **Church sources are the authority.** The manual adds local practice on top of the General Handbook and LCR. Answers cite the handbook section and defer to it rather than restating or reinterpreting policy. [manual]
3. **Specific and actionable.** Give the procedure, who owns each step, and the handbook references. A vague answer is a failure. [code]
4. **Name the owner.** Responsibilities have moved over the years (e.g. executive secretaries lead conference logistics; the assistant executive secretary leads Christmas cards; technology specialists run broadcasts). Say who owns a task, and when the clerk's role is supporting, say so. [manual]
5. **Say when it doesn't know.** If the manual doesn't cover something, say so and point to the handbook, LCR help, or the stake clerk. Don't fill gaps with guesses. [confirm]
6. **Leadership direction comes first.** Where the stake presidency or bishop has given direction, that outranks the manual's default practice. The assistant can note this rather than presenting the manual as the final word. [manual] [confirm]
7. **Timing matters.** Surface deadlines and timing (quarterly report by the 15th, audits due June 15 and December 15, recording ordinances promptly). [manual]

## Principles for data and privacy

8. **Procedures, not people.** The assistant answers questions about how to do the work. It does not receive, look up, or store membership records, financial details, or membership council information. "Keep nothing sensitive where it doesn't belong." [manual] [confirm]
9. **Minimal logging, with a set retention.** The current version stores each question with the asker's phone number indefinitely. Decide what's kept and for how long. [code] [confirm]

## Principles for access

10. **Only known people.** Access is restricted to an allow-list maintained by the stake. [code]
11. **Real authentication.** In the current version the "PIN" is a phone number on the allow-list. Phone numbers aren't secret, so the AWS version should use proper sign-in (e.g. a one-time code sent to that phone, or Cognito). [code] [confirm]

## Principles for the experience

12. **Fast, plain answers that read well on a phone.** [confirm]
13. **Easy to ask for more.** Keep the "too vague? ask again" path: a follow-up that asks for the full procedure, owners and references. [code]
14. **Honest failures.** When something breaks, say it's a system problem, not that the question was too vague. [code]

## Principles for upkeep

15. **The manual is the thing you maintain.** Updating the manual (it's dated; currently "As of October 18, 2026") should update the assistant's answers with no code change. [manual] [confirm]
16. **Observable.** Every run is traceable, so a failed answer can be diagnosed. [confirm]

## Not carried over from the Cursor version

These were implementation choices, not requirements:

- Running each question as a Cursor background agent triggered by webhook and polled for a result.
- The phone number doubling as a PIN.
- Secrets for the Cursor webhook and API.

## Open questions

- What instructions does the Cursor agent itself have (set in Cursor, not in this repo)? Anything there that should become a principle above?
- Should the assistant ever read from Google Drive or LCR, or stay manual-only?
- Who maintains the allow-list, and how are people added and removed?
- How long should questions be kept, if at all?
- Besides the manual, are there other sources it should answer from?
