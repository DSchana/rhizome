
# TODO

## Bugs

### /<group> <subcmd> --help
- Running `/<group> <subcmd> --help` doesn't work - just shows group --help
- need another way of capturing stdout here

### ctrl+pageup/pagedown into a tab with an interrupt
- Noticed that ctrl+pageup/ctrl+pagedown into a tab where an interrupt is occurring sometimes doesn't work (flashes for a frame, then goes back)
- Or might have to do something with the type of pane you're starting in - logs pane being fine, but chat pane no?

### ctrl+q occasionally crashing the program instead of gracefully exiting
- Example: when an interrupt widget is active the program crashes on `ctrl+q` with a "no nodes match msg-collapse" error

### Commit workflow with subagent and additional user tuning
- Steps to reproduce:
    - invoke subagent
    - revise proposal
    - ctrl+e and submit
    - reinvoke subagent
    - ERROR: "sequence item 2: expected str instance, list found"

### Multiple parallel occurrences of ask_user_input causes an error
- Multiple instances of "ask_user_input" cannot be posted at once - langchain needs us to specify the interrupt ID
    - could also address this by just automatically merging the two interrupts into a single widget and routing the answers accordingly? Seems very finnicky tho - we should probably just disallow this behaviour entirely.

## Major Issues & Refactors

### Lag during long conversations
- Becomes very laggy during long conversations - python limitation with a lot of widgets
- Could possibly "off-load" early conversational widgets after a while? Add a "conversation continues above (click to expand)" at the top of the conversation area?
- One idea: switch to rust and ratatui? (Is rust worth the pain?)

### Refactor Concurrent Mode-Switching Handlers
- address the code resolving concurrent UI/agent updates to the mode
    - e.g., how we presently handle this: "agent is thinking, and user updates mode" or "agent is thinking, user updates mode, then agent switches mode through tool call"
- this is all a bit of a mess, but if you want an idea of what's going on, take a look at these three files/areas:
    - agent_mode.py
    - session.py - specifically code engaging with the mode middleware
    - chat_pane.py - specifically the set_mode method

- This stuff is just brutal to trace the flow through - either we need to come up with a different structure or figure out a way to simplify/document the existing.

### Refactor Agent into a proper Langgraph Compiled Graph
- The review agent has been setup in a way that it is practically begging to be a proper langgraph graph, rather than a standalone agent
- Each phase in the review state machine can be handled by a separate node in the graph (and possibly even a separate subagent with consolidated system prompt) - context is preserved through transitions in the ReviewState
- Possibly makes more sense to think about the transitions between different agent modes as edges in the graph as well (will have to think about this one).

## Minor Issues

### Need to update the flashcard presentation in review mode now that we have a proper flashcard practice widget
- Additionally, let's allow the user to type before revealing an answer

### Wire up the subagents to the options widget
- Commit subagent.enabled/disabled is available, but model choice isn't
- Flashcard validator subagents aren't wired at all
- Default models should be the up-to-date ones, not the specific timestamped ones

### Propagate user changes in commit/flashcard proposal widgets to the agent response

### MessageID Middleware still sometimes shows up in the token stream when it shouldn't
- Still seeing some messages that start "[MSG-N]" in the UI when that should be entirely hidden.
- Actually looking at the message dump - the issue seems a little stranger than that, almost wonder if the agent is inserting the "[MSG-N]" itself since sometimes it differs in format from the _injected_ metadata?
- The latest agent message has not been decorated with the metadata in "additional_kwargs", and yet has a "[MSG-10]" prefix - that probably indicates that it's the agent doing this itself.
- System prompt alone isn't preventing this - maybe just make it harsher

### Remove rhizome.agent.middleware.message_ids log messages
- Tend to flood the output

### Move the thinking indicator below the most recent item in the agent message harness container
- Think it's a little more noticeable at the bottom than at the top.

### Add options editor to the "active widgets" list
- needs to post a WidgetDisabled message

### Delete topic cascades to UI state
- when we delete a topic that's currently selected, maybe the status bar should update to?
    - check if it stores anything relevant to the DB that could cause errors.
    - also would need to notify to any topic viewers that the view is stale?

### /clear
- /clear should reset the status bar as well (refresh token usage, topic, mode)
    - need to think this through

### Colour in markdown messages
- style guide for the agent: how to use colour in the markdown output?
    - tricky with the markdown style rendering - if we switched to just rich formatting maybe it'd be better?
        - need to figure out if we lose:
            - headers, tables, horizontal partitions, quote blocks, code, etc.
    - maybe just veto this one

### Commit Worfklow
- commit subagent tools that modify the selectables also modify the payload, forcing a rewrite of the conversation
    - e.g. deselect certain messages
    - maybe just do this through instructions, like "ignore this message"
- commit workflow could possibly utilize the new message ID middleware more?
- need to figure out what to do when user's selected messages don't make sense for a commit
- maybe provide some context automatically to the subagent when invoking it for the first time (e.g. selected topic, etc.)

#### Commit Instructions
In commit mode, after we confirm the selection, we need to provide the user with the option to add additional commit instructions before beginning the proposal process.

#### Commit Proposal System Prompt
- The learn mode agent and the commit proposal subagent need to have their system prompts tuned quite a bit.
- Commit subagent created a bunch of topics without approval
- another thing to think about:
    - sometimes, I want to ask questions that aren't really individual factoids, but are things I might still want to retain some knowledge about
    - e.g., "what's the command to git checkout HEAD on everything _but_ a specific file"
    - in this case the answer is `git checkout HEAD -- ':!path/to/file'`, using git's pathspec syntax
    - we don't want a knowledge entry on _just_ this specific question, so we need to break it down automatically into core entries

#### Commit Proposal Widget UI
When selecting ctrl+e, you should still be able to navigate through the entries to see what they represent

#### Commit Proposal User Edits need to be reflected somehow in what the agent receives
e.g. after a ctrl+a, with user edits, agent doesn't know about the edits, thinks something went wrong if you removed entries

### Review Workflow
- Always ask "anything else?" when configuring
- Tune the system prompt

    - example interaction that doesn't really make sense:
        - agent asked me about file systems
        - I responded, but I didn't cover everything in my notes
        - agent responded with "your notes emphasize that filesystems must answer several key design questions - things like how to recover from a crash, how to handle large vs small files, whether to verify data integrity, and what advanced features (snapshots, compression, RAID) to support. These trade-offs are what differentiate one filesystem from another."

            - indicate that notes are _just guides_, and not _intended_ to be rotely memorized by the user
            - indicate that notes are _inherently incomplete_ through the process of learning/reviewing
            - indicate that notes are _not to be treated as gospel_.

        - it does seem way to primed to critique based on how well I can recite my own notes, I need to make it more explicitly clear that that's _not_ the intention

    - it's VERY tough on you right now - judges fairly harshly
    - still doesn't have a good lens on writing flashcards, e.g. one of the ones it came up with was
        - "which common linux filesystem cannot be shrunk in-place?" answer: xfs
        - not sure why it zeroed in on that one.

- indicate that it's safe to switch off the review state and return later - review state is preserved.

- maybe we should have an "active learning" phase as well
- the review mode process, first time around, doesn't really make sense without just _seeing_ the flashcards that were made first.    


### Topic viewer widget adjustments

#### UI
- Need to dock the horizontal scroll bar in the topic tree area to the bottom of the _entries_ area
    - This is tricky to do because there's no way to "stretch" the topic/entry areas to be as tall as the tallest of the two with just textual CSS alone - need application code to handle this sadly
- Ensure that vertical scrolling in the topic tree area works
    - Might need to choose a fixed max height for this subwidget
- Always display the entries by default?
- Need an easier way of refocusing it - right now I have no idea how to reselect it and navigate around again, if I've begun typing something
- Hint says "ctrl+j" instead of "ctrl+enter" (technically ctrl+j works but)

- Anomalous behaviour:
    - select a topic with entries
    - press enter to focus on the entries
    - lose focus entirely on the topic widget (e.g. with ctrl+l to return to chat input area)
    - return to topic viewer by clicking on the area "around" a topic name (clicking _on_ it seems to still "select" it)
    - if you clicked on a topic that doesn't have any entries, you'll be in a state where the focus is on the entry viewer, but there's no entries to view
    - you can still easily recover by hitting enter to refocus the topic tree, but it's still confusing, we should avoid it altogether.

### Interrupt widgets don't scroll to the end
- interrupts don't scroll message area to the end

#### Realtime Database Access
- What do we do when the database updates? would it be possible to "watch" for updates somehow? How else do we notify that it's stale?
    - Maybe just hint "use /topics [-r | --refresh] to refresh the display" after a certain amount of time?
    - Same sort of behaviour can happen if we have two separate global options viewer widgets in separate tabs
    
### Message ping animation issues
- message ping doesn't really work (at least not in my terminal context)

### rename_tab tool validations
- rename_tab should reject empty tabs and tabs that are too long
- rename_tab should reject newlines

### ask_user_input tool validations
- ask_user_input shouldn't allow empty lists of questions

### Cleanup of ephemeral DB state
- There's some ephemeral DB state such as review sessions and related matter (review interactions, flashcards, etc.)
- Clean this up semi-periodically once they become stale (lifespan of two weeks or so)

### Gemini Integration
google models:
    - gemini-3.1-pro-preview - https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview
    - gemini-3-flash-preview - https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview
    - gemini-2.5-flash - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash
    - gemini-2.5-flash-lite - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite
    - gemini-2.5-pro - https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro

### Themes
- themes? grab _all_ colours in the app and expose them as an editable file
- see the proposal doc claude made

### Agent rename tab hesitancy
- agent seems hesitant to rename the tab - e.g. "I want to learn about the gcloud CLI" doesn't automatically trigger a rename

## Investigations

### Prompt Caching Anomalies
- I haven't noticed this in a very long time, it might have been an issue in an older, broken version of the caching middleware
- OCCASIONALLY, prompt caching isn't enabled until a rebuild of the state graph is triggered - not sure why?

### Structured response schema unreliable with just python dataclasses
- Noticed this before with the commit subagent - when the response schema was just a dataclass, it frequently returned an empty response: `{"entries": []}`
- This seems to have been fixed by using pydantic models.

### Token Usage with Web Search/Fetch
- token counts are _way_ higher after web search/fetch tools (predictably, but not sure how to detect that)
    - this is because of the silly way anthropic web fetch actually works - it writes code to fetch the webpage and this doesn't really work

## Features

### Session Serialization
- A way to save/restore sessions
- See proposal claude made

### Setup Screen
- add a "setup" screen for when the user hasn't configured their provider

### Welcome Screen
- A little welcome visual on your topics, maybe showing which ones are most practiced, which ones need review, etc.

### List/Table type entries
- What to do about lists in knowledge entries?
    - Notoriously difficult to memorize
    - Same with "tables" of comparisons
- Maybe entries should also have "testing notes"? Notes on how to use them in review mode?

### Autocommit
- a note on the auto-commit tool
    - should be used cautiously to avoid committing hallucinations
    - perhaps roll in _batches_ - use user guidance from the conversation to determine what's true and what's not, only commit with a certain confidence?
    - enabling auto-commit should post a one-time system message warning about how to use safely
    - expose an auto-commit frequency option
    - expose auto-commit USER_PROMPT.md, optional instructions depending on how the user likes to generate their knowledge entries

### User Threads
- Add a way to write notes mid-session on things that aren't relevant now, but could be relevant later.
- Example could be just "/thread <Something the user wants to pick up on later>"
- Then view with "/threads"

### /next
- In learn mode, "/next" can prompt the agent to suggest the next location to learn about, investigating dangling threads

### Resources
- "Resources" per topic
    - How should these be looped in?
        - Direct - just load into context window whenever topic is selected
        - Direct w/ usage description - load into context window selectively, based on usage description
        - RAG based - load into separate vector store, use subagent to perform retrieval/summarization/deep research for Q/A
    - Could be local documents, pdfs, websites
    - "free form" deep research option that uses API extended thinking with tools (web search, etc.)

### Deep Research
- deep research subagent - reviews topics
- "research-eagerness" setting

### Notes Mode
- Add a new mode for just taking notes while reading something else, and automatically converting those into knowledge entries for review later.
- e.g. if I'm reading a book or a webpage, and I want to just take quick notes about what I was doing
- A couple of ways this could work:
    - Manually make notes
    - Follow-along with the work I'm reading as a resource

### Work Mode
- Mode for when I'm using a chat agent during work
- Don't expect a single active topic or anything - instead during the workday I ask a bunch of random questions, and then the agent has to figure out at the end of the day what the best organization into topics/knowledge entries is.

### Refresh Mode
- Like a conversational review, but without review interactions or scoring - just to brush up and recall stuff that I studied before through active review.

### Review Mode

#### Practice Phase
I think the phase diagram could look more like this:
```
(START) → SCOPING → CONFIGURING → PLANNING → REVIEWING ⟲ → SUMMARIZING → (END)
                                     ↓           ↑
                                  PRACTICING ⟲ -/
```
When the agent generates new flashcards, it doesn't really make sense to just present them and expect the user to get them correct the first time around. Instead we need to actually review the flashcards the agent created and then practice them, and _then_ progress to REVIEWING.

Another fun idea: after practice is done, "ping the tab" after 10 minutes to indicate that the user should begin their review.

### Agent's ability to reorganize the database
- make sure the "reorganization" is easy for the agent to do
- e.g., let's say I don't like my notes on topic X
    - ask the agent to restructure them
    - this will necessarily invalidate previous review sessions or flashcards since the knowledge entry IDs/topic IDs they refer to may not exist anymore
    - we could have the agent automatically update the flashcards following the restructuring of the notes.

### Continuous summarization middleware
- Continuous summarization middleware
    - https://platform.claude.com/cookbook/misc-session-memory-compaction

### Comprehensive Token Usage Breakdown
- comprehensive token usage breakdown panel
    - token usage treated as "events" - each event delineating the change in token usage per category
    - token usage events linked to message IDs, so you can click on token usage events to ping the message the event corresponds to
    - token usage events can be displayed in a clickable graph (deltas to minimize widget height)
        - how do summarization events show up?

    - Offer direct anthropic token usage counts: https://platform.claude.com/docs/en/build-with-claude/token-counting

### /logs <namespace>
- /logs <namespace> to view a specific level of logs
- Or some other way of filtering the logs namespace

### Docking widgets
- Ability to dock the options/topics/other widgets to fixed locations (e.g. directly above the chat area), rather than floating as widgets in the chat pane.

### /topics select or /topics list?
- /topics select <topic> and /topics list or find or something

### Subagents pane
- Add a "subagents for session X" pane to see raw output, monitor, cancel, or maybe even provide guidance through chat messages?

### Hover over token usage to have a little display
- can hover over the (+X) token indicator to have it display what it means

### sqlite pane
- subterminal/pane for sqlite to interact with the database?
    - general purpose "sqlite" tool for the agent, which always requests approval of the command it wants to run?

## Infrastructure / Tooling

### Database

#### Cleanup
- cleanup the "curriculum.db" at the repo root
- do a lot of cleaning of the database - feel like we could be a lot more mature about this

#### Migrations
- use a proper migration framework now that the database is getting more mature

### Claude Code

#### CLAUDE.md cleanup
- Present CLAUDE.md is pretty outdated, could use a refresh.

#### Low-Hanging Fruits
- Introduce a queue of really simple issues that claude can handle entirely autonomously overnight
    - Add a skill for this, use proper git workflow with MR format to present proposed changes.

#### Scratchpad / Auto-memory
- Supposedly auto-memory is turned on but I don't see any memory files anywhere
- Optionally give it a scratchpad manually to organize research findings

#### Scheduled Tasks
- Review/update documentation
- Check which context files are out of sync
- Linting
- Search/propose architectural improvements

## External References
- anthropic "fast" mode: https://platform.claude.com/docs/en/build-with-claude/fast-mode
- RAG with https://docs.langchain.com/oss/python/langchain/rag
    - semantic search
- Reranking
- FalkorDB
- BM25
- GraphRAG

