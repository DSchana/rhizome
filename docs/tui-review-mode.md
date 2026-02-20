# `/review` Mode

Review mode is for practicing and testing knowledge that's already been committed.

## Entering review mode

`/review` opens a selection screen:

- **Select scope** — pick a curriculum, a specific topic, or a tag to review.
- **Select review type:**
  - **Free-form quiz** — the agent generates open-ended questions from knowledge entries; the user answers; the agent evaluates.
  - **Timed quiz** — for entries flagged `speed_testable`. Quick-fire Q&A with a visible timer. Tracks response times.
  - **Browse entries** — not a quiz, just a way to read through committed knowledge. Useful for refreshing memory before a quiz.

## Quiz flow

1. The agent selects entries from the chosen scope (random, weighted by difficulty, or least-recently-reviewed — TBD).
2. A question is presented.
3. The user types their answer.
4. The agent evaluates the answer against the stored knowledge entry and gives feedback (correct, partially correct, incorrect + explanation).
5. Repeat until the user exits or the quiz ends.

## Performance tracking (future)

- Track correct/incorrect per entry over time.
- Surface entries the user struggles with more frequently (spaced repetition logic).
- Display progress stats at the end of a review session.
