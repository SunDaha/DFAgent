import yaml
from dfagent import WORKDIR


# Skills 文件目录
SKILLS_DIR =  (WORKDIR/"skills").resolve()

SKILL_REGISTRY: dict[str, dict] = {}

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def _scan_skills():
    """Scan skills/ dir, populate SKILL_REGISTRY with name/description/content."""
    
    if not SKILLS_DIR.exists():
        return
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "SKILL.md"
        if manifest.exists():
            raw = manifest.read_text()
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", d.name)
            desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
            SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}


def list_skills() -> str:
    """List all skills (name + one-line description)."""
    # 每次都扫描加载一遍skill
    _scan_skills()
    if not SKILL_REGISTRY:
        return "(no skills found)"
    lines = [f"- **{s['name']}**: {s['description']}" for s in SKILL_REGISTRY.values()]
    return "\n".join(lines)

    
def get_skill(name: str):
    """Get skill info(dict) by name"""
    skill = SKILL_REGISTRY.get(name) 
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]