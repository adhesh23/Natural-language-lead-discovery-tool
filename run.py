"""CLI runner for the Lead Discovery & Decision-Maker Pipeline."""

import sys
from lead_discovery_pipeline.orchestrator import execute_pipeline

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    execute_pipeline(config_file)
