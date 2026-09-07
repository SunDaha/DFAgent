from dfagent.tools.tool import tool
from dfagent.skills.load_skills import get_skill

@tool(name="load_skill")
def load_skill(name:str):
    """Load the full content of a skill by name.

    Args:
        name : skill name
    """
    return get_skill(name)

    
    
    