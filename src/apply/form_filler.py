import os
import re
import json
import time
import requests
from typing import Dict, Any, List
from playwright.sync_api import sync_playwright, Page, Locator
from src.config import Config
from src.apply.profile_manager import save_to_profile_md, load_profile

class FormFiller:
    def __init__(self):
        self.groq_api_key = Config.GROQ_API or os.getenv("GROQ_API")
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_model = "llama-3.1-8b-instant"

    def get_llm_mapping(self, fields: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
        """Calls Groq to map form fields to profile data."""
        if not self.groq_api_key:
            # Fallback to local heuristic mapping if Groq API is not set
            return self._heuristic_mapping(fields, profile)

        system_prompt = (
            "You are an expert browser automation mapping assistant.\n"
            "Your task is to map web form fields to a candidate's user profile.\n"
            "Here is the user profile data:\n"
            f"{json.dumps(profile, indent=2)}\n\n"
            "Rules:\n"
            "1. For text/textarea inputs: find the matching profile value.\n"
            "2. For dropdown/select fields: choose the option value from the 'options' list that is closest semantically to the user profile info.\n"
            "3. For file inputs (type=file): if it's for a Resume/CV, return 'UPLOAD_RESUME'. If for a Cover Letter, return 'UPLOAD_COVER_LETTER'.\n"
            "4. If a field is a custom/dynamic question (e.g. 'Why do you want to join?') and not in the profile, return 'LEARN_REQUIRED' so we can prompt the user.\n"
            "5. If a field is work authorization or gender or race, map it to the closest profile value or closest select option.\n\n"
            "Return response as a JSON object of field index mapping:\n"
            "{\n"
            "  \"mappings\": {\n"
            "     \"<index>\": {\n"
            "         \"value\": \"<value to fill, select, upload, or LEARN_REQUIRED>\",\n"
            "         \"action\": \"fill\" | \"select\" | \"upload\" | \"learn\"\n"
            "     }\n"
            "  }\n"
            "}"
        )

        user_content = f"Here are the extracted web form fields:\n{json.dumps(fields, indent=2)}"

        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.groq_api_key}"
        }

        try:
            res = requests.post(self.groq_url, json=payload, headers=headers, timeout=25)
            res.raise_for_status()
            data = res.json()
            content = data['choices'][0]['message']['content'].strip()
            return json.loads(content).get("mappings", {})
        except Exception as e:
            print(f"[Warning] LLM mapping failed: {e}. Falling back to heuristics.")
            return self._heuristic_mapping(fields, profile)

    def _heuristic_mapping(self, fields: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
        """Backup heuristic field mapping when LLM is unavailable."""
        mappings = {}
        for idx, field in enumerate(fields):
            label = field.get("label", "").lower()
            placeholder = field.get("placeholder", "").lower()
            name = field.get("name", "").lower()
            f_type = field.get("type", "").lower()
            options = field.get("options", [])
            
            # Identify action and value
            action = "fill"
            value = ""
            
            if f_type == "file":
                action = "upload"
                if "cover" in label or "cover" in name:
                    value = "UPLOAD_COVER_LETTER"
                else:
                    value = "UPLOAD_RESUME"
            elif f_type == "select" or options:
                action = "select"
                # Pick first option or map to gender/work auth
                if "gender" in label or "gender" in name:
                    g = profile.get("USER_GENDER", "").lower()
                    matched = [o for o in options if g in o.lower()]
                    value = matched[0] if matched else (options[1] if len(options) > 1 else "")
                else:
                    value = options[1] if len(options) > 1 else ""
            else:
                # Map standard inputs
                if any(x in label or x in name or x in placeholder for x in ["first name", "given name"]):
                    value = profile.get("USER_FIRST_NAME", "")
                elif any(x in label or x in name or x in placeholder for x in ["last name", "surname", "family name"]):
                    value = profile.get("USER_SURNAME", "")
                elif any(x in label or x in name or x in placeholder for x in ["middle name"]):
                    value = profile.get("USER_MIDDLE_NAME", "")
                elif any(x in label or x in name or x in placeholder for x in ["email"]):
                    value = profile.get("USER_EMAIL", "")
                elif any(x in label or x in name or x in placeholder for x in ["phone", "mobile", "contact"]):
                    value = profile.get("USER_PHONE_NUMBER", "")
                elif any(x in label or x in name or x in placeholder for x in ["address", "street"]):
                    value = profile.get("USER_PERMANENT_ADDRESS", "")
                elif any(x in label or x in name or x in placeholder for x in ["location", "city"]):
                    value = profile.get("USER_CURRENT_LOCATION", "")
                else:
                    # Look up in general profile for exact matches or similar keys
                    found = False
                    for pk, pv in profile.items():
                        if pk.lower().replace("_", " ") in label:
                            value = pv
                            found = True
                            break
                    if not found:
                        action = "learn"
                        value = "LEARN_REQUIRED"
                        
            mappings[str(idx)] = {"value": value, "action": action}
        return mappings

    def extract_form_fields(self, page: Page) -> List[Dict[str, Any]]:
        """Traverses the DOM to find fillable input/select/textarea fields."""
        fields = page.evaluate("""() => {
            let root = document;
            const modal = document.querySelector('.jobs-easy-apply-modal, [role="dialog"], #easy-apply-modal, .fade.in');
            if (modal) {
                root = modal;
            }
            
            const results = [];
            const inputs = root.querySelectorAll('input, select, textarea');
            
            inputs.forEach((el, index) => {
                // Skip hidden inputs, submits, check/radio wrappers unless visible
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || el.type === 'hidden' || el.type === 'submit' || el.type === 'button') {
                    return;
                }
                
                // Find label
                let labelText = '';
                if (el.id) {
                    const labelEl = document.querySelector(`label[for="${el.id}"]`);
                    if (labelEl) labelText = labelEl.innerText;
                }
                if (!labelText) {
                    const parentLabel = el.closest('label');
                    if (parentLabel) labelText = parentLabel.innerText;
                }
                if (!labelText) {
                    // Try placeholder or name
                    labelText = el.getAttribute('aria-label') || el.placeholder || el.name || '';
                }
                
                // Gather select options
                const options = [];
                if (el.tagName.toLowerCase() === 'select') {
                    Array.from(el.options).forEach(opt => {
                        options.push(opt.text || opt.value);
                    });
                }
                
                results.push({
                    index: index,
                    tagName: el.tagName.toLowerCase(),
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    placeholder: el.placeholder || '',
                    label: labelText.replace(/\*\s*$/g, '').trim(), // clean asterisk
                    options: options
                });
            });
            return results;
        }""")
        return fields

    def click_apply_button(self, page: Page) -> Any:
        """Clicks the 'Easy Apply' or 'Apply' button, handling new tab redirection."""
        context = page.context
        
        # Set up a listener for new pages
        new_page_holder = []
        def on_page(new_page):
            new_page_holder.append(new_page)
        context.on("page", on_page)
        
        apply_selectors = [
            "button.jobs-apply-button", 
            "a.jobs-apply-button",
            ".jobs-apply-button button",
            ".jobs-apply-button a",
            'button:has-text("Easy Apply")',
            'button:has-text("Apply now")',
            'button:has-text("Apply")',
            'a:has-text("Apply")'
        ]
        
        clicked = False
        for sel in apply_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    print(f"[Apply Button] Clicking apply button matching selector: '{sel}'")
                    btn.click()
                    clicked = True
                    break
            except Exception:
                pass
                
        # Wait a bit for the click to trigger and new page / modal to load
        page.wait_for_timeout(4000)
        
        # Remove the listener
        context.remove_listener("page", on_page)
        
        if clicked:
            if new_page_holder:
                new_page = new_page_holder[0]
                print(f"[Redirect] Detected external career portal opened in a new tab: {new_page.url}")
                new_page.bring_to_front()
                return new_page
            return True
        return False

    def populate_fields_on_page(self, page: Page, fields: List[Dict[str, Any]], mappings: Dict[str, Any], profile: Dict[str, Any]):
        """Fills and populates the given list of fields on the page based on the mappings."""
        for field in fields:
            idx = str(field["index"])
            mapping = mappings.get(idx)
            if not mapping:
                continue
                
            action = mapping.get("action")
            value = mapping.get("value")
            label = field["label"]
            
            # Construct locator
            selector = f'input[name="{field["name"]}"], select[name="{field["name"]}"], textarea[name="{field["name"]}"]'
            if field["id"]:
                selector = f'#{field["id"]}'
                
            locator = page.locator(selector).first
            if not locator.is_visible():
                # Fallback to index-based locator if selector isn't visible
                locator = page.locator(field["tagName"]).nth(field["index"])
                
            try:
                if action == "learn" or value == "LEARN_REQUIRED":
                    # Prompt user to input the missing field
                    print(f"\n[Learning Prompt] Web page asks for: '{label}'")
                    user_val = input(f"Please enter value for '{label}': ").strip()
                    # Learn it! Save to profile and user_profile.md
                    save_to_profile_md(label, user_val)
                    profile[label] = user_val
                    value = user_val
                    action = "fill"
                    
                if action == "upload":
                    path = profile.get("TAILORED_RESUME_PATH") if value == "UPLOAD_RESUME" else profile.get("TAILORED_COVER_LETTER_PATH")
                    if path and os.path.exists(path):
                        print(f"  - Uploading file: {os.path.basename(path)} for '{label}'")
                        locator.set_input_files(path)
                    else:
                        print(f"  - [Warning] Upload path not found for {value}")
                        
                elif action == "select":
                    print(f"  - Selecting option: '{value}' for '{label}'")
                    locator.select_option(label=value)
                    
                elif action == "fill" and value:
                    print(f"  - Filling: '{value}' into '{label}'")
                    locator.fill(value)
                    
            except Exception as fill_err:
                print(f"  [Error] Failed to populate field '{label}': {fill_err}")

    def click_next_button(self, page: Page) -> bool:
        """Attempts to find and click a 'Next' or 'Continue' button on the form step."""
        next_button_selectors = [
            '.jobs-easy-apply-modal button:has-text("Next")',
            '.jobs-easy-apply-modal button:has-text("Continue")',
            '.jobs-easy-apply-modal button:has-text("Review")',
            '[role="dialog"] button:has-text("Next")',
            '[role="dialog"] button:has-text("Continue")',
            '[role="dialog"] button:has-text("Review")',
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Review")'
        ]
        
        for sel in next_button_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    # Exclude submit buttons
                    text = btn.inner_text().lower()
                    if "submit" in text or "finish" in text or "send" in text:
                        continue
                        
                    print(f"[Form Automation] Clicking '{btn.inner_text()}' to proceed to next step...")
                    btn.click()
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                pass
        return False

    def fill_form(self, page: Page, profile: Dict[str, Any]) -> bool:
        """Main flow: handles cookies, clicks apply, and fills multi-step form dialogs."""
        # 1. Handle Cookie/Privacy Banner
        self.handle_cookie_walls(page)
        
        active_page = page
        if "linkedin.com" in page.url:
            print("[Apply Button] We are on LinkedIn. Locating Apply/Easy Apply button...")
            res = self.click_apply_button(page)
            if not res:
                print("[Apply Button] Failed to find or click Apply button.")
                return False
            
            if isinstance(res, Page):
                active_page = res
                active_page.wait_for_timeout(3000)
            else:
                page.wait_for_timeout(3000)
                if "linkedin.com" not in page.url:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                    active_page = page
        
        # 3. Process form steps
        for step in range(10):  # Process up to 10 steps/pages of the form
            # If we are STILL on linkedin.com, we MUST check if the Easy Apply modal is open.
            # If we are on linkedin.com but NO modal is open, we must not fill anything!
            if "linkedin.com" in active_page.url:
                modal = active_page.locator('.jobs-easy-apply-modal, [role="dialog"], #easy-apply-modal').first
                if not modal.is_visible():
                    print("[Apply Info] LinkedIn Easy Apply modal is not open. Skipping form extraction on LinkedIn page.")
                    break
                    
            fields = self.extract_form_fields(active_page)
            if not fields:
                print(f"[Form Analysis] No form fields found on step {step + 1}.")
                break
                
            print(f"[Form Analysis] Step {step + 1}: Found {len(fields)} fields.")
            
            # Map Fields via LLM / Heuristics
            mappings = self.get_llm_mapping(fields, profile)
            
            # Fill Fields
            self.populate_fields_on_page(active_page, fields, mappings, profile)

            # Check if there is a "Next", "Continue", or "Review" button to proceed to the next step
            button_clicked = self.click_next_button(active_page)
            if not button_clicked:
                break
                
        return True

    def handle_cookie_walls(self, page: Page):
        """Looks for and accepts cookie walls to prevent overlays."""
        cookie_keywords = ["accept", "allow all", "accept all", "agree", "agree & close", "close"]
        for kw in cookie_keywords:
            try:
                btn = page.locator(f'button:has-text("{kw}"), a:has-text("{kw}")').first
                if btn.is_visible():
                    print(f"[Cookie Wall] Clicking consent button with text: '{kw}'")
                    btn.click()
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass
