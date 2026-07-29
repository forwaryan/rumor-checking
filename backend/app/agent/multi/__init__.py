"""Multi-agent protocol definitions.

Inspired by:
- OpenAI Swarm: lightweight agent (model + instructions + tools), per-agent model
- CrewAI: role/goal/tools per agent, task-based assignment
- LangGraph: conditional routing (loop-back edge), RetryPolicy, dependency graph

Agents cooperate through a shared `AgentState` blackboard rather than passing
messages: each sub-agent reads what it needs and writes its output back, and the
Supervisor sequences them by their declared dependencies. This keeps the agents
small and composable and mirrors how the single-agent runner already works.

Each agent has:
- role: what it does
- goal: what outcome it aims for (guides LLM behavior)
- model: which LLM to use (heterogeneous model selection)
- tools: which tools it has access to
- retry policy: how many times to retry on failure
- skip condition: when to skip this agent entirely
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, Protocol

from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext


class AgentRole(str, Enum):
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"
    CRITIC = "critic"
    REPORT = "report"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


SkipCondition = Callable[[AgentState], bool]


@dataclass
class AgentConfig:
    """Per-agent configuration — the full identity of a sub-agent.

    Mirrors the best of Swarm (model per agent), CrewAI (role/goal/tools),
    and LangGraph (retry policy, conditional routing).
    """

    model: Optional[str] = None
    temperature: Optional[float] = None
    max_retries: int = 1
    timeout_seconds: Optional[float] = None
    goal: str = ""
    tools: List[str] = field(default_factory=list)
    skip_when: Optional[SkipCondition] = None


@dataclass
class SubAgentResult:
    """Result of a sub-agent's execution."""

    role: AgentRole
    status: AgentStatus
    actions_taken: List[str] = field(default_factory=list)
    error: Optional[str] = None
    model_used: Optional[str] = None
    output: Any = None


class SubAgent(Protocol):
    """Protocol for a specialized sub-agent."""

    role: AgentRole
    description: str
    config: AgentConfig

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        """Execute this agent's responsibilities, mutating state in place."""
        ...

    @property
    def dependencies(self) -> List[AgentRole]:
        """Roles that must complete before this agent can run."""
        ...

