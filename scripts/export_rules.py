import os
import shutil

def export_rules():
    # 1. Read SKILL.md
    skill_path = "SKILL.md"
    if not os.path.exists(skill_path):
        print("SKILL.md not found in current directory.")
        return

    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split frontmatter if present
    main_instructions = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            main_instructions = parts[2].strip()

    print("Generating tool-specific rules/skills files...")

    # A. Cursor rules: .cursorrules
    with open(".cursorrules", "w", encoding="utf-8") as f:
        f.write(content)
    print("  - Generated .cursorrules")

    # B. Aider conventions: CONVENTIONS.md
    with open("CONVENTIONS.md", "w", encoding="utf-8") as f:
        f.write(content)
    print("  - Generated CONVENTIONS.md")

    # C. Windsurf rules: .windsurf/rules/job-scraper.md
    os.makedirs(".windsurf/rules", exist_ok=True)
    with open(".windsurf/rules/job-scraper.md", "w", encoding="utf-8") as f:
        f.write(content)
    print("  - Generated .windsurf/rules/job-scraper.md")

    # D. Copilot instructions: .github/copilot-instructions.md
    os.makedirs(".github", exist_ok=True)
    with open(".github/copilot-instructions.md", "w", encoding="utf-8") as f:
        f.write(main_instructions)
    print("  - Generated .github/copilot-instructions.md")

    # E. Mistral Vibe & Hermes: .vibe/skills/job-scraper/SKILL.md & .hermes/skills/job-scraper/SKILL.md
    for agent_dir in [".vibe/skills/job-scraper", ".hermes/skills/job-scraper"]:
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(content)
    print("  - Generated .vibe and .hermes skill directories")

    print("\nAll rules and skills generated successfully!")

if __name__ == "__main__":
    export_rules()
