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
Pydantic Configuration Validation Schemas.

Validates:
  - config/connectors.yaml           -> ConnectorsConfig
  - config/delegation_policies.yaml  -> DelegationPoliciesConfig
  - config/user_persona.yaml         -> UserPersonaConfig

Supports automatic ${ENV_VAR} interpolation across all string fields.
Fails fast on boot with clear, actionable validation error messages.
"""
import os
import re
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

try:
    import yaml
except ImportError:
    yaml = None


# ── Environment Variable Interpolation ────────────────────────────────────────

def _interpolate_env_vars(obj: Any) -> Any:
    """Recursively replace ${VAR_NAME} or $VAR_NAME with os.environ values."""
    if isinstance(obj, str):
        def _repl(match):
            var_name = match.group(1) or match.group(2)
            val = os.getenv(var_name)
            if val is None:
                return f"${{{var_name}}}"
            return val
        return re.sub(r'\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)', _repl, obj)
    elif isinstance(obj, dict):
        return {k: _interpolate_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_interpolate_env_vars(elem) for elem in obj]
    return obj


def load_yaml_with_env(path: str) -> dict:
    """Load a YAML file and interpolate environment variables."""
    if not yaml:
        raise ImportError("PyYAML is required to parse configuration files.")
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        raw_data = yaml.safe_load(f) or {}
    return _interpolate_env_vars(raw_data)


# ── Connectors Schema (config/connectors.yaml) ─────────────────────────────────

class ExternalRAGConfig(BaseModel):
    endpoint: str = Field(description="HTTP REST endpoint for querying RAG")
    modify_endpoint: Optional[str] = Field(default=None, description="Optional endpoint for document updates/feedback")
    auth_header: Optional[str] = Field(default=None, description="Authorization header value, e.g. Bearer token")
    description: Optional[str] = Field(default="", description="Description of the topics/knowledge indexed in this RAG")
    timeout_seconds: float = Field(default=2.0, ge=0.5, le=10.0, description="Query timeout in seconds")


class MCPServerConfig(BaseModel):
    transport: str = Field(default="stdio", description="MCP transport: 'stdio' or 'sse' or 'mock'")
    command: Optional[str] = Field(default=None, description="Executable command for stdio, e.g. 'npx'")
    args: Optional[List[str]] = Field(default_factory=list, description="Command line arguments")
    url: Optional[str] = Field(default=None, description="URL endpoint for SSE transport")
    env: Optional[Dict[str, str]] = Field(default_factory=dict, description="Environment variables for the MCP process")


class GmailSearchConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable historical Gmail mailbox search")
    max_past_threads: int = Field(default=3, ge=1, le=10, description="Max past threads to inspect")
    search_scope_months: int = Field(default=6, ge=1, le=24, description="Search time window in months")


class CalendarConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable calendar free/busy lookup")
    provider: str = Field(default="google", description="Calendar provider: 'google', 'outlook', or 'mock'")
    timezone: str = Field(default="UTC", description="User's primary timezone")
    buffer_minutes: int = Field(default=15, ge=0, le=60, description="Buffer time between scheduled slots")


class ERPFinancialConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable ERP/Ledger lookup")
    provider: str = Field(default="mock", description="Provider: 'stripe', 'quickbooks', 'netsuite', 'mock'")
    endpoint: Optional[str] = Field(default=None, description="API endpoint for ledger queries")


class RoutingRule(BaseModel):
    tags: List[str] = Field(description="Context tags that trigger these connectors")
    connectors: List[str] = Field(description="List of connector identifiers to invoke")


class ConnectorsConfig(BaseModel):
    external_rag_services: Dict[str, ExternalRAGConfig] = Field(
        default_factory=dict,
        description="External pre-existing enterprise RAG services"
    )
    mcp_servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        description="Outbound Model Context Protocol servers"
    )
    gmail_search: GmailSearchConfig = Field(default_factory=GmailSearchConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    erp_financial: ERPFinancialConfig = Field(default_factory=ERPFinancialConfig)
    routing_rules: List[RoutingRule] = Field(
        default_factory=list,
        description="Deterministic tag-to-connector mappings"
    )


# ── Delegation Policies Schema (config/delegation_policies.yaml) ──────────────

class MultiRecipientToPolicy(BaseModel):
    strategy: str = Field(default="semantic_mention_priority", description="Strategy: semantic_mention_priority | first_recipient | all_active")
    broadcast_threshold: int = Field(default=4, ge=2, le=50, description="Recipients count above which email is treated as broadcast")


class TeammateHandlingPolicy(BaseModel):
    suppress_draft_if_internal_reply: bool = Field(default=True, description="Suppress draft if an internal teammate replied")
    reopen_on_unanswered_followups: int = Field(default=2, ge=1, le=5, description="Follow-ups before escalating back to user")


class DynamicDelegationStrategy(BaseModel):
    trigger: str = Field(description="Trigger condition or tag query")
    resolver: str = Field(description="Resolver function name, e.g. pm_service.get_project_lead")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Parameters passed to resolver")
    template: str = Field(description="Delegation reply template with {name}, {email} placeholders")


class MissingInformationPolicy(BaseModel):
    action: str = Field(default="create_internal_task_and_holding_reply", description="Action when critical facts are missing")
    default_holding_reply: Optional[str] = Field(
        default="Thank you for your message. I am confirming the details with our team and will follow up shortly.",
        description="Standard external holding reply"
    )


class DelegationPoliciesConfig(BaseModel):
    multi_recipient_to: MultiRecipientToPolicy = Field(default_factory=MultiRecipientToPolicy)
    teammate_handling: TeammateHandlingPolicy = Field(default_factory=TeammateHandlingPolicy)
    dynamic_delegation_strategies: List[DynamicDelegationStrategy] = Field(default_factory=list)
    missing_information: MissingInformationPolicy = Field(default_factory=MissingInformationPolicy)


# ── User Persona Schema (config/user_persona.yaml) ────────────────────────────

class UserPersonaConfig(BaseModel):
    name: str = Field(description="User's full name")
    title: str = Field(description="User's professional job title")
    department: Optional[str] = Field(default="", description="User's primary department")
    organization: str = Field(description="User's company or organization name")
    tone: str = Field(default="direct, collegial, executive", description="Desired tone of drafted replies")
    signature: str = Field(description="Default email signature block")
    communication_rules: Optional[List[str]] = Field(
        default_factory=list,
        description="Specific behavioral rules for the LLM when writing in user's voice"
    )


# ── Validation Loaders ────────────────────────────────────────────────────────

_DEFAULT_CONFIG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'config'))


def load_and_validate_connectors_config(path: Optional[str] = None) -> ConnectorsConfig:
    target_path = path or os.path.join(_DEFAULT_CONFIG_DIR, 'connectors.yaml')
    if not os.path.exists(target_path):
        example_path = os.path.join(_DEFAULT_CONFIG_DIR, 'connectors.example.yaml')
        if os.path.exists(example_path):
            target_path = example_path
        else:
            return ConnectorsConfig()
    data = load_yaml_with_env(target_path)
    return ConnectorsConfig(**data)


def load_and_validate_delegation_config(path: Optional[str] = None) -> DelegationPoliciesConfig:
    target_path = path or os.path.join(_DEFAULT_CONFIG_DIR, 'delegation_policies.yaml')
    if not os.path.exists(target_path):
        example_path = os.path.join(_DEFAULT_CONFIG_DIR, 'delegation_policies.example.yaml')
        if os.path.exists(example_path):
            target_path = example_path
        else:
            return DelegationPoliciesConfig()
    data = load_yaml_with_env(target_path)
    return DelegationPoliciesConfig(**data)


def load_and_validate_user_persona_config(path: Optional[str] = None) -> UserPersonaConfig:
    target_path = path or os.path.join(_DEFAULT_CONFIG_DIR, 'user_persona.yaml')
    if not os.path.exists(target_path):
        example_path = os.path.join(_DEFAULT_CONFIG_DIR, 'user_persona.example.yaml')
        if os.path.exists(example_path):
            target_path = example_path
        else:
            return UserPersonaConfig(
                name="Marcus Vance",
                title="Chief Technology Officer",
                organization="TechGlobal Cloud Solutions",
                signature="Best regards,\nMarcus Vance | CTO"
            )
    data = load_yaml_with_env(target_path)
    return UserPersonaConfig(**data)


def validate_all_configs(config_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate all enterprise configuration files at startup.
    Returns dict of validated models or raises ValidationError on invalid schema.
    """
    cdir = config_dir or _DEFAULT_CONFIG_DIR
    results = {}
    results['connectors'] = load_and_validate_connectors_config(os.path.join(cdir, 'connectors.yaml'))
    results['delegation'] = load_and_validate_delegation_config(os.path.join(cdir, 'delegation_policies.yaml'))
    results['persona'] = load_and_validate_user_persona_config(os.path.join(cdir, 'user_persona.yaml'))
    return results
