from pathlib import Path
import getpass

# AI Agent Name
AGENTNAME = "DFAgent"


# work_dir
WORKDIR = Path.cwd()

# work_file
WORKFILE = Path(WORKDIR).name

# user_home
USERHOME = Path.home()



# user
USERNAME = getpass.getuser()


# context_compact properties
CONTEXT_LIMIT = 50000
KEEP_RECENT = 20
PERSIST_THRESHOLD = 30000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

# retries
MAX_REACTIVE_RETRIES = 5


#Hook
MAX_TOOL_OUTPUR_SIZE = 100000


