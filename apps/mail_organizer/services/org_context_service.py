# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Organizational Context Service.

Loads, caches, and resolves rich organizational intelligence from:
  config/organization/company_profile.yaml
  config/organization/departments.yaml
  config/organization/roster.yaml
  config/organization/external_stakeholders.yaml

Provides structured persona lookup, active project keyword matching,
automatic VIP qualification, and formatted prompt enrichment blocks.
"""
import os
import re
from typing import Optional, List, Dict, Any

try:
    import yaml
except ImportError:
    yaml = None

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RELEASE_ROOT = os.path.normpath(os.path.join(_APP_DIR, '..', '..'))
_CONFIG_ORG_DIR = os.path.normpath(os.path.join(_RELEASE_ROOT, 'config', 'organization'))
if not os.path.exists(_CONFIG_ORG_DIR):
    _CONFIG_ORG_DIR = os.path.normpath(os.path.join(_APP_DIR, '..', 'config', 'organization'))

_ORG_CACHE: Dict[str, Any] = {}
_ORG_LOADED: bool = False


def _load_yaml(filename: str) -> Dict[str, Any]:
    if not yaml:
        return {}
    path = os.path.join(_CONFIG_ORG_DIR, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[org_context_service] Failed loading {filename}: {e}")
        return {}


def _ensure_org_loaded() -> None:
    global _ORG_CACHE, _ORG_LOADED
    if _ORG_LOADED:
        return
    _ORG_CACHE['company'] = _load_yaml('company_profile.yaml')
    _ORG_CACHE['departments'] = _load_yaml('departments.yaml').get('departments', {})
    _ORG_CACHE['employees'] = _load_yaml('roster.yaml').get('employees', [])
    _ORG_CACHE['stakeholders'] = _load_yaml('external_stakeholders.yaml')
    _ORG_LOADED = True


def reload_org_context() -> None:
    """Force reload organizational data from disk."""
    global _ORG_LOADED
    _ORG_LOADED = False
    _ensure_org_loaded()


def _clean_email(email_str: str) -> str:
    if not email_str:
        return ""
    # Extract email from "Name <user@domain.com>"
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', email_str)
    return match.group(0).lower() if match else email_str.strip().lower()


def resolve_sender_persona(sender_raw: str) -> Optional[Dict[str, Any]]:
    """Look up an employee or external VIP contact from the organization directory."""
    _ensure_org_loaded()
    email = _clean_email(sender_raw)
    if not email:
        return None

    # Check internal employee roster
    for emp in _ORG_CACHE.get('employees', []):
        if emp.get('email', '').lower() == email:
            dept_name = emp.get('department')
            dept_info = _ORG_CACHE.get('departments', {}).get(dept_name, {})
            return {
                "type": "internal_employee",
                "name": emp.get('name'),
                "email": emp.get('email'),
                "title": emp.get('title'),
                "department": dept_name,
                "dept_description": dept_info.get('description', ''),
                "hierarchy_level": emp.get('hierarchy_level'),
                "manager_email": emp.get('manager_email'),
                "approval_limit_usd": emp.get('approval_limit_usd', 0),
                "is_vip": emp.get('is_vip', False),
                "assigned_projects": emp.get('assigned_projects', []),
            }

    # Check strategic client contacts
    stakeholders = _ORG_CACHE.get('stakeholders', {})
    for client in stakeholders.get('strategic_clients', []):
        for contact in client.get('lead_contacts', []):
            if contact.get('email', '').lower() == email:
                return {
                    "type": "strategic_client",
                    "company_name": client.get('company_name'),
                    "tier": client.get('tier'),
                    "name": contact.get('name'),
                    "email": contact.get('email'),
                    "title": contact.get('title'),
                    "is_vip": contact.get('is_vip', True),
                    "sla_tier": client.get('sla_tier', ''),
                }

    return None


def is_org_vip(sender_raw: str) -> bool:
    """Check if the sender is marked VIP in the organization roster or strategic client list."""
    persona = resolve_sender_persona(sender_raw)
    if persona and persona.get('is_vip'):
        return True
    
    # Check domain against strategic client domains
    _ensure_org_loaded()
    email = _clean_email(sender_raw)
    domain = email.split('@')[-1] if '@' in email else ''
    stakeholders = _ORG_CACHE.get('stakeholders', {})
    for client in stakeholders.get('strategic_clients', []):
        if client.get('domain', '').lower() == domain:
            return True
    return False


def get_department_labels(sender_raw: str) -> List[str]:
    """Retrieve default department/client labels for a sender."""
    persona = resolve_sender_persona(sender_raw)
    if not persona:
        return []
    
    if persona.get('type') == 'internal_employee':
        dept_name = persona.get('department')
        dept_info = _ORG_CACHE.get('departments', {}).get(dept_name, {})
        return list(dept_info.get('default_labels', []))
    elif persona.get('type') == 'strategic_client':
        return [f"Client/{persona.get('company_name', '').replace(' ', '')}"]
    return []


def resolve_active_projects(text: str) -> List[Dict[str, Any]]:
    """Match subject/body text against known strategic company projects."""
    _ensure_org_loaded()
    company_data = _ORG_CACHE.get('company', {})
    projects = company_data.get('active_strategic_projects', [])
    matched = []
    text_lower = text.lower()
    for proj in projects:
        name_lower = proj.get('name', '').lower()
        code_lower = proj.get('code', '').lower()
        if name_lower in text_lower or code_lower in text_lower or proj.get('code', '') in text:
            matched.append(proj)
    return matched


def build_org_context_for_prompt(sender_raw: str, subject: str, body: str) -> str:
    """
    Build a rich, structured organizational context block to inject into the LLM prompt.
    """
    _ensure_org_loaded()
    persona = resolve_sender_persona(sender_raw)
    projects = resolve_active_projects(f"{subject} {body}")
    company_data = _ORG_CACHE.get('company', {}).get('company', {})

    lines = [
        "--- 🏢 ORGANIZATIONAL CONTEXT & SENDER INTELLIGENCE ---",
        f"• Company: {company_data.get('name', 'TechGlobal Cloud Solutions')}",
    ]

    if persona:
        if persona.get('type') == 'internal_employee':
            lines.append(f"• Sender Identity: {persona.get('name')} <{persona.get('email')}>")
            lines.append(f"• Role & Title: {persona.get('title')} ({persona.get('department')} Dept)")
            lines.append(f"• Hierarchy Level: {persona.get('hierarchy_level')}")
            lines.append(f"• Manager: {persona.get('manager_email') or 'None (Top Executive)'}")
            lines.append(f"• VIP Priority Status: {'YES (Executive/Critical)' if persona.get('is_vip') else 'Standard'}")
            if persona.get('assigned_projects'):
                proj_list = persona.get('assigned_projects')
                lines.append(f"• Assigned Projects: {', '.join(str(p) for p in proj_list) if isinstance(proj_list, list) else str(proj_list)}")
        elif persona.get('type') == 'strategic_client':
            lines.append(f"• Sender Identity: {persona.get('name')} <{persona.get('email')}>")
            lines.append(f"• External Client: {persona.get('company_name')} ({persona.get('tier')})")
            lines.append(f"• Client Title: {persona.get('title')}")
            lines.append(f"• Service SLA Tier: {persona.get('sla_tier')}")
            lines.append("• VIP Priority Status: YES (Tier-1 Strategic Account)")
    else:
        email = _clean_email(sender_raw)
        lines.append(f"• Sender: {email} (External / Unregistered Sender)")

    if projects:
        proj_strs = [f"{p.get('name')} ({p.get('description')})" for p in projects]
        lines.append(f"• Detected Active Project Context: {'; '.join(proj_strs)}")

    lines.append("---------------------------------------------------------")
    return "\n".join(lines)


# Public alias
build_org_context_block = build_org_context_for_prompt
