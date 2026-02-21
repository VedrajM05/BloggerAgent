import logging
from pathlib import Path

class AgentLogger:

    def __init__(self, log_file = "logs/agent.log"):
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok= True)

        self.logger = logging.getLogger("agent_logger")
        self.logger.setLevel(logging.INFO)

        # Prevent duplicate handlers on reload
        if not self.logger.handlers:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def log_state(self, node_name: str, state: dict):
        correlationId = state.get("correlationId")
        topic = state.get("topic")
        plan = state.get("plan")
        sections = state.get("sections", [])
        final_exists = "final" in state

        # If plan is None → avoid AttributeError.
        title = getattr(plan, "blog_title", None)
        # title = getattr(plan, "blog_title", None)
        self.logger.info(
            f"[CID: {correlationId}] | "
            f"[NODE: {node_name}] | "
            f"Topic: {topic} | "
            f"Title: {title} | "
            f"Sections: {len(sections)} | "
            f"Final: {final_exists}"
        )

    def log_prompt(self, node_name: str, correlationId : str, prompt : str):
        
        self.logger.info(
            f"[CID: {correlationId}] | "
            f"[NODE: {node_name}] | "
            f"PROMPT START\n"
            f"-------------------------------------------------------------------------------------------------------\n"
            f"{prompt}\n"
            f"-------------------------------------------------------------------------------------------------------\n"
            f"PROMPT END\n"
        )