from pathlib import Path

# word_dir
WORKDIR = Path.cwd()


# context_compact properties
CONTEXT_LIMIT = 50000
KEEP_RECENT = 20
PERSIST_THRESHOLD = 30000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

# retries
MAX_REACTIVE_RETRIES = 5