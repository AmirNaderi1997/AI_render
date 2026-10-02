#!/usr/bin/env python3
"""Verify model environment configuration.

Checks that all required models are configured via .env variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

print("\n" + "=" * 80)
print("ENVIRONMENT VARIABLE CONFIGURATION")
print("=" * 80)

models = {
    "LLM_MODEL": "Primary LLM for plan generation",
    "LLM_FALLBACK_MODEL": "Fallback LLM if primary returns empty",
    "CORRECTION_MODEL": "LLM for Persian text correction",
    "VISION_MODEL": "Vision model for effect analysis",
    "EFFECT_MODEL": "Model for effect selection (can use vision)",
    "IMAGE_MODEL": "Model for image/overlay generation",
}

print("\nConfigured Models:")
print(f"{'Variable':<25} {'Value':<30} {'Status':<8}")
print("-" * 65)

config_ok = True
for var_name, description in models.items():
    value = os.getenv(var_name, "<not set>")
    status = "OK" if value != "<not set>" else "MISSING"
    value_short = value if len(value) <= 30 else value[:27] + "..."
    print(f"{var_name:<25} {value_short:<30} {status:<8}")
    if status == "MISSING":
        config_ok = False

print("\n" + "=" * 80)
print("FALLBACK LOGIC")
print("=" * 80)

llm = os.getenv("LLM_MODEL", "<not set>")
fallback = os.getenv("LLM_FALLBACK_MODEL", "<not set>")
print(f"\nPrimary LLM:  {llm}")
print(f"Fallback LLM: {fallback}")
print(f"Retry logic:  If LLM_MODEL returns empty body → use LLM_FALLBACK_MODEL")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
if config_ok:
    print("✓ All required models configured")
else:
    print("✗ Some models missing (will use defaults or fail)")

print("\n" + "=" * 80 + "\n")
