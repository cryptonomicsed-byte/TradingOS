import os
from typing import List, Dict

class HermesPrompts:
    SYSTEM_PROMPT = """
    You are Hermes, the Master Orchestrator of TradingOS. 
    Your goal is to decompose high-level trading intents into specific tasks for specialized agents.
    
    Specialized Agents available:
    1. grok_scout: Scans X/Twitter for sentiment and hype velocity.
    2. claude_architect: Parses Pine Script and synthesizes strategy logic.
    3. julia_quant: Runs high-performance backtests and calculates risk metrics.
    4. llama_auditor: Audits on-chain contracts for rug-pull risks.
    5. whale_watcher: Tracks large wallet movements and liquidity anomalies.
    
    Respond in JSON format with a 'plan' key containing a list of tasks.
    Each task must have 'agent', 'action', and 'params'.
    """

    @staticmethod
    def get_decomposition_prompt(intent: str) -> str:
        return f"User Intent: {intent}\nDecompose this into a multi-agent plan."

class HermesAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    def plan(self, intent: str) -> List[Dict]:
        print(f"🧠 Hermes reasoning about: {intent}")
        # In a hardened system, this would call Claude with the SYSTEM_PROMPT
        # and parse the JSON output.
        return [
            {"agent": "grok_scout", "action": "scan", "params": {"ticker": "BTC"}},
            {"agent": "whale_watcher", "action": "track", "params": {"ticker": "BTC", "threshold": 1000000}}
        ]
