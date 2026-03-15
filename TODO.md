
- Big problem:
    - Becomes very laggy during long conversations - python limitation with a lot of widgets
    - Could possibly "off-load" early conversational widgets after a while? Add a "conversation continues above (click to expand)" at the top of the conversation area?

- Bug: /<group> <subcmd> --help doesn't work - just shows group --help
    - need another way of capturing stdout here
- Potential Bug: OCCASIONALLY, prompt caching isn't enabled until a rebuild of the state graph is triggered - not sure why?
    - happens with both builtin and custom anthropic prompt caching middleware
    - haven't noticed it in a little while though?
    - seems like it might just take a few back-and-forths to kick in? keep an eye on this though
- Bug: ctrl+q while an interrupt widget is open seems to crash the program ("no nodes match msg-collapse" error?)
    - This "no nodes match msg-collapse" occurs frequently on Ctrl+q during certain actions
- Bug: ctrl+pagedown _into_ a tab where an interrupt is occurring sometimes doesn't work (flashes for a frame, then goes back)
    - Or might have to do something with the type of pane you're starting in - logs pane being fine, but chat pane no?

- Bug: in commit workflow:
    - invoke subagent
    - revise proposal
    - ctrl+e and submit
    - reinvoke subagent
    - ERROR: "sequence item 2: expected str instance, list found"

- Small validation improvements:
    - rename_tab should reject empty tabs and tabs that are too long
    - rename_tab should reject newlines
    - ask_user_input shouldn't allow empty lists of questions
    - Multiple instances of "ask_user_input" cannot be posted at once - langchain needs us to specify the interrupt ID
        - could also address this by just automatically merging the two interrupts into a single widget and routing the answers accordingly? Seems very finnicky tho - we should probably just disallow this behaviour entirely.
    - Switching modes should queue a system message that the mode changed for the agent - otherwise it has no way of detecting that it swapped modes (it doesn't have reflection on it's own system prompt, of course)


- Claude code todos:
    - Introduce "low-hanging fruit" and "overnights" - things for it to do while I'm sleeping
    - Introduce "scratchpads" for various topics - organize as a depth-2 tree (contents.md and individual scratchpads)
        - idea is to save us some usage cost by not having to re-explore codebases/libraries to figure something out
    - Introduce scheduled tasks
        - Review/update documentation
        - Check what's in/out of sync
        - 

- TO INVESTIGATE:
    - The commit subagent seems a little unreliable, specifically when the structured response schema is a dataclass and not a pydantic model.
    - When just dataclasses, the agent repeatedly responded with '{"entries": []}'


BIG REFACTOR TODO:
    - The review agent has been setup in a way that it is practically begging to be a proper langgraph graph, rather than a standalone agent
    - Each phase in the review state machine can be handled by a separate node in the graph (and possibly even a separate subagent with consolidated system prompt) - context is preserved through transitions in the ReviewState
    - Possibly makes more sense to think about the transitions between different agent modes as edges in the graph as well (will have to think about this one).


- make sure the "reorganization" is easy for the agent to do
    - e.g., let's say I don't like my notes on topic X
        - ask the agent to restructure them
        - this will necessarily invalidate previous review sessions or flashcards since the knowledge entry IDs/topic IDs they refer to may not exist anymore
        - we could have the agent automatically update the flashcards following the restructuring of the notes.


- "cleanup" of ephemeral DB state
    - review sessions, and related materials


- minor adjustments to the topic viewer:
    - need to dock the horizontal scroll bar in the topic tree area to the bottom of the _entries_ area
        - tricky because no way to "stretch" the topic/entry areas to be as tall as the tallest of the two with just textual CSS alone - need a callback sadly
    - ensure that vertical scrolling in the topic tree area works - maybe choose a fixed max height
    - maybe just always display the entries? Or maybe hide it to keep the user from peeking if they don't want to
    - what do we do when the database updates? would it be possible to "watch" for updates somehow? How else do we notify that it's stale?
        - maybe just hint "use /topics [-r | --refresh] to refresh the display" after a certain amount of time?
        - same sort of behaviour can happen if we have two separate global options viewer widgets in separate tabs

    - need an easier way of refocusing it - right now I have no idea how to reselect it and navigate around again, if I've begun typing something
    - hint says "ctrl+j" instead of "ctrl+enter" (technically ctrl+j works but)

    - bit of odd behaviour:
        - select a topic with entries
        - press enter to focus on the entries
        - lose focus entirely on the topic widget (e.g. with ctrl+l to return to chat input area)
        - return to topic viewer by clicking on the area "around" a topic name (clicking _on_ it seems to still "select" it)
        - if you clicked on a topic that doesn't have any entries, you'll be in a state where the focus is on the entry viewer, but there's no entries to view
        - you can still easily recover by hitting enter to refocus the topic tree, but it's still confusing, we should avoid it altogether.


- address the code resolving concurrent UI/agent updates to the mode
    - this is all a bit of a mess, but if you want an idea of what's going on, take a look at these three files/areas:
        - agent_mode.py
        - session.py - specifically code engaging with the mode middleware
        - chat_pane.py - specifically the set_mode method

    - This stuff is just brutal to trace the flow through - either we need to come up with a different structure or figure out a way to simplify/document the existing.


- commit workflow adjustment
    - idea is as follows: during the workday I ask it a bunch of random questions (with verbosity set to terse), then I ask to create a commit proposal at the end of the day
    - right now, I think the commit workflow is best suited for when the _organization_ of knowledge entries into topics is decided "implicitly" through the conversation, and it's not really structured for "disorganized" commits.
    - we need to update the system prompt for creating commit proposals to allow the agent to suggest the best organization/decomposition of the commit payload into knowledge entries/topics as well.
    - actually, I think the system prompt in general (the shared part) might not be suited for this workflow either, as it'll do things like switch to learn mode, browse topics, try to select topics, etc.


- review mode adjustments
    - always ask "anything else?" when configuring

    - an interaction that doesn't really make sense:
        - agent asked me about file systems
        - I responded, but I didn't cover everything in my notes
        - agent responded with "your notes emphasize that filesystems must answer several key design questions - things like how to recover from a crash, how to handle large vs small files, whether to verify data integrity, and what advanced features (snapshots, compression, RAID) to support. These trade-offs are what differentiate one filesystem from another."

            - indicate that notes are _just guides_, and not _intended_ to be rotely memorized by the user
            - indicate that notes are _inherently incomplete_ through the process of learning/reviewing
            - indicate that notes are _not to be treated as gospel_.

        - it does seem way to primed to critique based on how well I can recite my own notes, I need to make it more explicitly clear that that's _not_ the intention

    - maybe we should have an "active learning" phase as well, that focuses 

    - indicate that it's safe to switch off the review state and return later - review state is preserved.

    - it's VERY tough on you right now - judges fairly harshly
    - still doesn't have a good lens on writing flashcards, e.g. one of the ones it came up with was
        - "which common linux filesystem cannot be shrunk in-place?" answer: xfs
        - not sure why it zeroed in on that one.


    - the review mode process, first time around, doesn't really make sense without just _seeing_ the flashcards that were made first.
    - give it a tool to update the scope after the fact
        - couldn't remove flashcards


```
(START) → SCOPING → CONFIGURING → PLANNING → REVIEWING ⟲ → SUMMARIZING → (END)
                                     ↓           ↑
                                  PRACTICING ⟲ -/
```


- use a proper migration framework now that the database is getting more mature

- add an "setup" screen for when the user hasn't configured their provider

- we _definitely_ should try a vector store now for knowledge entries - that way the agent can run "fuzzy search" queries across the entire database (or parts of the database) without needing to fully understand the structure.
    - Helpful in review mode when generating cross-pollinated questions

- definitely want a "notes" feature - keep tabs on things that have happened throughout the conversation that aren't immediately relevant to the conversation.

- token counts are _way_ higher after web search/fetch tools (predictably, but not sure how to detect that)
    - this is because of the silly way anthropic web fetch actually works

- when we delete a topic that's currently selected, maybe the status bar should update to?
    - check if it stores anything relevant to the DB that could cause errors.
    - also would need to notify to any topic viewers that the view is stale?

- commit subagent created a bunch of topics without approval
    - moreover, after a ctrl+a, with user edits, agent doesn't know about the edits, thinks something went wrong if you removed entries
- commit proposal widget - ctrl+e, you should still be able to navigate through the entries to see what they represent

- changes to the commit proposal made by the user before running "edit" aren't propagated
- What to do about the following workflow:
    - Commit proposal includes some dangling topics we didn't actually work on, but want to make a note about them for the future
    - "Threads"?

- What to do about lists in knowledge entries?
    - Notoriously difficult to memorize
    - Same with "tables" of comparisons
- Maybe entries should also have "testing notes"? Notes on how to use them in review mode?

- subterminal/pane for sqlite to interact with the database?
    - general purpose "sqlite" tool for the agent, which always requests approval of the command it wants to run?


- idea: option to "dock" certain widgets to certain areas of the screen (e.g. the topic selector widget to be directly above the input area)

- style guide for the agent: how to use colour in the markdown output?
    - tricky with the markdown style rendering - if we switched to just rich formatting maybe it'd be better?
        - need to figure out if we lose:
            - headers, tables, horizontal partitions, quote blocks, code, etc.
    - maybe just veto this one

- commit instructions
- ChatPane.confirm_commit_selection() takes 1 positional argument but 2 were given
    - "escape" from commit selection with no selected messages?
- topic selector widget could be reactive?

- maybe provide some context automatically to the subagent when invoking it for the first time (e.g. selected topic, etc.)
- need to figure out what to do when user's selected messages don't make sense for a commit
- agent should say at least a little something when it begins a conversation with a subagent, so the user isn't left hanging
- AgentSession.stream should probably just be called .respond now, since it doesn't yield anything anymore
- agent seems hesitant to rename the tab - e.g. "I want to learn about the gcloud CLI" doesn't automatically trigger a rename
- a note on the auto-commit tool
    - should be used cautiously to avoid committing hallucinations
    - perhaps roll in _batches_ - use user guidance from the conversation to determine what's true and what's not, only commit with a certain confidence?
    - enabling auto-commit should post a one-time system message warning about how to use safely
    - expose an auto-commit frequency option
    - expose auto-commit USER_PROMPT.md, optional instructions depending on how the user likes to generate their knowledge entries
- commit subagent tools that modify the selectables also modify the payload, forcing a rewrite of the conversation
- commit payload should contain the user message directly above by default? Otherwise the subagent might struggle with context

- another thing to think about:
    - sometimes, I want to ask questions that aren't really individual factoids, but are things I might still want to retain some knowledge about
    - e.g., "what's the command to git checkout HEAD on everything _but_ a specific file"
    - in this case the answer is `git checkout HEAD -- ':!path/to/file'`, using git's pathspec syntax
    - we don't want a knowledge entry on _just_ this specific question, but maybe add
    - in review 

- interrupts don't scroll message area to the end


- /clear should reset the status bar as well (refresh token usage, topic, mode)
    - need to think this through
- /topics select <topic> and /topics list or find or something
- for some reason in choices interrupt, first option isn't highlighted on mount, only when an arrow key is pressed - might be a redraw issue again
- can hover over the (+X) token indicator to have it display what it means
- rename CurriculumApp to RhizomeApp

- message ping doesn't really work (at least not in my terminal context)

google models:
    - gemini-3.1-pro-preview - https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview
    - gemini-3-flash-preview - https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview
    - gemini-2.5-flash - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash
    - gemini-2.5-flash-lite - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite
    - gemini-2.5-pro - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro


Ideas:
- a shortcut to "find dangling threads in the conversation history", maybe "/next"
- "research-eagerness" setting
- Limit the number message window size used by the agent
    - Display this limit visually in the scroll (possibly on the right side rather than the left)
- A way to save/restore sessions
- A little welcome visual on your topics, maybe showing which ones are most practiced, which ones need review, etc.
- In /commit mode after a proposal is made, use a structured output to allow the user to walk through the proposed knowledge entries in a widget and expand/collapse them if they're too long.
- /logs <namespace> to view a specific level of logs
- themes? grab _all_ colours in the app and expose them as an editable file
- A separate pane to see subagents thinking (e.g. for research with resources)
- comprehensive token usage breakdown panel
    - token usage treated as "events" - each event delineating the change in token usage per category
    - token usage events linked to message IDs, so you can click on token usage events to ping the message the event corresponds to
    - token usage events can be displayed in a clickable graph (deltas to minimize widget height)
        - how do summarization events show up?

    - Offer direct anthropic token usage counts: https://platform.claude.com/docs/en/build-with-claude/token-counting

- how to deal with jailbreaking?
- anthropic "fast" mode: https://platform.claude.com/docs/en/build-with-claude/fast-mode

- Continuous summarization middleware
    - https://platform.claude.com/cookbook/misc-session-memory-compaction
- "Resources" per topic
    - How should these be looped in?
        - Direct - just load into context window whenever topic is selected
        - Direct w/ usage description - load into context window selectively, based on usage description
        - RAG based - load into separate vector store, use subagent to perform retrieval/summarization/deep research for Q/A
    - Could be local documents, pdfs, websites
    - "free form" deep research option that uses API extended thinking with tools (web search, etc.)
- Add a "subagents for session X" pane to see raw output, monitor, cancel, or maybe even provide guidance through chat messages?


Thoughts on review mode:
    - "conversational" style review 
        - ask leading questions to prompt user discussion
        - pull in context as necessary
        - respond to their questions as the conversation develops - could potentially become some new knowledge entries, etc.

    - "ask all first, then mark at the end"
    - "ask and critique one-by-one"
    - speed tests

    - "question complexity and recombination" criterion
        - do we treat the questions as anki cards, or recombine them to create new questions that test user knowledge?
        - e.g., if the user has knowledge entries on both "git" and "git pathspec", ask them questions like "how would you checkout HEAD on everything _except_ a specific glob?"






Things to think about:
- RAG with https://docs.langchain.com/oss/python/langchain/rag
    - semantic search
- Reranking
- FalkorDB
- BM25




Modes:
    - "learn"
    - "work"
        - idea: at work I'll just ask for basic things, then review them at the end of the day
    - "notes"
        - idea: while reading a book or something, I'll make notes about the things I'm reading and then we'll review afterwards, instead of having the llm be the source of truth
    - "review"
    - "refresh"
        - idea: Just review the notes instead of quizzing