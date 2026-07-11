import os
import re
from dotenv import load_dotenv

MANDATORY_FIELDS = [
    "USER_FIRST_NAME",
    "USER_MIDDLE_NAME",
    "USER_SURNAME",
    "USER_GENDER",
    "USER_AGE",
    "USER_CURRENT_LOCATION",
    "USER_PERMANENT_ADDRESS",
    "USER_PHONE_NUMBER",
    "USER_EMAIL",
    "TAILORED_RESUME_PATH",
    "TAILORED_COVER_LETTER_PATH"
]

PROFILE_MD_FILE = "user_profile.md"

def update_env_file(key, value, filepath=".env"):
    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}='{value}'\n")
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f"{key}='{value}'\n")
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def load_profile() -> dict:
    load_dotenv(override=True)
    profile = {}
    
    # 1. Load from environment
    for field in MANDATORY_FIELDS:
        profile[field] = os.getenv(field, "").strip()
        
    # 2. Load from user_profile.md
    if os.path.exists(PROFILE_MD_FILE):
        with open(PROFILE_MD_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # Parse markdown tables or bullet points
        # Format: - Key: Value or | Key | Value |
        pattern = r"[-*]\s*([^:]+):\s*(.*)"
        for match in re.finditer(pattern, content):
            key = match.group(1).strip()
            val = match.group(2).strip()
            profile[key] = val
            
    return profile

def save_to_profile_md(key: str, value: str):
    """Appends or updates a key-value pair in user_profile.md."""
    profile_data = {}
    if os.path.exists(PROFILE_MD_FILE):
        with open(PROFILE_MD_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            if line.strip().startswith("-"):
                parts = line.strip()[1:].split(":", 1)
                if len(parts) == 2:
                    profile_data[parts[0].strip()] = parts[1].strip()
    
    profile_data[key] = value
    
    # Write back clean list
    with open(PROFILE_MD_FILE, "w", encoding="utf-8") as f:
        f.write("# User Profile & Learned Inputs\n\n")
        f.write("Here is the list of all recorded information used for job applications:\n\n")
        for k, v in sorted(profile_data.items()):
            f.write(f"- {k}: {v}\n")

def check_and_setup_profile() -> dict:
    print("\n" + "=" * 50)
    print("CHECKING USER PROFILE CONFIGURATION...")
    print("=" * 50)
    
    profile = load_profile()
    missing_fields = []
    
    for field in MANDATORY_FIELDS:
        if not profile.get(field):
            if field == "USER_MIDDLE_NAME":
                # Middle name is optional
                profile[field] = ""
                update_env_file(field, "")
                continue
            missing_fields.append(field)
            
    if missing_fields:
        print("\n[Action Required] Some mandatory profile fields are missing in .env or user_profile.md:")
        for f in missing_fields:
            print(f"  - {f}")
        print("\nPlease fill in the details below:")
        
        for f in missing_fields:
            prompt_name = f.replace("USER_", "").replace("_", " ").title()
            val = input(f"Enter {prompt_name}: ").strip()
            profile[f] = val
            update_env_file(f, val)
            save_to_profile_md(f, val)
            
        print("\n[Success] All mandatory fields updated and saved successfully!")
        load_dotenv(override=True)
        
    return profile
