
- Big problem:
    - Becomes very laggy during long conversations - python limitation with a lot of widgets

- Bug: /<group> <subcmd> --help doesn't work - just shows group --help
    - need another way of capturing stdout here
- Bug: ctrl+c to interrupt agent message (while it's streaming tokens, not tool calls) omits the agent message from the message history, since it never becomes an "update" in the agent's stream (which is how we track messages)
- Potential Bug: OCCASIONALLY, prompt caching isn't enabled until a rebuild of the state graph is triggered - not sure why?
    - happens with both builtin and custom anthropic prompt caching middleware
    - haven't noticed it in a little while though?
    - seems like it might just take a few back-and-forths to kick in? keep an eye on this though
- Bug: ctrl+q while an interrupt widget is open seems to crash the program ("no nodes match msg-collapse" error?)
- Bug: ctrl+l input while focused on a tab seems to get eaten - can't return to the chat input area
- Bug: ctrl+pagedown _into_ a tab where an interrupt is occurring sometimes doesn't work (flashes for a frame, then goes back)
    - Or might have to do something with the type of pane you're starting in - logs pane being fine, but chat pane no?

- Bug: in commit workflow:
    - invoke subagent
    - revise proposal
    - ctrl+e and submit
    - reinvoke subagent
    - ERROR: "sequence item 2: expected str instance, list found"

- TO INVESTIGATE:
    - The commit subagent seems a little unreliable, specifically when the structured response schema is a dataclass and not a pydantic model.
    - When just dataclasses, the agent repeatedly responded with '{"entries": []}'

- I _think_ rebuilding the agent flushes the message state now, causing token counts to be wrong
- token counts are _way_ higher after web search/fetch tools (predictably, but not sure how to detect that)

- definitely need a way to view knowledge entries in a widget, like /topics

- double esc to clear text input area
- base agent etxt should be light grey, not pure white - potentially cccccc or a5a5a5?
- disabling caching needs to disable the cache usage display in the status bar

- commit subagent created a bunch of topics without approval
    - moreover, after a ctrl+a, with user edits, agent doesn't know about the edits, thinks something went wrong
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

- style guide for the agent: how to use colour in the markdown output?

- commit instructions
- rename tab tool should have context about max tab len
- fix token usage counting
- ChatPane.confirm_commit_selection() takes 1 positional argument but 2 were given
    - "escape" from commit selection with no selected messages?
- topic selector widget could be reactive?
- commit proposalI thinnkt

- maybe provide some context automatically to the subagent when invoking it for the first time (e.g. selected topic, etc.)
- improve the effect of the planning-verbosity setting (even "low" often leads to multiple rounds of tool-calls and messages)
- something seems wrong with the token counting - it said I was at 5,000 at one point, then down to 4,677 at another
- double check that answer-verbosity is actually working
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

- "done" in the options widget should say what changed
- CSS issues now with the commit-selected borders
- command input shouldn't necessarily be blocked while the agent is thinking (e.g. /logs - no reason to wait)
- interrupts don't scroll message area to the end

- /clear should reset the status bar as well (refresh token usage, topic, mode)
    - need to think this through
- /topics select <topic> and /topics list or find or something
- user input should allow typing a custom message
    - for some reason first option isn't highlighted on mount, only when an arrow key is pressed - might be a redraw issue again
- can hover over the (+X) token indicator to have it display what it means
- rename CurriculumApp to RhizomeApp
- provide agent with a tool to just list all the topics in a flat order
- remove from future import __annotations__ everywhere
- cleanup imports
- dynamic system prompts option?
    - use different system prompts for review/learn/idle mode - invalidates the cache when context-switching but allows for separate system prompts per mode
    - cache may still match after switching if ttl is high enough

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